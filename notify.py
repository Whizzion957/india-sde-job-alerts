#!/usr/bin/env python3
"""Run the job scanner, keep only postings never sent before, append them to ALERTS.md
and push them to Telegram. Sends a message every run: new postings, a short "no new postings" note, or a failure warning."""
import datetime as dt, html, json, os, subprocess, sys, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "seen.json")
ALERTS = os.path.join(HERE, "ALERTS.md")
ENV = os.path.join(HERE, "telegram.env")
NAMES = {"gravitonresearchcapital": "Graviton", "towerresearchcapital": "Tower Research", "razorpaysoftwareprivatelimited": "Razorpay",
         "arcesiumllc": "Arcesium", "alphagrepsecurities": "AlphaGrep", "squarepointcapital": "Squarepoint", "harnessinc": "Harness",
         "observeai": "Observe.AI", "ms": "Morgan Stanley", "db": "Deutsche Bank", "jpmc": "JPMorgan", "hpe": "HPE",
         "thomsonreuters": "Thomson Reuters", "motorolasolutions": "Motorola Solutions", "analogdevices": "Analog Devices", "kla": "KLA", "atlassian": "Atlassian", "salesforce": "Salesforce", "adobe": "Adobe", "mongodb": "MongoDB", "gitlab": "GitLab", "paypal": "PayPal", "ebay": "eBay", "inmobi": "InMobi",
         "highradius": "HighRadius", "hackerrank": "HackerRank", "cred": "CRED", "nvidia": "NVIDIA", "hevodata": "Hevo Data"}

PAY = {"A": "≥ ₹24L", "B": "₹18–24L", "C": "likely < ₹18L", "U": "pay unknown"}

def name(co): return NAMES.get(co, co.capitalize())

def load_env():
    env = {}
    if os.path.exists(ENV):
        for line in open(ENV):
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1); env[k] = v
    return env

def tg(method, token, **params):
    data = urllib.parse.urlencode(params).encode() if params else None
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/{method}", data=data, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram {method} failed: {e.code} {e.read().decode('utf-8', 'replace')[:300]}") from None

def chat_id(env):
    if env.get("CHAT_ID"): return env["CHAT_ID"]
    ups = tg("getUpdates", env["TOKEN"]).get("result", [])
    ids = [u["message"]["chat"]["id"] for u in ups if "message" in u]
    if not ids: raise SystemExit("No chat found: send any message to the bot in Telegram first.")
    env["CHAT_ID"] = str(ids[-1])
    with open(ENV, "w") as f: f.write("".join(f"{k}={v}\n" for k, v in env.items()))
    os.chmod(ENV, 0o600)
    return env["CHAT_ID"]

def send(text):
    env = load_env()
    if not env.get("TOKEN"): print("telegram: no TOKEN in telegram.env, skipped"); return False
    cid = chat_id(env)
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) > 3500: chunks.append(cur); cur = ""
        cur += line + "\n"
    chunks.append(cur)
    for c in chunks:
        tg("sendMessage", env["TOKEN"], chat_id=cid, text=c, parse_mode="HTML", disable_web_page_preview="true")
    return True

def main():
    if sys.argv[1:] == ["--test"]:
        send("✅ Job alerts are connected. You'll get a message here whenever new India entry-level SDE postings appear (checked daily, 9 PM IST)."); return
    preview = "--preview" in sys.argv
    p = subprocess.run([sys.executable, "-I", os.path.join(HERE, "alert_scan.py"), "30" if preview else "7", "--json"], capture_output=True, text=True, timeout=1500)
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    try: data = json.loads(p.stdout.strip().splitlines()[-1])
    except Exception: data = {"failed": True, "ok_fetches": 0, "results": [], "errors": [p.stderr[-300:]]}
    if data.get("failed"):
        msg = f"⚠️ Job scan failed on {today}: only {data.get('ok_fetches', 0)} job-board requests succeeded. Will retry next run."
        print(msg); send(msg); return 2
    seen = set(json.load(open(SEEN))) if os.path.exists(SEEN) else set()
    new = [r for r in data["results"] if preview or r["url"] not in seen]
    print(f"{len(data['results'])} in window, {len(new)} new")
    if not new:
        n = len(data["results"])
        send(f"✅ Daily scan done ({today}): no new postings. {n} still-open posting{'s' if n != 1 else ''} already sent earlier.")
        return 0
    new.sort(key=lambda r: ("ABUC".index(r["tier"]), r["co"], r["title"]))
    # Telegram
    title = (f"👀 Preview: {len(new)} open India SDE posting{'s' if len(new) > 1 else ''} from the last 30 days (includes ones already sent)"
             if preview else f"🆕 {len(new)} new India SDE posting{'s' if len(new) > 1 else ''} — {today}")
    lines = [f"<b>{title}</b>", ""]
    for r in new:
        pay = PAY[r["tier"]] + (" est." if r["tier"] != "U" else "")
        exp = f"{r['yrs']} yr exp" if r["yrs"] is not None else "exp not stated"
        lines.append(f"• <b>{html.escape(name(r['co']))}</b> — {html.escape(r['title'])}\n   {html.escape(r['loc'])} · {exp} · {html.escape(pay)}\n"
                     f"   <a href=\"{html.escape(r['url'])}\">Apply</a>")
    if not send("\n".join(lines)):
        print("not sent; will retry next run"); return 1
    if preview: print("preview sent; nothing recorded"); return 0
    # ALERTS.md (newest first)
    rows = "\n".join(f"| {name(r['co'])} | {r['title']}{(' (' + r['note'] + ')') if r.get('note') else ''} | {r['loc']} | "
                     f"{str(r['yrs']) + ' yr' if r['yrs'] is not None else 'not stated'} | {PAY[r['tier']]} | "
                     f"{r['posted']} | [apply]({r['url']}) |" for r in new)
    section = (f"## {today} — {len(new)} new\n\n| Company | Role | Location | Min exp | Pay tier | Posted | Link |\n"
               f"|---|---|---|---|---|---|---|\n{rows}\n\n")
    old = open(ALERTS).read() if os.path.exists(ALERTS) else "# Job alerts — India entry-level SDE\n\n"
    head, _, rest = old.partition("\n\n")
    open(ALERTS, "w").write(head + "\n\n" + section + rest)
    json.dump(sorted(seen | {r["url"] for r in new}), open(SEEN, "w"), indent=0)
    return 0

if __name__ == "__main__":
    sys.exit(main() or 0)
