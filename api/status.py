"""
api/status.py
-------------
Stores per-item read/review status in Vercel KV.
Used as a sync endpoint — localStorage is the primary store,
this is the cross-device backup.

GET  /api/status          → { statuses: { "<id>": { status, ts } } }
POST /api/status          → body: { id, status, ts }
                            status: "unread" | "read" | "review"
                            ts: epoch ms (from client)
                          → { ok: true }

Conflict resolution: whichever side has the higher `ts` wins.
The frontend merges KV data into localStorage on page load.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))
from upstash_redis import Redis  # noqa: E402

KV_STATUS_KEY = "item_statuses"

VALID_STATUSES = {"unread", "read", "review"}


def _get_redis() -> Redis:
    return Redis(
        url=os.environ["KV_REST_API_URL"],
        token=os.environ["KV_REST_API_TOKEN"],
    )


def _load_statuses(kv: Redis) -> dict:
    raw = kv.get(KV_STATUS_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _save_statuses(kv: Redis, statuses: dict):
    kv.set(KV_STATUS_KEY, json.dumps(statuses))


class handler(BaseHTTPRequestHandler):

    def do_GET(self):   # noqa: N802
        try:
            kv       = _get_redis()
            statuses = _load_statuses(kv)
            self._json(200, {"statuses": statuses})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_POST(self):  # noqa: N802
        try:
            length  = int(self.headers.get("Content-Length", 0))
            body    = json.loads(self.rfile.read(length))
            item_id = str(body.get("id", "")).strip()
            status  = str(body.get("status", "")).strip()
            ts      = int(body.get("ts", 0))

            if not item_id:
                self._json(400, {"error": "id required"}); return
            if status not in VALID_STATUSES:
                self._json(400, {"error": f"status must be one of {VALID_STATUSES}"}); return

            kv       = _get_redis()
            statuses = _load_statuses(kv)

            existing = statuses.get(item_id, {})
            # Only update if incoming ts is newer (or no existing entry)
            if ts >= existing.get("ts", 0):
                statuses[item_id] = {"status": status, "ts": ts}
                _save_statuses(kv, statuses)

            self._json(200, {"ok": True})
        except Exception as e:
            self._json(500, {"error": str(e)})

    def do_OPTIONS(self):  # noqa: N802  (CORS preflight)
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _json(self, code: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self._cors()
        self.end_headers()
        self.wfile.write(payload)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, *_):
        pass
