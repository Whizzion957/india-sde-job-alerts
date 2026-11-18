import test from "node:test";
import assert from "node:assert/strict";
import {spawnSync} from "node:child_process";
import {fileURLToPath} from "node:url";
import {classifyJob, defaults, families, matchCatalog, matchJob, skillSearchText} from "../dist/match.js";

const posting = (title, description = "", overrides = {}) => ({
  title, location:"Bengaluru", workplace:"hybrid", ...classifyJob(title,description), ...overrides,
});

test("zero-experience Telegram mode sends only confirmed zero-year matches", () => {
  const jobs = [
    {...posting("Data Engineer", "0–2 years of relevant experience"), id:"zero"},
    {...posting("Data Engineer", "1 year of relevant experience"), id:"one"},
    {...posting("Graduate Data Engineer"), id:"unknown"},
    {...posting("Data Engineer", "No prior experience required", {location:"Remote"}), id:"review"},
  ];
  const matcher = fileURLToPath(new URL("../src/telegram_matches.mjs", import.meta.url));
  const result = spawnSync(process.execPath, [matcher], {
    input:JSON.stringify({jobs, preferences:{years:1}, archived:[], applied:[], zeroExperienceOnly:true}),
    encoding:"utf8",
  });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(result.stdout).map(x=>x.job.id), ["zero"]);
});
test("tech roles extend beyond software, with multiple applicable families", () => {
  const titles = ["Android Developer","Decision Scientist","Analytics Engineer","NLP Engineer",
    "Site Reliability Engineer","Cloud Security Engineer","Software Test Engineer","FPGA Design Engineer",
    "Application Support Engineer","Technical Product Manager"];
  titles.forEach((title,i) => assert.ok(classifyJob(title).families.includes(families[i]),title));
  assert.deepEqual(classifyJob("Analytics Engineer").families,[families[1],families[2]]);
  assert.equal(classifyJob("Member of Technical Staff").seniority,"unknown");
  assert.equal(classifyJob("Staff Member of Technical Staff").seniority,"lead");
  assert.deepEqual(classifyJob("AI Marketing Manager","Python SQL").families,[]);
  assert.deepEqual(classifyJob("Director, Growth Sales (AI & Digital Natives)").families,[]);
  assert.deepEqual(classifyJob("Head of AMER Startups (AI Sales)").families,[]);
  assert.deepEqual(classifyJob("Partner Development Manager, AI Partnerships").families,[]);
  assert.ok(classifyJob("Software Engineer, Marketing").families.includes(families[0]));
  assert.ok(classifyJob("Forward Deployed Engineer, Industry Solutions").families.includes(families[0]));
  assert.ok(classifyJob("Software Development Engineer").families.includes(families[0]));
  assert.ok(classifyJob("Software Dev Engineer I, L4").families.includes(families[0]));
  assert.equal(classifyJob("Software Dev Engineer I, L4").seniority,"entry");
  assert.ok(classifyJob("Technical Services Engineer (Weekend Shift)").families.includes(families[8]));
  assert.ok(classifyJob("Staff Engineer, Revenue Experiences","Building large-scale, distributed systems.").families.includes(families[0]));
  assert.deepEqual(classifyJob("Research Scientist","Wet lab biochemistry").families,[]);
  assert.ok(classifyJob("Research Scientist","Training deep learning models").families.includes(families[3]));
  assert.deepEqual(classifyJob("Engineer","Road inspection").families,[]);
  assert.ok(classifyJob("Engineer","Build software applications with Java and SQL.").families.includes(families[0]));
});

