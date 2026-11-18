// Classify each public posting once. Personal preferences only affect the second pass.
const rules = [
  ["Software Engineering", /\b(?:software (?:engineer|develop|architect|designer)|swe|sde|sdet|programmer|full[ -]?stack|front[ -]?end|back[ -]?end|web develop|mobile (?:develop|engineer)|android (?:develop|engineer)|ios (?:develop|engineer)|applications? (?:engineer|develop)|systems? developer|api (?:engineer|develop)|member of (?:the )?technical staff|mts|(?:java|python|ruby|react|net|rust|golang|game|firmware) developer|developer experience|forward.deployed engineer|quant(?:itative)? develop)/i],
  ["Data Science & Analytics", /\b(?:data scien|data analy|business intelligence|bi (?:analyst|engineer|developer)|product analy|decision scien|applied scien|quant(?:itative)? (?:research|analyst)|statistician|analytics (?:engineer|scientist|analyst|consultant)|consultant\b.{0,45}\banalytics\b|business analytics)/i],
  ["Data Engineering", /\b(?:data (?:engineer|platform|architect|warehouse|infrastructure|pipeline|integration)|analytics engineer|etl (?:engineer|developer)|database (?:engineer|admin|develop|architect)|big data|db[at] engineer|dba\b)/i],
  ["AI & Machine Learning", /\b(?:ai|ml|nlp|llm|mlops|genai|aiops|machine learning|artificial intelligence|deep learning|computer vision|natural language processing|generative ai|applied scien(?:ce|tist)|research (?:engineer|scientist)|reinforcement learning|recommendation systems?)\b/i],
  ["Infrastructure & Cloud", /\b(?:dev[ -]?ops|devsecops|(?:site|systems?|integration|database|customer) reliability|sre|cloud (?:engineer|architect|infra|platform|ops)|platform (?:monitoring )?engineer|infra(?:structure)? engineer|systems? (?:admin|engineer)|network (?:(?:operations|deployment) )?(?:engineer|architect)|production engineer|build (?:engineer|and release)|release engineer|kubernetes|developer infrastructure)/i],
  ["Security", /\b(?:cyber[ -]?security|information security|(?:application|network|cloud|product|platform) security|security (?:engineer|research|analyst|architect|operations)|soc analyst|penetration test|threat (?:intel|research|hunt)|incident respon|devsecops)/i],
  ["Quality Engineering", /\b(?:sdet|software (?:test|quality)|test automation|qa (?:engineer|analyst|tester|automation)|quality assurance engineer|automation test|test development engineer)/i],
  ["Hardware & Embedded", /\b(?:embedded|firmware|fpga|asic|vlsi|rtl|silicon|soc verification|semiconductor|hardware (?:engineer|design|validation)|computer architect|robotics engineer)/i],
  ["Technical Operations", /\b(?:it (?:support|operations|administrator|engineer|automation)|help[ -]?desk|technical (?:support|services engineer)|systems? support|solutions? architect|technical solutions? engineer|application support|support engineer|data cent(?:er|re) technician)/i],
  ["Product & Design", /\b(?:(?:ux|ui)(?:\s*[\/&]\s*(?:ux|ui))? (?:design|research)|user experience|interaction design|product designer|technical (?:product|program) manager|product manager.{0,25}(?:data|platform|cloud|software|ai\b|technical))/i],
];
// Employers use "Dev Engineer" and "Development Engineer" interchangeably.
const normalizedRoleTitle = title => title.replace(/\bsoftware dev(?=\s+eng)/gi, "Software Development");

export const families = rules.map(([label]) => label);
export const defaults = {
  families: [...families], levels: [], location: "India", years: 1, skills: [], workplace: "", includeUncertain: true,
};

