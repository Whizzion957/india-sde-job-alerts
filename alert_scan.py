#!/usr/bin/env python3
"""India entry-level SDE job alert scanner.
Reports postings published in the last WINDOW_DAYS days on official job-board APIs,
excluding roles already applied to. Prints a markdown report to stdout."""
import json, re, html, sys, time, datetime as dt, urllib.request, concurrent.futures as cf

WINDOW_DAYS = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 3.5
NOW = dt.datetime.now(dt.timezone.utc)
CUTOFF = NOW - dt.timedelta(days=WINDOW_DAYS)

# Roles already applied to (posting IDs found in URLs) -- never report these.
# One ID per line in applied.txt (git-ignored, personal); '#' starts a comment.
_APPLIED_FILE = __import__("os").path.join(__import__("os").path.dirname(__import__("os").path.abspath(__file__)), "applied.txt")
APPLIED = set()
try:
    APPLIED = {l.split("#")[0].strip() for l in open(_APPLIED_FILE)} - {""}
except FileNotFoundError:
    pass
# Google India early-career postings already seen on 2026-10-21 (Google list pages carry no dates).
KNOWN_GOOGLE = {"104556982945358534", "115719346323366598", "122710813273137862", "123868492716745414", "125086141714965190",
                "130475891879748294", "137635533642703558", "138674961899233990", "73379279982731974", "75076499224306374",
                "77695403851424454", "83262703669256902", "96710280632771270"}

# Estimated fresher base-pay tier in India (approximate, from public offer reports):
# A = >= 24 LPA, B = 18-24 LPA, C = likely below 18 LPA. Companies not listed = U (unknown).
TIER = {}
for t, cos in {"A": """rubrik gravitonresearchcapital towerresearchcapital alphagrepsecurities squarepointcapital databricks stripe coinbase
cloudflare datadog mongodb elastic okta gitlab airbnb dropbox pinterest samsara twilio snowflake atlassian uber google nvidia cohesity
sprinklr netskope fivetran cred meesho groww sarvam salesforce workday""",
               "B": """microsoft amazon adobe paypal autodesk ebay oracle cisco broadcom cadence mastercard visa ms marvell kla zscaler
druva harnessinc arcesiumllc razorpaysoftwareprivatelimited zeta tekion hevodata apple""",
               "C": """accenture citi db barclays blackrock intel micron hpe thomsonreuters target nasdaq motorolasolutions analogdevices
jpmc paytm mindtickle highradius sigmoid"""}.items():
    for c in cos.split(): TIER[c] = t
# Companies the user never wants suggested.
EXCLUDE = {"cisco", "tcs", "wipro"}

GH = """gravitonresearchcapital towerresearchcapital alphagrepsecurities squarepointcapital rubrik databricks stripe coinbase cloudflare
datadog mongodb elastic okta gitlab airbnb dropbox pinterest samsara twilio netskope zscaler fivetran yugabyte arcesiumllc groww
razorpaysoftwareprivatelimited slice glance inmobi clear druva harnessinc highradius hackerrank sigmoid observeai""".split()
LEVER = "cred meesho zeta paytm mindtickle hevodata".split()
ASHBY = "snowflake tekion navi atlan spotdraft composio sarvam mintlify".split()
WORKDAY = [("salesforce", "wd12", "External_Career_Site"), ("adobe", "wd5", "external_experienced"),
           ("nvidia", "wd5", "NVIDIAExternalCareerSite"), ("sprinklr", "wd1", "careers"), ("cohesity", "wd5", "Cohesity_Careers"),
           ("workday", "wd5", "Workday"), ("paypal", "wd1", "jobs"), ("autodesk", "wd1", "Ext"), ("ebay", "wd5", "apply"),
           ("accenture", "wd103", "AccentureCareers"), ("broadcom", "wd1", "External_Career"),
           ("visa", "wd5", "Visa"), ("mastercard", "wd1", "CorporateCareers"), ("ms", "wd5", "External"), ("citi", "wd5", "2"),
           ("db", "wd3", "DBWebSite"), ("barclays", "wd3", "External_Career_Site_Barclays"), ("blackrock", "wd1", "BlackRock_Professional"),
           ("intel", "wd1", "External"), ("micron", "wd1", "External"), ("marvell", "wd1", "MarvellCareers"), ("kla", "wd1", "Search"),
           ("cadence", "wd1", "External_Careers"), ("hpe", "wd5", "Jobsathpe"), ("thomsonreuters", "wd5", "External_Career_Site"),
           ("target", "wd5", "targetcareers"), ("nasdaq", "wd1", "Global_External_Site"), ("motorolasolutions", "wd5", "Careers"),
           ("analogdevices", "wd1", "External")]