test("Discover and Telegram share posting-age and personal visibility filters", () => {
  const jobs = [
    {...posting("Software Engineer I", "1 year of software engineering experience"), id:"open",posted:"2026-11-18"},
    {...posting("Software Engineer I", "1 year of software engineering experience"), id:"archived",posted:"2026-11-18"},
    {...posting("Software Engineer I", "1 year of software engineering experience"), id:"applied",posted:"2026-11-18"},
    {...posting("Software Engineer I"), id:"undated"},
    {...posting("Software Engineer I"), id:"older",posted:"2026-11-16"},
  ];
  const result = matchCatalog(jobs, {...defaults,maxAgeDays:1,includeUndated:false,hideApplied:true},
    {archived:["archived"],applied:["applied"]}, new Date(2026,10,18,12));
  assert.deepEqual(result.map(x=>x.job.id),["open"]);
  assert.equal(result[0].match.uncertain,false);
});
test("evidence for experience distinguishes minimums, ranges and preferences", () => {
  assert.equal(classifyJob("Data Engineer","Minimum: 2–4 years of professional experience.").minYears,2);
  assert.equal(classifyJob("Data Engineer","6 months of relevant experience.").minYears,0.5);
  assert.equal(classifyJob("Data Engineer","5 years of experience or 2 years of experience with a master's.").minYears,2);
  assert.equal(classifyJob("Data Engineer","4 years of engineering experience. 1 year of experience in SQL.").minYears,4);
  assert.equal(classifyJob("Data Engineer","Minimum qualifications: Python. Preferred qualifications: 4 years of experience.").minYears,null);
  assert.equal(classifyJob("Data Engineer","Up to 2 years of experience.").minYears,null);
  assert.equal(classifyJob("Android Engineer","3+ years of professional software-development experience").minYears,3);
  assert.equal(classifyJob("Backend Engineer","2+ years of backend engineering experience, preferably in finance.").minYears,2);
  assert.equal(classifyJob("Data Engineer","We have 20 years of experience building SaaS.").minYears,null);
  const alternate = posting("Data Scientist","PhD with 3+ years, MS with 6+ years, or BS with 8+ years of data science or quantitative modeling experience.");
  assert.equal(alternate.minYears,3);
  assert.ok(matchJob(alternate,{years:4}).uncertain);
});
test("location distinguishes a global remote job, restricted remote and unknown scopes", () => {
  const evaluate = (location, preferences) => matchJob(posting("Graduate Data Engineer","",{location}),preferences);
  assert.equal(evaluate("Hyderabad").uncertain,false);
  assert.equal(evaluate("Remote - U.S. only").eligible,false);
  assert.equal(evaluate("Worldwide except India").eligible,false);
  assert.equal(evaluate("Worldwide except UK").uncertain,false);
  assert.equal(evaluate("Worldwide except India",{location:"Hyderabad"}).eligible,false);
  assert.equal(evaluate("Remote LATAM").eligible,false);
  assert.equal(evaluate("Washington DC-metro area").eligible,false);
  assert.equal(evaluate("Worldwide remote").uncertain,false);
  assert.equal(evaluate("Remote (APAC)").uncertain,true);
  assert.equal(evaluate("Remote - EMEA").eligible,false);
  assert.equal(evaluate("Bangalore",{location:"Bengaluru"}).uncertain,false);
  assert.equal(evaluate("Mumbai",{location:"Bengaluru"}).eligible,false);
  assert.equal(evaluate("Mumbai, India",{location:"Bengaluru, India"}).eligible,false);
  assert.equal(evaluate("Remote - India",{location:"Mumbai"}).uncertain,true);
  assert.equal(evaluate("Remote",{includeUncertain:false}).eligible,false);
  assert.equal(evaluate("Indianapolis, United States").eligible,false);
  assert.equal(evaluate("London",{location:"India, UK"}).eligible,true);
});