const spellings = {
  Python: [], SQL: ["T-SQL","structured query language"], Java: [], JavaScript:["ECMAScript","JS"],
  TypeScript:[], "Node.js":["NodeJS","Node JS"], "Next.js":["NextJS","Next JS"], "Vue.js":["VueJS","Vue JS"],
  "C++":["C plus plus","CPP"], "C#":["C sharp","CSharp"], ".NET":["dotnet","dot net"], Rust:[], Scala:[],
  Kotlin:[], React:["ReactJS","React.js"], Angular:[], Django:[], Flask:[], FastAPI:[], Spring:["Spring Boot"],
  Spark:["Apache Spark"], PySpark:["Py-Spark"], PostgreSQL:["Postgres"], MySQL:[], MongoDB:[], Redis:[],
  AWS:["Amazon Web Services"], Azure:["Microsoft Azure"], GCP:["Google Cloud","Google Cloud Platform"],
  Kubernetes:["K8s"], Docker:[], Linux:[], Terraform:[], Airflow:["Apache Airflow"], Kafka:["Apache Kafka"],
  PyTorch:[], TensorFlow:["Tensor Flow"], "Machine learning":["machine-learning","ML"], Pandas:[], NumPy:["Num Py"],
  "scikit-learn":["scikit learn","scikitlearn","sklearn"], SciPy:[], Jupyter:["JupyterLab"], Matplotlib:[],
  Keras:[], XGBoost:[], MLflow:[], "Hugging Face":["HuggingFace"], LangChain:[], NLP:["natural language processing"],
  LLM:["LLMs","large language model","large language models"], "Deep learning":["deep-learning"],
  Tableau:[], "Power BI":["PowerBI"], Snowflake:[], BigQuery:["Big Query"], Redshift:["Amazon Redshift"],
  dbt:["data build tool"], ETL:["extract transform load"], Databricks:[], "Delta Lake":[], Hadoop:["Apache Hadoop"],
  Elasticsearch:["Elastic Search"], GraphQL:[], gRPC:[], Figma:[], Cypress:[], Selenium:[],
};
const canonicalNames = new Map();
for (const [name,aliases] of Object.entries(spellings)) {
  for (const spelling of [name,...aliases]) canonicalNames.set(spelling.toLowerCase(),name);
}
// Longest aliases claim their span first (e.g. "Google Cloud Platform"). Boundaries also work for C++ and C#.
const escapeRegex = term => term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const allSkillTerms = [...canonicalNames.keys(),"golang"].sort((a,b)=>b.length-a.length).map(escapeRegex);
const skillPattern = new RegExp("(?<![a-z0-9_])(?:" + allSkillTerms.join("|") + ")(?![a-z0-9_])","gi");
canonicalNames.set("golang","Go");
canonicalNames.set("go","Go");
function canonicalSkill(value) {
  const key = String(value).trim().toLowerCase();
  return canonicalNames.get(key) ?? key;
}
export function skillSearchText(values = []) {
  return values.flatMap(value => [value,...(spellings[canonicalSkill(value)] ?? (value === "Go" ? ["Golang"] : []))]).join(" ");
}
const normal = value => String(value ?? "").toLowerCase().normalize("NFKD")
  .replace(/\p{Diacritic}/gu, "").replace(/[^a-z0-9+#]+/g, " ").trim();
const contains = (value, term) => Boolean(term) && (" " + value + " ").includes(" " + term + " ");

function plain(value) {
  return String(value ?? "").replace(/&lt;/gi, "<").replace(/&gt;/gi, ">")
    .replace(/<\/?(?:br|li|p|h\d|div|tr|td|th)\b[^>]*>/gi, "\n").replace(/<[^>]*>/g, " ")
    .replace(/&(?:nbsp|#160);/gi, " ").replace(/&amp;/gi, "&");
}

const numberWords = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty"];
const quantity = "(?:" + numberWords.join("|") + "|\\d{1,2}(?:\\.\\d+)?)";
const duration = new RegExp("\\b(" + quantity + ")(?:\\s*\\(\\s*\\d{1,2}\\s*\\))?\\s*\\+?\\s*(?:(?:[-–—−]|to)\\s*(" + quantity + ")\\s*\\+?\\s*)?(?:total\\s+)?(years?|yrs?|months?|mos?)\\b\\s*\\+?", "gi");
const preferredHeading = /^(?:preferred (?:qualifications|skills|experience|requirements)|nice.to.have|bonus (?:points|skills)|desirable (?:skills|qualifications)|what would be a plus)\b/i;
const requiredHeading = /^(?:required|minimum|basic|essential|mandatory|what you.ll (?:need|bring)|qualifications|requirements|what we.re looking for|your (?:skills|background|experience))\b/i;
const otherHeading = /^(?:responsibilities|about (?:us|the role|the team)|benefits|what we offer|equal opportunity|job description)\s*:?\s*$/i;
const experienceWord = /\b(?:experienc(?:e|ed)|exp|tenure)\b/i;
const degree = /\b(?:ph\.?\s?d|bachelor|master|bs|ba|ms|ma)\b/i;

function yearsRequired(description) {
  let section = "";
  const requirements = [];
  const clauses = description.replace(
    /^([ \t]*(?:(?:minimum|required|total|relevant|overall)\s+)?(?:years of )?experience[ \t]*:?)\s*\n\s*(?=\d|(?:zero|one|two|three|four|five|six|seven|eight|nine|ten)\b)/gim,
    "$1 ",
  ).split(/\n|[;•●]|(?<!\b(?:yr|yrs|exp|B|M|Ph|Sc|D|S|A)\.)(?<=[.!?])\s+/i);
  for (const raw of clauses) {
    const line = raw.trim().replace(/^[-–—*]+\s*/, "");
    if (!line) continue;
    if (preferredHeading.test(line)) section = "optional";
    else if (requiredHeading.test(line) && !/^required (?:experience|skills).*\bprefer/i.test(line)) section = "required";
    else if (otherHeading.test(line)) section = "";
    if (section === "optional" || /\b(?:our (?:team|company|founders?)|we have|we bring|founded|combined experience|in business|years ago)\b/i.test(line)) continue;
    const clause = line.split(/[,–—]\s*(?:preferably|ideally|a plus|nice to have)\b/i)[0];
    const educationAlternative = /\bor\b/i.test(clause) && degree.test(clause) && experienceWord.test(clause);
    const amounts = [];
    for (const match of clause.matchAll(duration)) {
      const before = clause.slice(0, match.index);
      const after = clause.slice(match.index + match[0].length).replace(/^\./, "");
      if (/\b(?:up to|at most|maximum(?: of)?|within|for the next|preferred|ideally)\s*[:=]?\s*$/i.test(before)) continue;
      if (/^\s*(?:of\s+)?(?:university|college|education|study|school|vesting|warranty|contract (?:term|duration))\b/i.test(after)) continue;
      if (/^\s*['’]?\s*(?:of\s+)?(?:[\w/+.-]+\s+){0,7}(?:is |are )?(?:preferred|a plus|nice to have|desirable|advantageous)\b/i.test(after) &&
          !/\b(?:at least|minimum|required|mandatory)\b/i.test(before)) continue;
      const relevant = experienceWord.test(before.slice(-115)) ||
        /^\s*['’]?\s*(?:of\s+)?(?:[\w/+(),-]+\s+){0,14}(?:experience|exp|developing|building|working|programming|designing)\b/i.test(after) ||
        /^\s*(?:in|as|with)\s+(?:an?\s+)?(?:technical|software|engineering|backend|frontend|data|systems|developer|cloud|security|AI|ML|[A-Z][A-Za-z+#.]*\b)/i.test(after);
      if (!relevant && !educationAlternative && !/^(?:minimum|required|mandatory)\b.*\bexperience\b/i.test(clause)) continue;
      const quantityText = match[1].toLowerCase();
      const count = /^\d/.test(quantityText) ? Number(quantityText) : numberWords.indexOf(quantityText);
      const years = count / (/^m/i.test(match[3]) ? 12 : 1);
      if (years <= 45) amounts.push(years);
    }
    const explicitZero = /\b(?:no (?:prior |professional |work )?experience (?:is )?(?:required|needed)|experience (?:is )?not required|without prior experience)\b/i.test(clause);
    if (explicitZero) amounts.push(0);
    const repeatedUnitRange = /\b(?:years?|yrs?|months?|mos?)\s*(?:to|[-–—])\s*\d/i.test(clause);
    const durationAlternative = amounts.length > 1 && (repeatedUnitRange || /\b(?:or|either)\b/i.test(clause))
      && !/\b(?:and|including|of which|with at least)\b/i.test(clause);
    const structured = clause.match(new RegExp("^\\s*(?:(?:overall|total|required|minimum|relevant)\\s+)*(?:years\\s+of\\s+experience|experience\\s+\\(\\s*years\\s*\\))\\s*[:=]\\s*(" + quantity + ")\\b", "i"));
    if (!amounts.length && structured) {
      const value = structured[1].toLowerCase();
      amounts.push(/^\d/.test(value) ? Number(value) : numberWords.indexOf(value));
    }
    if (amounts.length) {
      requirements.push({years:(educationAlternative || durationAlternative ? Math.min : Math.max)(...amounts),
        alternative:educationAlternative, evidence:clause.replace(/\s+/g, " ").slice(0, 280)});
    }
  }
  const strongest = requirements.reduce((best, item) => !best || item.years > best.years ? item : best, null);
  return {minYears:strongest?.years ?? null, experienceEvidence:strongest?.evidence ?? null,
    experienceConditional:requirements.some(r=>r.alternative)};
}

const nontechnical = /\b(?:account executive|sales representative|recruit(?:er|ing)|talent acquisition|marketing (?:manager|lead|director|specialist)|(?:sales|account|partner development|partnerships) manager|business development|sales development|sales (?:director|leader)|(?:director|head|vp|vice president) of (?:sales|strategic accounts)|growth sales|social media manager|content writer|brand designer|mechanical engineer|civil engineer|industrial engineer|sales operations|paralegal|counsel|attorney|accountant|communications manager|policy lead|business partner|finance (?:director|manager|senior manager))\b/i;
const genericEngineer = /^(?:(?:senior|sr\.?|junior|jr\.?|associate|graduate|staff|principal)\s+)*(?:engineer|developer|engineering intern|graduate engineer trainee|engineering manager|director of engineering|technology (?:analyst|lead)|technical (?:consultant|analyst))(?:\s+(?:[ivx]+|L?[1-6]))?$/i;
export function classifyJob(title, description = "") {
  const name = plain(title).trim();
  const roleTitle = normalizedRoleTitle(name);
  const primaryTitle = roleTitle.split(/[,(:]|\s+[-–—]\s+/)[0].trim();
  const body = plain(description);
  const text = name + "\n" + body;
  const evidence = new Set(Array.from(text.matchAll(skillPattern), hit => canonicalSkill(hit[0])));
  if (/\bGo (?:developer|engineer|programming|language)\b|\bGo(?=,\s*(?:Python|Java|Rust|C\+\+))/.test(text)) evidence.add("Go");
  if (evidence.has("PySpark")) evidence.add("Spark");
  if (evidence.has("PostgreSQL") || evidence.has("MySQL")) evidence.add("SQL");
  const detectedSkills = [...evidence];
  let roles = rules.filter(([, pattern]) => pattern.test(roleTitle)).map(([label]) => label);
  if (/\bresearch (?:engineer|scientist)\b/i.test(name) &&
      !/\b(?:comput(?:er|ing|ational)|models?|robotics|learning|software|nlp|llm|ai|ml|algorithms?|pytorch|tensorflow)\b/i.test(text)) {
    roles = roles.filter(role => role !== families[3]);
  }
  if (genericEngineer.test(primaryTitle) && !roles.length) {
    const software = /\b(?:build|write|develop|design)\w*\b.{0,65}\b(?:software|applications|distributed systems|services|apis)\b/i.test(body);
    if (software || detectedSkills.length >= 2) {
      roles = rules.filter(([, pattern]) => pattern.test(body.slice(0, 900))).map(([label]) => label);
      if (!roles.length && software) roles.push(families[0]);
    }
  }
  if (nontechnical.test(primaryTitle)) roles = [];
  // "AI" often describes the customer segment or business unit of a non-technical vacancy.
  if (roles.length === 1 && roles[0] === families[3] &&
      !/\b(?:engineer|scien\w*|develop\w*|research\w*|architect|programmer|analyst|intern|designer|technical|machine learning|model operations)\b/i.test(primaryTitle)) roles = [];
  let seniority = "unknown";
  const levelTitle = name.replace(/member of (?:the )?technical staff/ig, "").replace(duration, "");
  if (/\b(?:principal|director|architect|head of|staff|lead|engineering manager|distinguished|fellow)\b/i.test(levelTitle)) seniority = "lead";
  else if (/\b(?:senior|sr|iii|iv|[3-6])\b/i.test(levelTitle)) seniority = "senior";
  else if (/\b(?:intern|internship|apprentice|co.op)\b/i.test(levelTitle)) seniority = "intern";
  else if (/\b(?:junior|jr|graduate|new grad|entry.level|campus|associate|trainee|fresher|early career|i|1)\b/i.test(levelTitle)) seniority = "entry";
  else if (/\b(?:ii|2|mid.level|intermediate)\b/i.test(levelTitle)) seniority = "mid";
  const titleDuration = name.replace(/(\d+)[-–—]+(?=\s*(?:years|yrs)\b)/ig, "$1 ");
  let experience = yearsRequired(body);
  if (/\b(?:experience|exp)\b/i.test(name) || /\b\d{1,2}(?:\s*(?:[-–—]|to)\s*\d{1,2})?\s*\+?\s*(?:years?|yrs?)\b/i.test(titleDuration)) {
    const titleExperience = yearsRequired("Experience: " + titleDuration);
    if (titleExperience.minYears != null && (experience.minYears == null || titleExperience.minYears > experience.minYears)) {
      experience = {...titleExperience, experienceEvidence:name};
    }
  }
  return {families: roles, seniority, skills: detectedSkills, ...experience};
}

const places = {
  india: "india|bharat|bengaluru|bangalore|hyderabad|mumbai|pune|delhi|gurgaon|gurugram|noida|chennai|kolkata|ahmedabad|kochi|cochin|trivandrum|thiruvananthapuram|bhubaneswar|chandigarh|mohali|coimbatore|indore|jaipur|nagpur|mysuru|mysore|karnataka|maharashtra|telangana|tamil nadu|kerala|haryana|uttar pradesh|gujarat",
  usa: "usa|us|united states|united states of america|us only|new york|nyc|san francisco|seattle|boston|austin|california|texas|new jersey|chicago|atlanta|los angeles|san mateo|san jose|san diego|sunnyvale|mountain view|palo alto|redmond|bellevue|denver|phoenix|raleigh|atlanta|boulder|miami|pittsburgh|maryland|virginia|massachusetts|washington dc|washington d c|washington state|united states remote",
  uk: "uk|united kingdom|great britain|england|london|manchester|edinburgh",
  canada: "canada|toronto|vancouver|montreal|ontario|quebec", germany: "germany|berlin|munich|hamburg",
  france: "france|paris|lyon", australia: "australia|sydney|melbourne", singapore: "singapore",
  netherlands: "netherlands|amsterdam", ireland: "ireland|dublin", israel: "israel|tel aviv",
  china: "china|beijing|shanghai", japan: "japan|tokyo", uae: "uae|united arab emirates|dubai|abu dhabi",
  brazil: "brazil|sao paulo", poland: "poland|warsaw|krakow", spain: "spain|madrid|barcelona", romania:"romania|bucharest",
};
const countries = {
  india: ["india","bharat"], usa: ["usa","us","united states","united states of america"],
  uk: ["uk","united kingdom","great britain"], uae: ["uae","united arab emirates"],
};
const regions = {
  "north america": ["usa","canada","mexico"], latam:["brazil","mexico"], "latin america":["brazil","mexico"],
  americas:["usa","canada","mexico","brazil"], europe: ["uk","germany","france","netherlands","ireland","poland","spain","romania"],
  emea: ["uk","germany","france","netherlands","ireland","poland","spain","romania","uae","israel"],
  apac: ["india","singapore","australia","china","japan"], asia: ["india","singapore","china","japan","uae","israel"],
};
const aliases = {bangalore:"bengaluru",gurgaon:"gurugram",cochin:"kochi",mysore:"mysuru",trivandrum:"thiruvananthapuram"};
const countryTerms = new Map();
const regionNames = new Intl.DisplayNames(["en"], {type:"region", fallback:"none"});
for (let a = 65; a <= 90; a++) for (let b = 65; b <= 90; b++) {
  const code = String.fromCharCode(a,b);
  const display = regionNames.of(code);
  if (display && !["EU","QO","UN","ZZ"].includes(code)) countryTerms.set(normal(display), normal(display));
}
for (const [country, list] of Object.entries(places)) for (const alias of list.split("|")) countryTerms.set(alias,country);
const countryPattern = new RegExp("\\b(?:" + [...countryTerms.keys()].filter(Boolean).sort((a,b) => b.length-a.length).join("|") + ")\\b","g");
const namesAt = value => new Set(Array.from(value.matchAll(countryPattern), match => countryTerms.get(match[0])));
const locations = new Map();
function geo(value) {
  if (locations.has(value)) return locations.get(value);
  let normalized = normal(value).replace(/\bu s(?: a)?\b/g, "usa").replace(/\bu k\b/g,"uk");
  normalized = normalized.replace(/\b(?:bangalore|gurgaon|cochin|mysore|trivandrum)\b/g, key => aliases[key]);
  const parsed = {normalized, countries: namesAt(normalized)};
  if (locations.size > 12000) locations.clear();
  locations.set(value,parsed);
  return parsed;
}
const isCountry = (q, country) => (countries[country] ?? [country]).includes(q);
function locationQueries(input) {
  const result = [];
  for (const group of String(input ?? "").split(/[;|]/)) {
    const places = group.split(",").map(x=>x.trim()).filter(Boolean);
    for (let i=0;i<places.length;i++) {
      const here = geo(places[i]), next = places[i+1] && geo(places[i+1]);
      const context = next && [...next.countries].find(c => isCountry(next.normalized,c));
      if (context && ![...here.countries].some(c => isCountry(here.normalized,c)) &&
          (!here.countries.size || here.countries.has(context))) {
        result.push({target:places[i],country:context}); i++;
      } else result.push({target:places[i],country:null});
    }
  }
  return result;
}
function geography(target, source, country) {
  const actual = geo(source), wanted = geo(target);
  const q = wanted.normalized, s = actual.normalized;
  if (!q) return "any";
  if (country && actual.countries.size && !actual.countries.has(country)) return "no";
  const restriction = s.match(/\b(?:except|excluding|outside of|not available in)\s+(.+)/);
  if (restriction) {
    const excludesCountry = [...wanted.countries].some(c => (countries[c] ?? [c]).some(alias=>contains(restriction[1],alias)));
    if (contains(restriction[1],q) || excludesCountry) return "no";
  }
  const scope = restriction ? s.slice(0,restriction.index) : s;
  if (/\b(?:worldwide|anywhere in the world|globally remote|remote anywhere|global remote)\b/.test(scope) && !namesAt(scope).size) return "yes";
  if (contains(s,q)) return "yes";
  if ([...wanted.countries].some(c=>actual.countries.has(c))) {
    if ([...wanted.countries].some(c=>(countries[c] ?? [c]).includes(q))) return "yes";
    // A country-wide location doesn't establish a city. Two listed cities in the same country may differ.
    const onlyCountry = [...actual.countries].some(c=>(countries[c] ?? [c]).includes(s.replace(/\b(?:remote|hybrid|onsite)\b/g,"").trim()));
    if (onlyCountry || /\bremote\b/.test(s)) return "maybe";
    return "no";
  }
  if (wanted.countries.size && actual.countries.size) return "no";
  for (const [region, territories] of Object.entries(regions)) if (contains(s,region) && wanted.countries.size) {
    if ([...wanted.countries].some(country=>territories.includes(country))) return "maybe";
    if ([...wanted.countries].every(country=>Object.hasOwn(places,country))) return "no";
  }
  return "maybe";
}

const neighbors = [[0,2],[0,3],[0,4],[0,6],[0,7],[1,2],[1,3],[2,3],[2,4],[4,5],[4,8]];
const adjacent = new Map(families.map(name=>[name,new Set()]));
for (const [a,b] of neighbors) { adjacent.get(families[a]).add(families[b]); adjacent.get(families[b]).add(families[a]); }
const familySignals = [
  ["Java","TypeScript","JavaScript","Node.js","React","C++","Go","Rust","C#"], ["Tableau","Power BI","Pandas","scikit-learn","Machine learning"],
  ["Spark","Airflow","Kafka","dbt","Snowflake","BigQuery","Delta Lake"], ["PyTorch","TensorFlow","LLM","NLP","scikit-learn","Machine learning"],
  ["Kubernetes","Docker","Terraform","AWS","Azure","GCP"], ["Security"], ["Cypress","Selenium"],
  ["C++"], ["Linux"], ["Figma"],
];
function isAdjacent(job, selected) {
  return job.families.some(role => [...(adjacent.get(role) ?? [])].some(other =>
    selected.has(other) && familySignals[families.indexOf(other)].some(skill => job.skills?.includes(skill))));
}
const workplaceKey = value => normal(value).replace(/on site|in office|in person/g, "onsite");

export function matchJob(job, preferences = {}) {
  const pref = {...defaults, ...preferences};
  const discard = reason => ({eligible:false, score:0, reasons:[reason], uncertain:false});
  const reasons = [], questions = [];
  const roles = job.families ?? [];
  if (!roles.length) return discard("Outside the supported tech roles");
  if (pref.levels?.length) {
    if (!job.seniority || job.seniority === "unknown") questions.push("Seniority unlisted");
    else if (!pref.levels.includes(job.seniority)) return discard("Different seniority");
    else reasons.push("Seniority matches");
  }
  const selected = new Set(pref.families ?? []);
  const direct = roles.filter(role => selected.has(role));
  let score = 45;
  if (!selected.size) reasons.push(roles[0]);
  else if (direct.length) { score += 15; reasons.push(direct[0]); }
  else if (isAdjacent(job, selected)) {
    questions.push("Related role family"); score -= 20;
  } else return discard("Different role family");
  const matches = locationQueries(pref.location).map(({target,country})=>geography(target,job.location ?? "",country));
  if (matches.includes("yes")) { score += 14; reasons.push("Location matches"); }
  else if (matches.includes("maybe")) questions.push("Verify location eligibility");
  else if (matches.length) return discard("Outside your locations");
  const workplace = workplaceKey(pref.workplace), offered = workplaceKey(job.workplace);
  if (workplace && workplace !== "any") {
    if (!["remote","hybrid","onsite"].includes(offered)) questions.push("Work arrangement unlisted");
    else if (offered !== workplace) return discard("Different work arrangement");
    else { score += 5; reasons.push("Work arrangement matches"); }
  }
  if (typeof pref.years === "number" && Number.isFinite(pref.years)) {
    if (pref.years < 2 && ["senior","lead"].includes(job.seniority)) return discard("Explicit senior-level title");
    if (Number.isFinite(job.minYears)) {
      if (job.minYears > pref.years) return discard("Requires more experience");
      if (job.experienceConditional) questions.push("Verify the education and experience combination");
      else { score += 12; reasons.push("Experience requirement met"); }
    } else if (pref.years > 0 && ["intern","entry"].includes(job.seniority)) {
      score += 8; reasons.push("Early-career title");
    } else questions.push("Experience requirement unverified");
  }
  const detected = new Set((job.skills ?? []).map(canonicalSkill));
  const wantedSkills = [...new Set((pref.skills ?? []).map(canonicalSkill).filter(Boolean))];
  const skillHits = wantedSkills.filter(skill => detected.has(skill) || contains(normal(job.title),normal(skill)));
  if (skillHits.length) { score += Math.round(14 * skillHits.length / wantedSkills.length); reasons.push("Skills: " + skillHits.join(", ")); }
  const uncertain = questions.length > 0;
  return {eligible: !uncertain || !!pref.includeUncertain, score: Math.max(1,score - questions.length*5), reasons:[...reasons,...questions], uncertain};
}

export function matchCatalog(jobs, preferences, { archived = [], applied = [] } = {}, now = new Date()) {
  const hidden = new Set(archived.map(String));
  if (preferences.hideApplied) for (const id of applied) hidden.add(String(id));
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate());
  const earliest = preferences.maxAgeDays ? today - (preferences.maxAgeDays - 1) * 86400000 : -Infinity;
  const matches = [];
  for (const job of jobs) {
    if (hidden.has(String(job.id))) continue;
    const date = job.posted ? Date.parse(job.posted.slice(0, 10)) : NaN;
    if (Number.isFinite(date) ? date < earliest : preferences.includeUndated === false) continue;
    const match = matchJob(job, preferences);
    if (match.eligible) matches.push({ job, match });
  }
  return matches;
}