INDIA = re.compile(r"\bindia\b|\bIND\b|bengal|bangalore|hyderabad|pune|gurugram|gurgaon|noida|mumbai|chennai|delhi", re.I)
SW = re.compile(r"software|sde|swe|developer|development|engineer|member of technical staff|\bmts\b|programmer|quant", re.I)
BAD = re.compile(r"senior|sr\.?\b|staff|lead|principal|manager|director|head|architect|\b(ii|iii|iv|2|3|4|5)\b|vp\b|sales|support|"
                 r"solution|customer|field|recruit|hardware|fpga|verification|analog|mechanical|layout|silicon|asic|rtl|validation|"
                 r"test|qa\b|sdet|security|network|data center|devops|site reliability|escalation|designer|technician|quality|"
                 r"manufactur|equipment|process engineer|automation engineer", re.I)
OK_FETCHES = [0]
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Chrome/126", "Accept": "application/json"}

def fetch(url, data=None, raw=False, extra=None):
    h = dict(UA); h.update(extra or {})
    if data is not None: h["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode() if data is not None else None, headers=h)
            with urllib.request.urlopen(req, timeout=45) as r:
                b = r.read().decode("utf-8", "replace")
                out = b if raw else json.loads(b)
                OK_FETCHES[0] += 1
                return out
        except Exception:
            time.sleep(3 * (attempt + 1))
    return None

def text(s): return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(s or ""))))

