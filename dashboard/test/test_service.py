"""Exercise real accounts and HTTP requests with a disposable database."""

import http.cookiejar
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server
from src import catalog


def client():
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


class DashboardTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        state = patch.object(catalog, "DATA", Path(temp.name))
        state.start()
        self.addCleanup(state.stop)
        server.catalog_cache.clear()
        server.init()
        self.server = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def call(self, opener, path, method="GET", body=None, extra=None):
        req = urllib.request.Request(
            self.base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", **(extra or {})},
        )
        try:
            with opener.open(req) as res:
                return res.status, json.load(res)
        except urllib.error.HTTPError as err:
            return err.code, None

    def test_private_applications_survive_closure(self):
        a, b = client(), client()
        for opener, name in [(a, "alice"), (b, "bravo")]:
            self.assertEqual(
                self.call(
                    opener,
                    "/api/register",
                    "POST",
                    {"username": name, "password": "unique secret " + name},
                )[0],
                200,
            )
        job = {"id": "demo:1", "title": "Data Engineer"}
        with catalog.connect() as db:
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?)", (job["id"], "demo", json.dumps(job))
            )
        path = "/api/applications"
        body = {"jobId": job["id"]}
        self.assertEqual(self.call(a, "/api/shortlist", "PUT", body)[0], 200)
        self.assertEqual(self.call(a, "/api/session")[1]["shortlist"][0]["job"], job)
        self.assertEqual(self.call(b, "/api/session")[1]["shortlist"], [])
        self.assertEqual(
            self.call(a, path, "PUT", body, {"Origin": "https://wrong.example"})[0], 403
        )
        self.assertEqual(self.call(a, path, "PUT", body)[0], 200)
        self.assertEqual(self.call(a, path, "PUT", body)[0], 200)
        self.assertEqual(self.call(a, "/api/session")[1]["shortlist"], [])
        details = {
            **body,
            "stage": "interview",
            "notes": "Ask about the team",
            "followUp": "2026-11-23",
        }
        self.assertEqual(self.call(b, path + "/details", "PUT", details)[0], 404)
        self.assertEqual(
            self.call(
                a, path + "/details", "PUT", {**details, "followUp": "2026-02-30"}
            )[0],
            400,
        )
        self.assertEqual(self.call(a, path + "/details", "PUT", details)[0], 200)
        archive = "/api/archive"
        self.assertEqual(self.call(client(), archive, "PUT", body)[0], 401)
        first_archive = self.call(a, archive, "PUT", body)
        self.assertEqual(first_archive[0], 200)
        self.assertEqual(self.call(a, archive, "PUT", body), first_archive)
        self.assertEqual(self.call(b, archive, "DELETE", body)[0], 200)
        with catalog.connect() as db:
            db.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
        prefs = {
            "location": "Pune",
            "years": 4,
            "includeUncertain": False,
            "maxAgeDays": 14,
            "levels": ["entry", "mid"],
            "includeUndated": False,
            "hideApplied": True,
        }
        self.assertEqual(self.call(a, "/api/preferences", "PUT", prefs)[0], 200)
        sa = self.call(a, "/api/session")[1]
        self.assertEqual(sa["preferences"]["maxAgeDays"], 14)
        self.assertEqual(sa["preferences"]["levels"], ["entry", "mid"])
        self.assertTrue(sa["preferences"]["hideApplied"])
        self.assertEqual([x["job"] for x in sa["applications"]], [job])
        for field in ("stage", "notes", "followUp"):
            self.assertEqual(sa["applications"][0][field], details[field])
        self.assertEqual(sa["archives"], [first_archive[1]])
        self.assertEqual(self.call(b, "/api/session")[1]["applications"], [])
        self.assertEqual(self.call(b, "/api/session")[1]["archives"], [])
        self.assertEqual(self.call(b, "/api/session")[1]["preferences"], {})
        self.assertEqual(self.call(a, "/api/logout", "POST", {})[0], 200)
        self.assertEqual(self.call(a, "/api/session")[0], 401)
        self.assertEqual(
            self.call(
                a,
                "/api/login",
                "POST",
                {"username": "alice", "password": "unique secret alice"},
            )[0],
            200,
        )
        self.assertEqual(self.call(a, path, "DELETE", body)[0], 200)
        self.assertEqual(self.call(a, "/api/session")[1]["applications"], [])
        self.assertEqual(self.call(a, archive, "DELETE", body)[0], 200)
        self.assertEqual(self.call(a, "/api/session")[1]["archives"], [])
        self.assertEqual(self.call(a, archive, "PUT", body)[0], 404)

    def test_reuse_and_remove_changed_postings(self):
        a = {"id": "a", "title": "Software Engineer", "description": "building APIs"}

        def accept(_, rows):
            return [dict(row) for row in rows if row["title"] == "Software Engineer"]

        with (
            catalog.connect() as db,
            patch.object(catalog, "classify", side_effect=accept) as classify,
        ):
            catalog.update_jobs(db, "demo", None, [a], b"v1")
            catalog.update_jobs(db, "demo", None, [a], b"v1")
            self.assertEqual(classify.call_args.args[1], [])
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            catalog.update_jobs(db, "demo", None, [], b"v1", complete=False)
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1)
            catalog.update_jobs(db, "demo", None, [dict(a, title="Sales")], b"v1")
            self.assertEqual(db.execute("SELECT count(*) FROM jobs").fetchone()[0], 0)
            catalog.update_jobs(db, "demo", None, [], b"v1")
            self.assertEqual(
                db.execute("SELECT count(*) FROM classified").fetchone()[0], 0
            )

    def test_incomplete_and_unchanged_boards_preserve_history(self):
        board = {"company": "Demo", "provider": "lever", "slug": "demo"}
        job = {
            "id": "lever:demo:1",
            "company": "Demo",
            "title": "Software Engineer",
            "description": "Python",
            "location": "Pune",
            "url": "https://example.org/job/1",
            "posted": None,
            "workplace": "",
        }
        with patch.object(catalog, "registry", return_value=[board]):
            catalog.init()
            for result, status in [
                (([job], "tag", None), "ok"),
                (TimeoutError(), "stale"),
                ((None, "tag", None), "ok"),
            ]:
                with catalog.connect() as db:
                    db.execute("UPDATE boards SET next_check=0 WHERE key='lever:demo'")
                with patch.object(catalog, "fetch_board", side_effect=[result]):
                    catalog.scan()
                code, scan = self.call(client(), "/api/scan")
                self.assertEqual(code, 200)
                self.assertIsNone(scan["active"])
                self.assertEqual(scan["last"]["checked"], 1)
                self.assertGreaterEqual(scan["last"]["seconds"], 0)
                self.assertTrue(scan["nextCheckAt"])
                with catalog.connect() as db:
                    self.assertEqual(
                        db.execute(
                            "SELECT status FROM boards WHERE key='lever:demo'"
                        ).fetchone()[0],
                        status,
                    )
                    self.assertEqual(
                        db.execute("SELECT count(*) FROM jobs").fetchone()[0], 1
                    )