test("zero-experience filter rejects required tenure across common posting formats", () => {
  for (const [description, minimum] of [
    ["Required experience: eight (8) years in software engineering", 8],
    ["<h3>Minimum qualifications</h3><ul><li>8+ yrs. exp. with SQL, Python, and cloud-native data engineering</li></ul>", 8],
    ["Experience required — 8–12 years", 8],
    ["Total years of experience: 8", 8],
    ["Experience: 2 years to 5 years", 2],
    ["Required Experience\n8 years", 8],
    ["2.5 years of full-time, professional (non-internship) engineering experience", 2.5],
    ["Experience building data pipelines: 6 mos.", 0.5],
  ]) {
    const role = posting("Data Engineer", description);
    assert.equal(role.minYears, minimum, description);
    assert.ok(role.experienceEvidence, description);
    assert.equal(matchJob(role, {years: 0}).eligible, false, description);
  }
  const withTitle = posting("Software Engineer (Exp-8--years)", "Preferred qualifications: Cloud");
  assert.equal(withTitle.minYears, 8);
  assert.equal(matchJob(withTitle, {years: 0}).eligible, false);
  assert.equal(posting("ASIC DFT Engineer || ATPG, MBIST || Synopsys tools || Exp 8+ years").minYears, 8);
  assert.equal(posting("Graduate Software Engineer", "No prior experience is required.").minYears, 0);
  assert.equal(posting("Software Engineer", "8 years of experience preferred.").minYears, null);
  assert.equal(posting("Software Engineer", "Our founders have 12 years of experience.").minYears, null);
  assert.equal(matchJob(posting("Graduate Software Engineer"), {years: 0}).uncertain, true);
});
test("rank strict matches first, surface near matches with evidence, respect personal constraints", () => {
  const pref = {...defaults, families:[families[3]],skills:["Python","PyTorch"]};
  const direct = matchJob(posting("Graduate ML Engineer","Python and PyTorch"),pref);
  const adjacent = matchJob(posting("Graduate Software Engineer","Python and PyTorch"),pref);
  assert.ok(direct.eligible && adjacent.eligible && direct.score > adjacent.score);
  assert.equal(adjacent.uncertain,true);
  assert.equal(matchJob(posting("Graduate Software Engineer","Java"),pref).eligible,false);
  assert.equal(matchJob(posting("Senior ML Engineer","1 year of experience in Python"),pref).eligible,false);
  assert.equal(matchJob(posting("ML Engineer","3 years of experience"),pref).eligible,false);
  assert.equal(matchJob(posting("ML Engineer"),pref).uncertain,true);
  assert.ok(matchJob(posting("Senior ML Engineer"),{...pref,years:null}).eligible);
  assert.equal(matchJob(posting("Graduate ML Engineer"),{...pref,workplace:"remote"}).eligible,false);
  assert.ok(matchJob(posting("Graduate ML Engineer","",{workplace:""}),{...pref,workplace:"remote"}).uncertain);
});

test("specific tools match direct evidence and equivalent spellings", () => {
  const stack = posting("Graduate Data Engineer","Our stack includes pandas, NumPy, SKLearn, PySpark, Postgres and NodeJS.");
  for (const label of ["Pandas","NumPy","scikit-learn","Spark","PySpark","SQL","PostgreSQL","Node.js"]) {
    assert.ok(stack.skills.includes(label),label);
  }
  const matched = matchJob(stack,{skills:["scikit learn","sklearn","Node JS","Postgres","pandas"]});
  assert.ok(matched.reasons.includes("Skills: scikit-learn, Node.js, PostgreSQL, Pandas"));
  assert.ok(skillSearchText(stack.skills).toLowerCase().includes("sklearn"));
  const generic = posting("Graduate Software Engineer","JavaScript, Spark, SQL, .NET and Python.");
  for (const label of ["Node.js","PySpark","PostgreSQL","Pandas","C#","Java"]) assert.ok(!generic.skills.includes(label),label);
  assert.deepEqual(matchJob(generic,{skills:["NodeJS","PySpark","Postgres","pandas"]}).reasons,
                   matchJob(generic,{skills:[]}).reasons);
  assert.ok(classifyJob("Software Engineer","Write C++/C#, and design APIs.").skills.includes("C++"));
});
test("level preferences reject explicit mismatches and allow review of undisclosed levels", () => {
  const graduate = posting("Graduate Software Engineer");
  const intern = posting("Software Engineering Intern");
  const noLevel = posting("Software Engineer","1 year of professional experience.");
  assert.ok(matchJob(graduate,{levels:[]}).eligible);
  assert.ok(matchJob(graduate,{levels:["entry","intern"]}).eligible);
  assert.equal(matchJob(intern,{levels:["entry"],years:null}).eligible,false);
  assert.equal(matchJob(noLevel,{levels:["mid"]}).uncertain,true);
  assert.equal(matchJob(noLevel,{levels:["mid"],includeUncertain:false}).eligible,false);
  assert.equal(matchJob(noLevel,{levels:[]}).uncertain,false);
});