def parse_date(s):
    if s is None or s == "": return None
    if isinstance(s, (int, float)) or (isinstance(s, str) and s.isdigit()):
        v = int(s); v = v / 1000 if v > 1e11 else v
        return dt.datetime.fromtimestamp(v, dt.timezone.utc)
    try: return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except Exception: pass
    try: return dt.datetime.strptime(str(s)[:10], "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    except Exception: return None

def years(body):
    m = re.search(r"bachelor[^.;]{0,80}?(\d+)\s*\+?\s*(?:-|–|to)?\s*(?:\d+)?\s*\+?\s*years?", body, re.I)
    if m and int(m.group(1)) < 20: return int(m.group(1))   # the bachelor's-degree requirement is the one that applies
    ys = [int(a) for a, _ in re.findall(r"(\d+)\s*\+?\s*(?:-|–|to)?\s*(\d+)?\s*\+?\s*years?", body, re.I) if int(a) < 20]
    return min(ys) if ys else None

def keep(co, title, loc, url, body, posted):
    if co in EXCLUDE: return None
    if any(a in url for a in APPLIED): return None
    if not INDIA.search(loc or "") or not SW.search(title) or BAD.search(title): return None
    if posted is None or posted < CUTOFF: return None
    y = years(body)
    grad = sorted(set(re.findall(r"(?:graduat\w*|batch|class of)[^.]{0,60}?(20(?:26|27))", body, re.I)))
    entryish = re.search(r"graduate|grad\b|2027|university|campus|fresher|entry|early|associate|\bI\b|\b1\b", title, re.I)
    if y is not None and y > 1: return None
    if y is None and not entryish and not grad: return None
    return dict(co=co, title=title, loc=loc.strip()[:60], url=url, yrs=y, grad=grad,
                posted=posted.date().isoformat(), tier=TIER.get(co, "U"))

def greenhouse(t):
    d = fetch(f"https://boards-api.greenhouse.io/v1/boards/{t}/jobs?content=true") or {}
    out = []
    for j in d.get("jobs", []):
        posted = parse_date(j.get("first_published") or j.get("updated_at"))
        out.append(keep(t, j["title"], (j.get("location") or {}).get("name", ""), j["absolute_url"], text(j.get("content")), posted))
    return out

def lever(t):
    out = []
    for j in fetch(f"https://api.lever.co/v0/postings/{t}?mode=json") or []:
        body = j.get("descriptionPlain", "") + " " + " ".join(text(l.get("content", "")) for l in j.get("lists", []))
        loc = (j.get("categories", {}).get("location") or "") + " " + " ".join(j.get("categories", {}).get("allLocations") or [])
        out.append(keep(t, j["text"], loc, j["hostedUrl"], body, parse_date(j.get("createdAt"))))
    return out

def ashby(t):
    d = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{t}") or {}
    out = []
    for j in d.get("jobs", []):
        loc = (j.get("location") or "") + " " + " ".join(x.get("location", "") for x in j.get("secondaryLocations") or [])
        out.append(keep(t, j["title"], loc, j["jobUrl"], text(j.get("descriptionPlain")), parse_date(j.get("publishedAt"))))
    return out

def workday(args):
    ten, wd, site = args
    base = f"https://{ten}.{wd}.myworkdayjobs.com/wday/cxs/{ten}/{site}"
    seen = {}
    for q in ["software engineer", "graduate", "university", "associate software", "member of technical staff", "application developer"]:
        for off in range(0, 100, 20):
            d = fetch(base + "/jobs", {"appliedFacets": {}, "limit": 20, "offset": off, "searchText": q})
            if not d or not d.get("jobPostings"): break
            for j in d["jobPostings"]:
                if j.get("externalPath"): seen[j["externalPath"]] = j
    out = []
    for p, j in seen.items():
        title = j.get("title", "")
        if not SW.search(title) or BAD.search(title): continue
        posted_txt = (j.get("postedOn") or "").lower()
        m = re.search(r"(\d+)\+? days? ago", posted_txt)
        days = 0 if "today" in posted_txt else 1 if "yesterday" in posted_txt else int(m.group(1)) if m else 99
        if "30+" in posted_txt or days > WINDOW_DAYS + 1: continue
        info = (fetch(base + p) or {}).get("jobPostingInfo", {})
        loc = " ".join([info.get("location", "") or j.get("locationsText", "")] + list(info.get("additionalLocations") or []))
        url = info.get("externalUrl") or f"https://{ten}.{wd}.myworkdayjobs.com/{site}{p}"
        out.append(keep(ten, title, loc, url, text(info.get("jobDescription")), parse_date(info.get("startDate")) or NOW - dt.timedelta(days=days)))
    return out

def microsoft():
    out, seen = [], {}
    for q in ["software engineer", "university graduate", "new grad"]:
        for start in range(0, 50, 10):
            d = fetch(f"https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query={q.replace(' ', '%20')}&location=India&start={start}&sort_by=timestamp")
            pos = (d or {}).get("data", {}).get("positions", [])
            for p in pos: seen[p["id"]] = p
            if len(pos) < 10: break
            time.sleep(2)
    for p in seen.values():
        posted = parse_date(p.get("postedTs"))
        if not SW.search(p["name"]) or BAD.search(p["name"]) or posted is None or posted < CUTOFF: continue
        det = (fetch(f"https://apply.careers.microsoft.com/api/pcsx/position_details?position_id={p['id']}&domain=microsoft.com&hl=en") or {}).get("data", {})
        body = text(det.get("jobDescription"))
        r = keep("microsoft", p["name"], " ".join(p.get("locations") or []), f"https://apply.careers.microsoft.com/careers/job/{p['id']}", body, posted)
        if r: r["note"] = "Microsoft L59 base ~14-22L (total higher)"
        out.append(r); time.sleep(2)
    return out

def amazon():
    out, seen = [], {}
    for q in ["software development engineer", "SDE", "university"]:
        for off in range(0, 500, 100):
            d = fetch(f"https://www.amazon.jobs/en/search.json?offset={off}&result_limit=100&sort=recent&country=IND&base_query={q.replace(' ', '%20')}")
            jobs = (d or {}).get("jobs", [])
            for j in jobs: seen[j["id_icims"]] = j
            if len(jobs) < 100: break
    for j in seen.values():
        try: posted = dt.datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").replace(tzinfo=dt.timezone.utc)
        except ValueError: posted = None
        body = text(j.get("basic_qualifications")) + " " + text(j.get("description"))
        if re.search(r"\bFTC\b|contract|temporary", j["title"], re.I): continue
        newgrad = re.search(r"university|graduate|new grad|campus|2027|intern", j["title"] + " " + (j.get("job_category") or ""), re.I)
        bq = text(j.get("basic_qualifications"))
        if not newgrad and (re.search(r"non-internship", bq, re.I) or (years(bq) or 0) >= 1): continue
        loc = (j.get("normalized_location") or "") + " India" if j.get("country_code") == "IND" else ""
        r = keep("amazon", j["title"], loc, "https://www.amazon.jobs" + j["job_path"], body, posted)
        if r: r["note"] = "Amazon SDE-1 base ~19-22L (total higher)"
        out.append(r)
    return out

def atlassian():
    out = []
    for j in fetch("https://www.atlassian.com/endpoint/careers/listings") or []:
        pj = j.get("portalJobPost") or {}
        try: posted = dt.datetime.strptime(pj.get("updatedDate", ""), "%Y-%m-%d %I:%M %p").replace(tzinfo=dt.timezone.utc)
        except ValueError: posted = None
        body = text(j.get("qualifications")) + " " + text(j.get("overview"))
        out.append(keep("atlassian", j.get("title", ""), " ".join(j.get("locations") or []), pj.get("portalUrl") or j.get("applyUrl", ""),
                        body, posted))
    return out

def apple():
    # jobs.apple.com search pages embed their results as router hydration JSON (newest first); details come from a JSON API.
    out, seen = [], {}
    for page in range(1, 15):
        b = fetch(f"https://jobs.apple.com/en-in/search?location=india-INDC&sort=newest&page={page}", raw=True) or ""
        m = re.search(r'__staticRouterHydrationData = JSON\.parse\(("(?:[^"\\]|\\.)*")\)', b)
        if not m: break
        rows = json.loads(json.loads(m.group(1))).get("loaderData", {}).get("search", {}).get("searchResults") or []
        for r in rows: seen.setdefault(r["positionId"], r)
        if not rows or parse_date(rows[-1].get("postDateInGMT")) < CUTOFF: break
    for r in seen.values():
        title, posted = r.get("postingTitle", "").strip(), parse_date(r.get("postDateInGMT"))
        if not SW.search(title) or BAD.search(title) or posted is None or posted < CUTOFF: continue
        det = (fetch(f"https://jobs.apple.com/api/v1/jobDetails/{r['positionId']}") or {}).get("res", {})
        body = text(" ".join(str(det.get(k) or "") for k in ("minimumQualifications", "preferredQualifications", "description")))
        loc = ", ".join(l.get("name", "") for l in r.get("locations") or []) + " India"
        x = keep("apple", title, loc, f"https://jobs.apple.com/en-in/details/{r['positionId']}/{r.get('transformedPostingTitle', '')}", body, posted)
        if x: x["note"] = "Apple ICT2 base est. ~20-28L"
        out.append(x)
    return out

def google():
    b = fetch("https://www.google.com/about/careers/applications/jobs/results?location=India&target_level=EARLY&q=software%20engineer", raw=True) or ""
    out = []
    for gid, slug in sorted(set(re.findall(r"jobs/results/(\d+)-([a-z0-9\-%]+)", b))):
        if gid in APPLIED or gid in KNOWN_GOOGLE or not re.search(r"software-engineer|software-developer", slug) \
                or re.search(r"senior|staff|principal|manager|lead|silicon|kernel|firmware", slug): continue
        out.append(dict(co="google", title=slug.replace("-", " "), loc="India", posted="undated", tier="A", yrs=None, grad=[],
                        url=f"https://www.google.com/about/careers/applications/jobs/results/{gid}-{slug}", gid=gid))
    return out

def oracle_hcm(args):
    host, site, co, link = args
    base = f"https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    out, seen = [], {}
    for kw in ["Software Engineer", "Software Developer", "Graduate", "University", "Associate"]:
        for off in range(0, 200, 25):
            d = fetch(f"{base}?onlyData=true&expand=requisitionList.secondaryLocations&finder=findReqs;siteNumber={site},keyword=%22{kw.replace(' ', '%20')}%22,limit=25,offset={off},sortBy=POSTING_DATES_DESC")
            reqs = ((d or {}).get("items") or [{}])[0].get("requisitionList", [])
            for r in reqs: seen[r["Id"]] = r
            if len(reqs) < 25: break
    for r in seen.values():
        locs = [r.get("PrimaryLocation") or ""] + [x.get("Name", "") for x in r.get("secondaryLocations") or []]
        out.append(keep(co, r["Title"], "; ".join(l for l in locs if l), link.format(id=r["Id"]),
                        r.get("ShortDescriptionStr") or "", parse_date(r.get("PostedDate"))))
    return out

ORACLE_HCM = [("iaziqy.fa.ocs.oraclecloud.com", "CX_1", "uber", "https://jobs.uber.com/en/jobs/{id}"),
              ("jpmc.fa.oraclecloud.com", "CX_1001", "jpmc", "https://jpmc.fa.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/job/{id}"),
              ("eeho.fa.us2.oraclecloud.com", "CX_45001", "oracle", "https://careers.oracle.com/jobs/#en/sites/jobsearch/job/{id}")]

tasks = ([(greenhouse, t) for t in GH] + [(lever, t) for t in LEVER] + [(ashby, t) for t in ASHBY] + [(workday, t) for t in WORKDAY]
         + [(oracle_hcm, t) for t in ORACLE_HCM])
results, errors = [], []
with cf.ThreadPoolExecutor(12) as ex:
    futs = {ex.submit(f, a): (f.__name__, a) for f, a in tasks}
    futs.update({ex.submit(f): (f.__name__, "") for f in (microsoft, google, amazon, atlassian, apple)})
    for fu in cf.as_completed(futs):
        try: results += [r for r in fu.result() if r]
        except Exception as e: errors.append(f"{futs[fu]}: {e}")

if OK_FETCHES[0] < 10:
    if "--json" in sys.argv:
        print(json.dumps({"ok_fetches": OK_FETCHES[0], "results": [], "errors": errors, "failed": True}))
        sys.exit(2)
    print(f"SCAN FAILED: only {OK_FETCHES[0]} job-board requests succeeded (network blocked or APIs down). Do not treat this as 'no new postings'.")
    sys.exit(2)
results.sort(key=lambda r: ("ABUC".index(r["tier"]), r["co"], r["title"]))
if "--json" in sys.argv:
    print(json.dumps({"ok_fetches": OK_FETCHES[0], "results": results, "errors": errors}))
    sys.exit(0)
print(f"# India entry-level SDE alerts — {NOW:%Y-%m-%d} (postings since {CUTOFF:%Y-%m-%d})\n")
if not results: print("No new matching postings this run.")
for tier, label in (("A", "Est. ≥ ₹24L fixed"), ("B", "Est. ₹18–24L fixed"), ("U", "Pay unknown"), ("C", "Est. below ₹18L fixed")):
    rows = [r for r in results if r["tier"] == tier]
    if not rows: continue
    print(f"\n## {label}\n\n| Company | Role | Location | Exp (min yrs) | Grad yr | Posted | Link |\n|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['co']} | {r['title']} | {r['loc']} | {r['yrs'] if r['yrs'] is not None else '-'} | {','.join(r['grad']) or '-'} | {r['posted']} | [apply]({r['url']}) |" + (f" {r['note']}" if r.get("note") else ""))
if errors: print("\nSource errors:", "; ".join(errors))
