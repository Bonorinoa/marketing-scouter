"""Local JSON API (127.0.0.1 only) for the future dashboard. Stdlib http.server.

  GET  /api/state                      panels, interests, counts
  GET  /api/candidates?panel=&min=&status=
  GET  /api/candidate?id=              item + its drafts
  POST /api/scout     {panel?, source?, rescore?}   run a scout (blocking; the UI shows a spinner)
  POST /api/draft     {id, take?}      Hermes drafts; the take is stored verbatim
  POST /api/status    {id, status}     new | drafted | approved | dismissed
  POST /api/capture   {url, text?, panel?}

There is deliberately no endpoint that sends anything anywhere. A Host-header check blocks
DNS-rebinding from other sites; every POST must carry Content-Type: application/json.
"""
import json
import os
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import capture, config, draft, scout, store

PANELS = ("op-eds", "trends", "commentary")
WEB_DIR = os.path.join(config.ROOT, "web")
_scout_lock = threading.Lock()          # one scout at a time


class Handler(BaseHTTPRequestHandler):
    server_version = "scouter/0.1"

    def log_message(self, fmt, *args):  # one clean line per request
        print("  %s %s" % (self.command, self.path.split("?")[0]), "->", args[1] if len(args) > 1 else "")

    # ---- helpers
    def _host_ok(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- routes
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        db = store.connect()
        if u.path == "/api/state":
            counts = {p: db.execute("SELECT COUNT(*) FROM candidates WHERE panel=? AND relevance IS NOT NULL",
                                    (p,)).fetchone()[0] for p in PANELS}
            last = db.execute("SELECT ts, detail FROM events WHERE kind='scout' ORDER BY id DESC LIMIT 1").fetchone()
            return self._send(200, {"panels": PANELS, "interests": config.interests(), "counts": counts,
                                    "min_relevance": config.sources().get("min_relevance", 0.15),
                                    "draft_model": config.load_json("settings.json")["draft"].get("model"),
                                    "last_scout": ({"ts": last["ts"], **json.loads(last["detail"])} if last else None)})
        if u.path == "/api/candidates":
            rows = store.list_candidates(db, panel=q.get("panel"), status=q.get("status"),
                                         min_relevance=float(q.get("min", config.sources().get("min_relevance", 0.15))),
                                         limit=int(q.get("limit", 100)))
            return self._send(200, rows)
        if u.path == "/api/candidate":
            c = store.get_candidate(db, q.get("id", ""))
            if not c:
                return self._send(404, {"error": "unknown id"})
            c["drafts"] = store.list_drafts(db, c["id"])
            return self._send(200, c)
        return self._static(u.path)

    def _static(self, path):
        """Serve web/ once a frontend exists. Nothing is served outside that directory."""
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.realpath(os.path.join(WEB_DIR, rel))
        if not full.startswith(os.path.realpath(WEB_DIR) + os.sep) or not os.path.isfile(full):
            return self._send(404, {"error": "not found"})
        kinds = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml", ".json": "application/json",
                 ".png": "image/png", ".ico": "image/x-icon"}
        data = open(full, "rb").read()
        self.send_response(200)
        self.send_header("Content-Type", kinds.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._host_ok():
            return self._send(403, {"error": "bad host"})
        if "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._send(415, {"error": "json only"})
        try:
            b = self._body()
            db = store.connect()
            if self.path == "/api/scout":
                if not _scout_lock.acquire(blocking=False):
                    return self._send(409, {"error": "a scout is already running"})
                try:
                    lines = []
                    s = scout.run(panel=b.get("panel"), source=b.get("source"),
                                  rescore=bool(b.get("rescore")), log=lines.append)
                finally:
                    _scout_lock.release()
                return self._send(200, {"summary": s, "log": lines})
            if self.path == "/api/draft":
                return self._send(200, draft.make_draft(b["id"], user_take=b.get("take"), db=db))
            if self.path == "/api/draft/save":
                # Authorship follows action: a human edit is stored as its own version, labelled as yours.
                cand = store.get_candidate(db, b["id"])
                if not cand or not str(b.get("text", "")).strip():
                    return self._send(400, {"error": "unknown id or empty text"})
                did = store.add_draft(db, b["id"], b.get("take"), cand.get("lens"), b["text"], "", [], "you (edited)")
                return self._send(200, {"draft_id": did})
            if self.path == "/api/status":
                store.set_status(db, b["id"], b["status"])
                return self._send(200, {"ok": True})
            if self.path == "/api/capture":
                return self._send(200, capture.capture(b["url"], text=b.get("text"), panel=b.get("panel", "commentary")))
            return self._send(404, {"error": "unknown route"})
        except (KeyError, ValueError) as e:
            return self._send(400, {"error": "bad request: %s" % e})
        except (RuntimeError, OSError, SystemExit) as e:
            return self._send(502, {"error": str(e)})


def serve(port=8787, open_browser=False):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = "http://127.0.0.1:%d" % port
    print("Marketing Scouter on %s  (Ctrl-C to stop)" % url)
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
