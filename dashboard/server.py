"""Serve the dashboard on loopback with persistent accounts, application snapshots and a shared scanner."""

import argparse
from datetime import date
import gzip
import hashlib
import hmac
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import logging
from logging.handlers import RotatingFileHandler
import threading
import time
from urllib.parse import urlsplit

from src import catalog, telegram_alerts

STATIC = Path(__file__).resolve().parent / "dist"
ACCOUNT = Path(__file__).resolve().parent / "account.html"
SESSION_SECONDS = 30 * 86400
catalog_cache = {}
cache_lock = threading.Lock()
login_slots = threading.BoundedSemaphore(2)
STAGES = {
    "applied",
    "screening",
    "interview",
    "offer",
    "accepted",
    "rejected",
    "withdrawn",
}


def init():
    catalog.init()
    with catalog.connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
            salt BLOB NOT NULL, digest BLOB NOT NULL, preferences TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user INTEGER NOT NULL, expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS applications(user INTEGER NOT NULL, jobid TEXT NOT NULL, data TEXT NOT NULL,
            applied TEXT NOT NULL, PRIMARY KEY(user,jobid));
        CREATE TABLE IF NOT EXISTS archives(user INTEGER NOT NULL, jobid TEXT NOT NULL, data TEXT NOT NULL,
            archived TEXT NOT NULL, PRIMARY KEY(user,jobid));
        CREATE TABLE IF NOT EXISTS shortlist(user INTEGER NOT NULL, jobid TEXT NOT NULL, data TEXT NOT NULL,
            saved TEXT NOT NULL, PRIMARY KEY(user,jobid));
        """)
        columns = {
            column["name"] for column in db.execute("PRAGMA table_info(applications)")
        }
        for field, definition in (
            ("stage", "TEXT NOT NULL DEFAULT 'applied'"),
            ("notes", "TEXT NOT NULL DEFAULT ''"),
            ("follow_up", "TEXT"),
        ):
            if field not in columns:
                db.execute(f"ALTER TABLE applications ADD COLUMN {field} {definition}")


def application(row):
    return {
        "job": json.loads(row["data"]),
        "appliedAt": row["applied"],
        "stage": row["stage"],
        "notes": row["notes"],
        "followUp": row["follow_up"],
    }


def application_details(body):
    stage, notes, follow_up = body.get("stage"), body.get("notes"), body.get("followUp")
    if not isinstance(stage, str) or stage not in STAGES:
        raise ValueError("Choose a valid stage")
    if not isinstance(notes, str) or len(notes) > 2000:
        raise ValueError("Notes must be 2,000 characters or fewer")
    if follow_up is not None:
        if (
            not isinstance(follow_up, str)
            or date.fromisoformat(follow_up).isoformat() != follow_up
        ):
            raise ValueError("Choose a valid follow-up date")
    return stage, notes.strip(), follow_up


def password_hash(password, salt):
    return hashlib.scrypt(
        password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024
    )


def snapshot(db):
    with cache_lock:
        db.execute("BEGIN")
        try:
            sources = [
                dict(row)
                for row in db.execute("""SELECT key,company,status,checked AS checkedAt,good AS lastSuccessAt,
                                                         count,revision FROM boards ORDER BY company""")
            ]
            version = str(sum(s["revision"] for s in sources)) + "-" + str(len(sources))
            if catalog_cache.get("version") != version:
                board_details = {
                    catalog.key(board): {
                        "careers": board.get("careers"),
                        "scope": board.get("scope"),
                    }
                    for board in catalog.registry()
                }
                for source in sources:
                    source.update(board_details.get(source["key"], {}))
                payload = {
                    "updatedAt": max(
                        (s["lastSuccessAt"] for s in sources if s["lastSuccessAt"]),
                        default=None,
                    ),
                    "sources": sources,
                }
                header = json.dumps(payload, ensure_ascii=False)[:-1]
                contents = (
                    header
                    + ',"jobs":['
                    + ",".join(r[0] for r in db.execute("SELECT data FROM jobs"))
                    + "]}"
                )
                raw = contents.encode()
                catalog_cache.update(
                    version=version,
                    raw=raw,
                    compressed=gzip.compress(raw, compresslevel=3),
                )
            return version, catalog_cache["raw"], catalog_cache["compressed"]
        finally:
            db.rollback()


def preferences(value):
    if not isinstance(value, dict):
        raise ValueError("Invalid preferences")
    out = {}
    for k in ("families", "skills", "levels"):
        v = value.get(k, [])
        if (
            not isinstance(v, list)
            or len(v) > 100
            or any(not isinstance(item, str) or len(item) > 100 for item in v)
        ):
            raise ValueError("Invalid " + k)
        out[k] = list(dict.fromkeys(v))
    if set(out["levels"]) - {"intern", "entry", "mid", "senior", "lead"}:
        raise ValueError("Invalid seniority level")
    for k in ("location", "workplace"):
        v = value.get(k, "")
        if not isinstance(v, str) or len(v) > 200:
            raise ValueError("Invalid " + k)
        out[k] = v.strip()
    years = value.get("years")
    if years is not None and (type(years) not in (float, int) or not 0 <= years <= 80):
        raise ValueError("Years must be between 0 and 80")
    out.update(years=years, includeUncertain=value.get("includeUncertain", True))
    if type(out["includeUncertain"]) is not bool:
        raise ValueError("Invalid review setting")
    days = value.get("maxAgeDays")
    if days is not None and (type(days) is not int or not 1 <= days <= 3650):
        raise ValueError("Invalid posting age")
    out.update(maxAgeDays=days, includeUndated=value.get("includeUndated", True))
    if type(out["includeUndated"]) is not bool:
        raise ValueError("Invalid posting date setting")
    out["hideApplied"] = value.get("hideApplied", False)
    if type(out["hideApplied"]) is not bool:
        raise ValueError("Invalid application visibility setting")
    return out


class Handler(BaseHTTPRequestHandler):
    def parse_request(self):
        if not super().parse_request():
            return False
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host not in ("localhost", "127.0.0.1"):
            self.send_error(403)
            return False
        return True

    def reply(self, status, data=b"", mime="application/json", headers=None):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        for k, v in {
            "Content-Type": mime,
            "Content-Length": str(len(data)),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Referrer-Policy": "same-origin",
            "X-Frame-Options": "DENY",
            **(headers or {}),
        }.items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def token(self):
        cookie = SimpleCookie()
        cookie.load(self.headers.get("Cookie", ""))
        raw = cookie["session"].value if "session" in cookie else ""
        return hashlib.sha256(raw.encode()).hexdigest()

    def get_user(self, db):
        return db.execute(
            """SELECT u.* FROM sessions s JOIN users u ON s.user=u.id
                             WHERE s.token=? AND s.expires>?""",
            (self.token(), time.time()),
        ).fetchone()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/jobs":
            with catalog.connect() as db:
                version, raw, compressed = snapshot(db)
            tag = '"' + version + '"'
            headers = {
                "ETag": tag,
                "Vary": "Accept-Encoding",
                "Cache-Control": "private, no-cache",
            }
            if self.headers.get("If-None-Match") == tag:
                return self.reply(304, headers=headers)
            if "gzip" in self.headers.get("Accept-Encoding", ""):
                headers["Content-Encoding"] = "gzip"
                raw = compressed
            return self.reply(200, raw, headers=headers)
        if path == "/api/session":
            with catalog.connect() as db:
                user = self.get_user(db)
                if not user:
                    return self.reply(401, {"error": "Sign in to save your search"})
                apps = [
                    application(r)
                    for r in db.execute(
                        "SELECT * FROM applications WHERE user=? ORDER BY applied DESC",
                        (user["id"],),
                    )
                ]
                archived = [
                    {"job": json.loads(r[0]), "archivedAt": r[1]}
                    for r in db.execute(
                        "SELECT data,archived FROM archives WHERE user=? ORDER BY archived DESC",
                        (user["id"],),
                    )
                ]
                shortlist = [
                    {"job": json.loads(r["data"]), "savedAt": r["saved"]}
                    for r in db.execute(
                        "SELECT data,saved FROM shortlist WHERE user=? ORDER BY saved DESC",
                        (user["id"],),
                    )
                ]
                return self.reply(
                    200,
                    {
                        "user": {"id": str(user["id"]), "name": user["username"]},
                        "preferences": json.loads(user["preferences"]),
                        "applications": apps,
                        "archives": archived,
                        "shortlist": shortlist,
                    },
                )
        if path == "/api/scan":
            return self.reply(200, catalog.scan_status())
        files = {
            "/": STATIC / "index.html",
            "/index.html": STATIC / "index.html",
            "/app.js": STATIC / "app.js",
            "/match.js": STATIC / "match.js",
            "/style.css": STATIC / "style.css",
            "/account": ACCOUNT,
        }
        file = files.get(path)
        if file and file.is_file():
            return self.reply(
                200,
                file.read_bytes(),
                (mimetypes.guess_type(file.name)[0] or "text/plain")
                + "; charset=utf-8",
            )
        self.reply(404, {"error": "Page not found"})

    def write_request(self):
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self.reply(415, {"error": "Expected JSON"})
        origin = self.headers.get("Origin")
        if origin and urlsplit(origin).netloc != self.headers.get("Host"):
            return self.reply(403, {"error": "Invalid origin"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 <= length <= 16384:
                return self.reply(413, {"error": "Request too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("Expected object")
            path = urlsplit(self.path).path
            with catalog.connect() as db:
                if self.command == "POST" and path in ("/api/login", "/api/register"):
                    username, password = (
                        body.get("username", ""),
                        body.get("password", ""),
                    )
                    if (
                        not isinstance(username, str)
                        or not isinstance(password, str)
                        or not 2 <= len(username.strip()) <= 64
                        or not 10 <= len(password) <= 256
                    ):
                        raise ValueError(
                            "Use a 2–64 character username and a 10–256 character password"
                        )
                    username = username.strip()
                    if not login_slots.acquire(blocking=False):
                        return self.reply(
                            429, {"error": "Please try again in a moment"}
                        )
                    try:
                        if path.endswith("register"):
                            salt = secrets.token_bytes(16)
                            try:
                                uid = db.execute(
                                    "INSERT INTO users(username,salt,digest) VALUES(?,?,?)",
                                    (username, salt, password_hash(password, salt)),
                                ).lastrowid
                            except sqlite3.IntegrityError:
                                return self.reply(
                                    409, {"error": "Username already in use"}
                                )
                        else:
                            user = db.execute(
                                "SELECT * FROM users WHERE username=?", (username,)
                            ).fetchone()
                            candidate = password_hash(
                                password, user["salt"] if user else bytes(16)
                            )
                            if not user or not hmac.compare_digest(
                                candidate, user["digest"]
                            ):
                                return self.reply(
                                    401, {"error": "Check your username and password"}
                                )
                            uid = user["id"]
                        token = secrets.token_urlsafe(32)
                        db.execute(
                            "DELETE FROM sessions WHERE expires<=? OR token=?",
                            (time.time(), self.token()),
                        )
                        db.execute(
                            "INSERT INTO sessions VALUES(?,?,?)",
                            (
                                hashlib.sha256(token.encode()).hexdigest(),
                                uid,
                                time.time() + SESSION_SECONDS,
                            ),
                        )
                        db.commit()
                        return self.reply(
                            200,
                            {"ok": True},
                            headers={
                                "Set-Cookie": f"session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={SESSION_SECONDS}"
                            },
                        )
                    finally:
                        login_slots.release()
                user = self.get_user(db)
                if not user:
                    return self.reply(401, {"error": "Sign in first"})
                if self.command == "POST" and path == "/api/logout":
                    db.execute("DELETE FROM sessions WHERE token=?", (self.token(),))
                    db.commit()
                    return self.reply(
                        200,
                        {"redirect": "/"},
                        headers={
                            "Set-Cookie": "session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
                        },
                    )
                if self.command == "PUT" and path == "/api/preferences":
                    value = preferences(body)
                    db.execute(
                        "UPDATE users SET preferences=? WHERE id=?",
                        (json.dumps(value), user["id"]),
                    )
                elif path == "/api/shortlist" and self.command in ("PUT", "DELETE"):
                    jid = body.get("jobId")
                    if not isinstance(jid, str) or not 0 < len(jid) <= 2048:
                        raise ValueError("Invalid job ID")
                    if self.command == "DELETE":
                        db.execute(
                            "DELETE FROM shortlist WHERE user=? AND jobid=?",
                            (user["id"], jid),
                        )
                    else:
                        db.execute(
                            "INSERT OR IGNORE INTO shortlist SELECT ?,id,data,? FROM jobs WHERE id=?",
                            (user["id"], catalog.now(), jid),
                        )
                        saved = db.execute(
                            "SELECT data,saved FROM shortlist WHERE user=? AND jobid=?",
                            (user["id"], jid),
                        ).fetchone()
                        if not saved:
                            return self.reply(
                                404, {"error": "This posting has left the feed"}
                            )
                        db.commit()
                        return self.reply(
                            200,
                            {
                                "job": json.loads(saved["data"]),
                                "savedAt": saved["saved"],
                            },
                        )
                elif path == "/api/archive" and self.command in ("PUT", "DELETE"):
                    job_id = body.get("jobId")
                    if not isinstance(job_id, str) or not 0 < len(job_id) <= 2048:
                        raise ValueError("Invalid job ID")
                    if self.command == "DELETE":
                        db.execute(
                            "DELETE FROM archives WHERE user=? AND jobid=?",
                            (user["id"], job_id),
                        )
                    else:
                        db.execute(
                            "INSERT OR IGNORE INTO archives SELECT ?,id,data,? FROM jobs WHERE id=?",
                            (user["id"], catalog.now(), job_id),
                        )
                        record = db.execute(
                            "SELECT data,archived FROM archives WHERE user=? AND jobid=?",
                            (user["id"], job_id),
                        ).fetchone()
                        if not record:
                            return self.reply(
                                404, {"error": "This posting has left the feed"}
                            )
                        db.commit()
                        return self.reply(
                            200,
                            {
                                "job": json.loads(record["data"]),
                                "archivedAt": record["archived"],
                            },
                        )
                elif path == "/api/applications/details" and self.command == "PUT":
                    jid = body.get("jobId")
                    if not isinstance(jid, str) or not 0 < len(jid) <= 2048:
                        raise ValueError("Invalid job ID")
                    details = application_details(body)
                    record = db.execute(
                        """UPDATE applications SET stage=?,notes=?,follow_up=?
                           WHERE user=? AND jobid=? RETURNING *""",
                        (*details, user["id"], jid),
                    ).fetchone()
                    if record is None:
                        return self.reply(404, {"error": "Application not found"})
                    db.commit()
                    return self.reply(200, application(record))
                elif path == "/api/applications" and self.command in ("PUT", "DELETE"):
                    jid = body.get("jobId")
                    if not isinstance(jid, str) or len(jid) > 2048:
                        raise ValueError("Invalid job ID")
                    if self.command == "DELETE":
                        db.execute(
                            "DELETE FROM applications WHERE user=? AND jobid=?",
                            (user["id"], jid),
                        )
                    else:
                        db.execute(
                            """INSERT OR IGNORE INTO applications(user,jobid,data,applied)
                               SELECT ?,id,data,? FROM jobs WHERE id=?""",
                            (user["id"], catalog.now(), jid),
                        )
                        db.execute(
                            """INSERT OR IGNORE INTO applications(user,jobid,data,applied)
                               SELECT user,jobid,data,? FROM shortlist WHERE user=? AND jobid=?""",
                            (catalog.now(), user["id"], jid),
                        )
                        saved = db.execute(
                            "SELECT * FROM applications WHERE user=? AND jobid=?",
                            (user["id"], jid),
                        ).fetchone()
                        if not saved:
                            return self.reply(404, {"error": "This posting has closed"})
                        db.execute(
                            "DELETE FROM shortlist WHERE user=? AND jobid=?",
                            (user["id"], jid),
                        )
                        db.commit()
                        return self.reply(200, application(saved))
                else:
                    return self.reply(404, {"error": "Unknown action"})
                db.commit()
                return self.reply(200, {"ok": True})
        except (ValueError, UnicodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except sqlite3.OperationalError:
            self.reply(503, {"error": "Database busy. Try again shortly."})

    do_POST = do_PUT = do_DELETE = write_request


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-scan", action="store_true")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    os.environ["JOB_NODE"] = args.node
    if args.background:
        catalog.DATA.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.INFO,
            handlers=[
                RotatingFileHandler(
                    catalog.DATA / "dashboard.log",
                    maxBytes=2000000,
                    backupCount=3,
                    encoding="utf-8",
                )
            ],
        )

        class LogStream:
            def write(self, text):
                if text.strip():
                    logging.info("%s", text.rstrip())

            def flush(self):
                pass

        sys.stderr = sys.stdout = LogStream()
    init()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if not args.no_scan:
        threading.Thread(target=catalog.cycle, daemon=True).start()
        threading.Thread(target=telegram_alerts.cycle, daemon=True).start()
    print(f"Dashboard listening at http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
