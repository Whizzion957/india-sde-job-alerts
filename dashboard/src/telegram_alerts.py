"""Send new confirmed Role Atlas matches to one configured private Telegram chat."""

import hashlib
import html
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

from . import catalog


def config():
    path = catalog.DATA / "telegram.env"
    if not path.exists():
        return {}
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )


def profile(db, cfg):
    if cfg.get("USER_ID"):
        return db.execute(
            "SELECT id,preferences FROM users WHERE id=?", (cfg["USER_ID"],)
        ).fetchone()
    users = db.execute("SELECT id,preferences FROM users LIMIT 2").fetchall()
    return users[0] if len(users) == 1 else None


def batches(matches, *, zero_experience_only=False):
    title = "<b>Role Atlas · New strong matches"
    title += " · 0 years required</b>" if zero_experience_only else "</b>"
    text, entries = title, []
    for item in matches:
        job, match = item["job"], item["match"]
        name = html.escape(job["company"][:100] + " — " + job["title"][:220])
        location = html.escape(job["location"][:180])
        reasons = html.escape(" · ".join(match["reasons"])[:300])
        link = html.escape(job["url"], quote=True)
        row = f'\n\n<b>{name}</b>\n{location}\n{reasons}\n<a href="{link}">View posting</a>'
        if entries and (len(text) + len(row) > 3500 or len(entries) == 8):
            yield text, entries
            text, entries = title, []
        text += row
        entries.append(job)
    if entries:
        yield text, entries


def send(cfg, text):
    request = urllib.request.Request(
        "https://api.telegram.org/bot" + cfg["TOKEN"] + "/sendMessage",
        data=urllib.parse.urlencode(
            dict(
                chat_id=cfg["CHAT_ID"],
                text=text,
                parse_mode="HTML",
                disable_web_page_preview="true",
            )
        ).encode(),
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            if not json.load(response).get("ok"):
                raise RuntimeError("Telegram declined the message")
    except HTTPError as error:
        raise RuntimeError(f"Telegram HTTP {error.code}") from None
    except (URLError, OSError):
        raise RuntimeError("Telegram connection failed") from None


def deliver(*, preview=False, previous=None):
    cfg = config()
    if not cfg.get("TOKEN") or not cfg.get("CHAT_ID"):
        return previous, "Telegram chat setup is incomplete."
    zero_experience_only = cfg.get("ZERO_EXPERIENCE_ONLY") == "1"
    recipient = hashlib.sha256(cfg["CHAT_ID"].encode()).hexdigest()
    with catalog.connect() as db:
        user = profile(db, cfg)
        if not user:
            return previous, "Configure a single Role Atlas account for Telegram."
        uid = user["id"]
        db.execute("""CREATE TABLE IF NOT EXISTS telegram_sent(
                   user INTEGER, recipient TEXT, jobid TEXT, url TEXT,
                   PRIMARY KEY(user,recipient,jobid))""")
        archived = [
            r[0] for r in db.execute("SELECT jobid FROM archives WHERE user=?", (uid,))
        ]
        applied = [
            r[0]
            for r in db.execute("SELECT jobid FROM applications WHERE user=?", (uid,))
        ]
        revision = db.execute(
            "SELECT coalesce(sum(revision),0),count(*) FROM boards"
        ).fetchone()
        key = (
            recipient,
            uid,
            zero_experience_only,
            user["preferences"],
            tuple(archived),
            tuple(applied),
            tuple(revision),
            time.strftime("%Y-%m-%d"),
        )
        if key == previous:
            return key, None
        sent = db.execute(
            "SELECT jobid,url FROM telegram_sent WHERE user=? AND recipient=?",
            (uid, recipient),
        ).fetchall()
        ids = {r["jobid"] for r in sent}
        urls = {r["url"] for r in sent}
        jobs = [json.loads(r[0]) for r in db.execute("SELECT data FROM jobs")]
    result = subprocess.run(
        [
            os.environ.get("JOB_NODE", "node"),
            str(catalog.ROOT / "src/telegram_matches.mjs"),
        ],
        input=json.dumps(
            dict(
                jobs=jobs,
                preferences=json.loads(user["preferences"]),
                archived=archived,
                applied=applied,
                zeroExperienceOnly=zero_experience_only,
            )
        ),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=True,
        creationflags=catalog.HIDDEN_CHILD,
    )
    unsent = []
    for item in json.loads(result.stdout):
        job = item["job"]
        if job["id"] not in ids and job["url"] not in urls:
            unsent.append(item)
            urls.add(job["url"])
    if preview:
        return key, f"{len(unsent)} unsent strong matches."
    count = 0
    for text, entries in batches(unsent, zero_experience_only=zero_experience_only):
        send(cfg, text)
        with catalog.connect() as db:
            db.executemany(
                "INSERT OR IGNORE INTO telegram_sent VALUES(?,?,?,?)",
                [(uid, recipient, job["id"], job["url"]) for job in entries],
            )
        count += len(entries)
        time.sleep(1)
    return key, f"Telegram sent {count} strong matches."


def cycle():
    previous = None
    while True:
        try:
            previous, message = deliver(previous=previous)
            if (
                message
                and not message.startswith("Telegram chat setup")
                and message != "Telegram sent 0 strong matches."
            ):
                print(message, flush=True)
        except Exception as error:
            print(f"Telegram delivery will retry ({type(error).__name__})", flush=True)
        time.sleep(90)


if __name__ == "__main__":
    try:
        print(deliver(preview="--preview" in sys.argv)[1])
    except Exception as error:
        print(error if type(error) is RuntimeError else type(error).__name__)
        sys.exit(1)
