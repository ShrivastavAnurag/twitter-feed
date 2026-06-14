"""
api/scrape.py
-------------
Vercel serverless function + cron job.

Cron schedule (vercel.json):  "0 0 * * *"  →  runs at 00:00 UTC every day

Can also be triggered manually:
  GET  /api/scrape              — runs scraper, stores to KV, returns summary JSON
  POST /api/scrape              — same (Vercel cron uses GET)

Environment variables required (set in Vercel dashboard → Settings → Environment Variables):
  KV_REST_API_URL      — from Vercel KV store dashboard
  KV_REST_API_TOKEN    — from Vercel KV store dashboard
  CRON_SECRET          — any random string you set; prevents public abuse
                         (Vercel passes it automatically for cron calls)
"""

import json
import os
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

# Allow importing sibling module when running as Vercel function
sys.path.insert(0, os.path.dirname(__file__))
from scraper_core import scrape_all, FOLLOWEES   # noqa: E402

from upstash_redis import Redis                  # noqa: E402

KV_TWEETS_KEY  = "tweets"
KV_REPLIES_KEY = "replies"
KV_META_KEY    = "meta"


def _get_redis() -> Redis:
    url   = os.environ["KV_REST_API_URL"]
    token = os.environ["KV_REST_API_TOKEN"]
    return Redis(url=url, token=token)


def _run_scrape() -> dict:
    tweets, replies = scrape_all(verbose=False)

    # Store in KV
    kv = _get_redis()
    kv.set(KV_TWEETS_KEY,  json.dumps(tweets))
    kv.set(KV_REPLIES_KEY, json.dumps(replies))
    kv.set(KV_META_KEY, json.dumps({
        "last_scraped": datetime.now(timezone.utc).isoformat(),
        "tweet_count":  len(tweets),
        "reply_count":  len(replies),
        "followees":    FOLLOWEES,
    }))

    return {
        "status":       "ok",
        "tweet_count":  len(tweets),
        "reply_count":  len(replies),
        "scraped_at":   datetime.now(timezone.utc).isoformat(),
    }


class handler(BaseHTTPRequestHandler):

    def _auth_ok(self) -> bool:
        """
        Vercel cron requests include:
          Authorization: Bearer <CRON_SECRET>
        Reject anything without it (so random people can't hammer Nitter via your URL).
        """
        secret = os.environ.get("CRON_SECRET", "")
        if not secret:
            return True                          # not set → open (dev mode)
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {secret}"

    def do_GET(self):   # noqa: N802
        self._handle()

    def do_POST(self):  # noqa: N802
        self._handle()

    def _handle(self):
        if not self._auth_ok():
            self._respond(403, {"error": "Forbidden"})
            return
        try:
            result = _run_scrape()
            self._respond(200, result)
        except Exception as exc:
            self._respond(500, {"error": str(exc)})

    def _respond(self, status: int, body: dict):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type",  "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):  # silence default stdout logging
        pass
