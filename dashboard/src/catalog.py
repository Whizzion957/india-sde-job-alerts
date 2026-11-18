"""Shared, resumable public-board scanner. A source is replaced only after a complete fetch."""

import concurrent.futures
from contextlib import contextmanager
import datetime as dt
import hashlib
import gzip
import html
import json
import os
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
from email.utils import parsedate_to_datetime
from . import enterprise

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("JOB_DASHBOARD_STATE", ROOT / ".state")).resolve()
AGE = 6 * 3600
WRITE_LOCK = threading.Lock()
HIDDEN_CHILD = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SCAN_STATUS_LOCK = threading.Lock()
active_scan = None


class PartialBoard(Exception):
    def __init__(self, jobs, cause):
        super().__init__(str(cause))
        self.jobs = jobs
        self.cause = cause


@contextmanager
def connect():
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "jobs.sqlite", timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def init():
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS boards (
            key TEXT PRIMARY KEY, company TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
            checked TEXT, good TEXT, next_check REAL DEFAULT 0, etag TEXT, modified TEXT,
            count INTEGER DEFAULT 0, revision INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, board TEXT NOT NULL, data TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS jobs_board ON jobs(board);
        CREATE TABLE IF NOT EXISTS classified (id TEXT PRIMARY KEY, board TEXT NOT NULL, fingerprint BLOB NOT NULL);
        CREATE INDEX IF NOT EXISTS classified_board ON classified(board);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        """)
        boards = registry()
        configured = {key(board) for board in boards}
        retired = [
            (row["key"],)
            for row in db.execute("SELECT key FROM boards")
            if row["key"] not in configured
        ]
        db.executemany("DELETE FROM jobs WHERE board=?", retired)
        db.executemany("DELETE FROM classified WHERE board=?", retired)
        db.executemany("DELETE FROM boards WHERE key=?", retired)
        for b in boards:
            db.execute(
                "INSERT INTO boards(key,company,status) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET company=excluded.company",
                (
                    key(b),
                    b["company"],
                    "manual" if b["provider"] == "link" else "pending",
                ),
            )


def registry():
    return [
        board
        for filename in ("enterprise_boards.json", "boards.json")
        for board in json.loads(
            (ROOT / "src" / filename).read_text(encoding="utf-8-sig")
        )
    ]


def key(b):
    return b["provider"] + ":" + b["slug"]


def clean(value):
    return re.sub(
        r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(value or "")))
    ).strip()


def locations(parts):
    return " · ".join(
        dict.fromkeys(str(p).strip() for p in parts if p and str(p).strip())
    )


def iso(value):
    if isinstance(value, (float, int)):
        return (
            dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()
        )
    return (
        value[:10]
        if isinstance(value, str) and re.match(r"^\d{4}-\d{2}-\d{2}", value)
        else None
    )


def normalized(b, r):
    provider = b["provider"]
    if provider == "greenhouse":
        title, url, body = r["title"], r["absolute_url"], r.get("content", "")
        primary = (r.get("location") or {}).get("name", "")
        metadata = {
            str(m.get("name", "")).lower(): m.get("value")
            for m in r.get("metadata") or []
        }
        extra = metadata.get("job posting location") or []
        loc = locations(
            [primary]
            + [o.get("location") or o.get("name") for o in r.get("offices") or []]
            + (extra if isinstance(extra, list) else [extra])
        )
        date = r.get("first_published") or r.get("first_published_at")
        model = str(metadata.get("working model eligibility") or primary).lower()
        if "hybrid" in model:
            workplace = "hybrid"
        elif re.search(r"\bremote\b", model):
            workplace = "remote"
        elif re.search(r"\bon[ -]?site\b|in[ -]office", model):
            workplace = "onsite"
        else:
            workplace = ""
    elif provider == "ashby":
        if r.get("isListed") is False:
            return None
        title, url, body = (
            r["title"],
            r["jobUrl"],
            r.get("descriptionPlain") or r.get("descriptionHtml"),
        )
        loc = locations(
            [
                r.get("location"),
                ((r.get("address") or {}).get("postalAddress") or {}).get(
                    "addressCountry"
                ),
            ]
            + [x.get("location") for x in r.get("secondaryLocations") or []]
        )
        date, workplace = (
            r.get("publishedAt"),
            r.get("workplaceType") or ("remote" if r.get("isRemote") else ""),
        )
    else:
        title, url = r["text"], r["hostedUrl"]
        body = " ".join(
            [r.get("descriptionPlain") or r.get("description") or ""]
            + [
                (x.get("text") or "") + " " + (x.get("content") or "")
                for x in r.get("lists") or []
            ]
        )
        cat = r.get("categories") or {}
        loc = locations([cat.get("location")] + (cat.get("allLocations") or []))
        date, workplace = r.get("createdAt"), r.get("workplaceType") or ""
    if (
        not title.strip()
        or urlsplit(url).scheme != "https"
        or not urlsplit(url).hostname
    ):
        return None
    source_id = str(r.get("id") or url)
    return dict(
        id=key(b) + ":" + source_id,
        company=b["company"],
        title=clean(title),
        location=clean(loc),
        url=url,
        posted=iso(date),
        description=html.unescape(body or ""),
        workplace=workplace.lower().replace("-", ""),
    )


def retry_delay(error, fallback):
    if not isinstance(error, HTTPError):
        return fallback
    retry = error.headers.get("Retry-After", "")
    try:
        return (
            float(retry)
            if retry.isdigit()
            else max(0, parsedate_to_datetime(retry).timestamp() - time.time())
        )
    except (ValueError, TypeError, OverflowError):
        return fallback


def fetch_page(url, validators, *, raw=False, body=None):
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "OpportunityDashboard/1.0 (public careers catalog)",
        **validators,
    }
    data = None if body is None else json.dumps(body).encode()
    if data is not None:
        headers["Content-Type"] = "application/json"
    if raw:
        headers["Accept"] = "text/html, application/rss+xml, application/json"
    for attempt in range(3):
        try:
            with urlopen(Request(url, data=data, headers=headers), timeout=22) as res:
                stream = (
                    gzip.GzipFile(fileobj=res)
                    if res.headers.get("Content-Encoding", "").lower() == "gzip"
                    else res
                )
                return (
                    stream.read().decode("utf-8", "replace")
                    if raw
                    else json.load(stream),
                    res.headers.get("ETag"),
                    res.headers.get("Last-Modified"),
                )
        except HTTPError as err:
            if err.code == 304:
                return None, None, None
            if err.code not in (408, 429, 500, 502, 503, 504) or attempt == 2:
                raise
            delay = retry_delay(err, 2**attempt)
            if delay > 60:
                raise
        except (URLError, OSError):
            if attempt == 2:
                raise
            delay = 2**attempt
        time.sleep(max(0, delay) + random.random())


def fetch_board(b, old):
    slug = quote(b["slug"], safe="")
    provider = b["provider"]
    if provider in enterprise.ADAPTERS:

        def get(url, **options):
            return fetch_page(url, {}, **options)[0]

        jobs = []
        try:
            for job in enterprise.ADAPTERS[provider](b, get):
                jobs.append(job)
        except (HTTPError, OSError, ValueError, KeyError) as error:
            if jobs:
                raise PartialBoard(jobs, error) from error
            raise
        return jobs, None, None
    base = {
        "greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
        "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
        "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
    }[provider]
    if provider == "lever" and b.get("region") == "eu":
        base = base.replace("api.lever.co", "api.eu.lever.co")
    validators = {}
    if provider != "lever":
        validators = {
            h: old[k]
            for k, h in [("etag", "If-None-Match"), ("modified", "If-Modified-Since")]
            if old[k]
        }
    rows, offset, observed = [], 0, set()
    while True:
        url = base + (f"&skip={offset}&limit=100" if provider == "lever" else "")
        data, etag, modified = fetch_page(url, validators)
        if data is None:
            if not validators:
                raise ValueError("Unexpected empty board")
            return None, old["etag"], old["modified"]
        page = data if provider == "lever" else data["jobs"]
        if not isinstance(page, list):
            raise ValueError("Unexpected board format")
        page_ids = set()
        for r in page:
            job = normalized(b, r)
            if job:
                page_ids.add(job["id"])
                if job["id"] not in observed:
                    rows.append(job)
                    observed.add(job["id"])
        if provider != "lever" or len(page) < 100:
            return rows, etag, modified
        if not page_ids or offset and not (page_ids - previous):
            raise ValueError("Pagination stopped advancing")
        previous = observed.copy()
        offset += len(page)


def classify(process, jobs):
    result = []
    for start in range(0, len(jobs), 100):
        process.stdin.write(
            json.dumps(jobs[start : start + 100], ensure_ascii=True) + "\n"
        )
        process.stdin.flush()
        result.extend(json.loads(process.stdout.readline()))
    return result


def completed_boards(pool, due, states):
    # Bound fetched descriptions in memory when classification or database writes run behind the network.
    remaining = iter(due)
    active = {}

    def enqueue():
        b = next(remaining, None)
        if b:
            active[pool.submit(fetch_board, b, states[key(b)])] = b

    for _ in range(8):
        enqueue()
    while active:
        ready, _ = concurrent.futures.wait(
            active, return_when=concurrent.futures.FIRST_COMPLETED
        )
        for future in ready:
            yield active.pop(future), future
            enqueue()


def update_jobs(db, board, process, jobs, version, *, complete=True):
    previous = dict(
        db.execute("SELECT id,fingerprint FROM classified WHERE board=?", (board,))
    )
    fingerprints = [
        (
            j["id"],
            board,
            hashlib.sha256(
                version + json.dumps(j, ensure_ascii=False).encode()
            ).digest(),
        )
        for j in jobs
    ]
    changed = [
        j
        for j, (_, _, digest) in zip(jobs, fingerprints)
        if previous.get(j["id"]) != digest
    ]
    accepted = classify(process, changed)
    if complete:
        db.execute("CREATE TEMP TABLE IF NOT EXISTS present(id TEXT PRIMARY KEY)")
        db.execute("DELETE FROM present")
        db.executemany("INSERT INTO present VALUES(?)", [(j["id"],) for j in jobs])
        for table in ("jobs", "classified"):
            db.execute(
                f"DELETE FROM {table} WHERE board=? AND id NOT IN (SELECT id FROM present)",
                (board,),
            )
    accepted_ids = {j["id"] for j in accepted}
    db.executemany(
        "DELETE FROM jobs WHERE id=?",
        [(j["id"],) for j in changed if j["id"] not in accepted_ids],
    )
    db.executemany(
        """INSERT INTO jobs VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data
                      WHERE data<>excluded.data""",
        [
            (j["id"], board, json.dumps(j, ensure_ascii=False, separators=(",", ":")))
            for j in accepted
        ],
    )
    db.executemany(
        "INSERT OR REPLACE INTO classified VALUES(?,?,?)",
        [f for f in fingerprints if previous.get(f[0]) != f[2]],
    )


def scan_status():
    with connect() as db:
        last = db.execute("SELECT value FROM settings WHERE key='last_scan'").fetchone()
        due = db.execute(
            "SELECT min(next_check) FROM boards WHERE status <> 'manual'"
        ).fetchone()[0]
    with SCAN_STATUS_LOCK:
        active = dict(active_scan) if active_scan else None
    return {
        "active": active,
        "last": json.loads(last[0]) if last else None,
        "nextCheckAt": dt.datetime.fromtimestamp(due, dt.timezone.utc).isoformat()
        if due is not None
        else None,
    }


def scan():
    global active_scan
    if not WRITE_LOCK.acquire(blocking=False):
        return
    try:
        with connect() as db:
            version = hashlib.sha256(
                b"".join(
                    p.read_bytes()
                    for p in (
                        Path(__file__),
                        Path(enterprise.__file__),
                        ROOT / "dist/match.js",
                        ROOT / "src/classify.mjs",
                    )
                )
            ).digest()
            stored = db.execute(
                "SELECT value FROM settings WHERE key='classification'"
            ).fetchone()
            if not stored or stored[0] != version.hex():
                with db:
                    db.execute(
                        "UPDATE boards SET etag=NULL, modified=NULL, next_check=0"
                    )
                    db.execute(
                        "INSERT OR REPLACE INTO settings VALUES('classification',?)",
                        (version.hex(),),
                    )
            states = {r["key"]: dict(r) for r in db.execute("SELECT * FROM boards")}
            due = [
                b
                for b in registry()
                if b["provider"] != "link"
                and states[key(b)]["next_check"] <= time.time()
            ]
            if not due:
                return
            started = time.monotonic()
            with SCAN_STATUS_LOCK:
                active_scan = {"startedAt": now(), "total": len(due), "checked": 0}
            command = [
                os.environ.get("JOB_NODE", "node"),
                str(ROOT / "src/classify.mjs"),
            ]
            with (
                subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    creationflags=HIDDEN_CHILD,
                ) as worker,
                concurrent.futures.ThreadPoolExecutor(8) as pool,
            ):
                for b, task in completed_boards(pool, due, states):
                    board = key(b)
                    stamp = now()
                    try:
                        jobs, etag, mod = task.result()
                        with db:
                            if jobs is not None:
                                update_jobs(db, board, worker, jobs, version)
                            db.execute(
                                """UPDATE boards SET status='ok',checked=?,good=?,etag=?,modified=?,next_check=?,
                                          count=(SELECT count(*) FROM jobs WHERE board=?),revision=revision+1 WHERE key=?""",
                                (
                                    stamp,
                                    stamp,
                                    etag,
                                    mod,
                                    time.time() + AGE,
                                    board,
                                    board,
                                ),
                            )
                    except Exception as e:
                        with db:
                            if isinstance(e, PartialBoard):
                                update_jobs(
                                    db, board, worker, e.jobs, version, complete=False
                                )
                                db.execute(
                                    """UPDATE boards SET status='partial',checked=?,next_check=?,
                                       count=(SELECT count(*) FROM jobs WHERE board=?),revision=revision+1 WHERE key=?""",
                                    (
                                        stamp,
                                        time.time()
                                        + max(1800, retry_delay(e.cause, 0)),
                                        board,
                                        board,
                                    ),
                                )
                                print(f"{board}: partial results: {e}", flush=True)
                                continue
                            db.execute(
                                """UPDATE boards SET checked=?,status=CASE WHEN good IS NULL AND count=0 THEN 'error' ELSE 'stale' END,
                                          next_check=?,revision=revision+1 WHERE key=?""",
                                (
                                    stamp,
                                    time.time() + max(1800, retry_delay(e, 0)),
                                    board,
                                ),
                            )
                        print(f"{board}: {type(e).__name__}: {e}", flush=True)
                    finally:
                        with SCAN_STATUS_LOCK:
                            active_scan["checked"] += 1
                worker.stdin.close()
            summary = {
                **active_scan,
                "finishedAt": now(),
                "seconds": round(time.monotonic() - started),
            }
            with db:
                db.execute(
                    "INSERT OR REPLACE INTO settings VALUES('last_scan',?)",
                    (json.dumps(summary),),
                )
            print(
                f"Scan finished in {summary['seconds']}s for {summary['checked']} boards",
                flush=True,
            )
    finally:
        with SCAN_STATUS_LOCK:
            active_scan = None
        WRITE_LOCK.release()


def cycle():
    while True:
        try:
            scan()
        except Exception as exc:
            print(f"Scan interrupted: {exc}", flush=True)
        time.sleep(90)
