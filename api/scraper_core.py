"""
scraper_core.py  —  Twitter API v2 based scraper
Uses Bearer Token (read-only, free tier — 500k tweets/month)
"""

import os
import re
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import requests

# ─────────────────────────────────────────────
#  FOLLOWEES  — add / remove handles here
# ─────────────────────────────────────────────
FOLLOWEES = [
    "tiwarisuhani_11",
    "tanujDE3180",
    "javarevisited",
    "ashoKumar89",
    "krunalbuilds",
    "devXritesh",
    "system_monarch",
    "Its_Nova1012",
    "SidJain_80",
    "0xlelouch_",
]

# Max tweets to fetch per user (max 100 per request on free tier)
MAX_TWEETS_PER_USER = 50

# ─────────────────────────────────────────────
#  TOPIC DETECTION
# ─────────────────────────────────────────────
TOPIC_RULES = [
    ("System Design",     r"\b(system design|scalab|distributed|microservice|monolith|sharding|replication|consistency|CAP theorem|load balanc|cdn|cache|redis|kafka|rabbit|message queue|event.driven|database design|high.availab)\b"),
    ("Data Structures",   r"\b(array|linked list|tree|graph|heap|trie|stack|queue|hash ?map|hash ?table|binary search|BST|AVL|segment tree|fenwick|union.find)\b"),
    ("Algorithms",        r"\b(algorithm|dynamic programming|\bDP\b|recursion|backtrack|greedy|\bBFS\b|\bDFS\b|sorting|two pointer|sliding window|time complexity|space complexity|Big.?O)\b"),
    ("Databases",         r"\b(SQL|NoSQL|postgres|mysql|mongodb|index|query optim|ACID|transaction|normalization|\bjoin\b|ORM|schema|migration|stored proc)\b"),
    ("Networking",        r"\b(HTTP|HTTPS|TCP|UDP|REST|gRPC|GraphQL|websocket|long.?poll|DNS|TLS|SSL|\bAPI\b|endpoint|latency|bandwidth|\bCDN\b|proxy)\b"),
    ("Operating Systems", r"\b(OS\b|process|thread|concurren|mutex|semaphore|deadlock|virtual memory|paging|scheduler|context switch|kernel|race condition)\b"),
    ("Cloud / DevOps",    r"\b(AWS|GCP|Azure|docker|kubernetes|\bk8s\b|CI.?CD|terraform|ansible|devops|serverless|lambda|container|orchestrat)\b"),
    ("Object-Oriented",   r"\b(OOP|SOLID|design pattern|singleton|factory|observer|strategy|decorator|inheritance|polymorphism|encapsulation|abstraction)\b"),
    ("Security",          r"\b(security|auth|OAuth|JWT|XSS|CSRF|SQL injection|encrypt|hash|salt|certificate|firewall|penetration)\b"),
    ("JavaScript / Web",  r"\b(javascript|typescript|react|vue|angular|node\.?js|event loop|promise|async|await|closure|prototype|\bDOM\b|webpack|vite)\b"),
    ("Python",            r"\b(python|django|flask|fastapi|pandas|numpy|\bGIL\b|list comprehension|generator|pip|virtualenv)\b"),
    ("Java / JVM",        r"\b(java\b|jvm|spring|maven|gradle|garbage collect|generics|stream API|thread pool|HashMap|ArrayList)\b"),
    ("Interview Tips",    r"\b(interview|leetcode|coding challenge|whiteboard|cracking|faang|big.?n\b)\b"),
]

QUESTION_RE = re.compile(
    r"(\?)|(\bhow\b)|(\bwhat\b)|(\bwhy\b)|(\bexplain\b)|(\bdifference\b)|"
    r"(\bcompare\b)|(\bvs\.?\b)|(\badvantage\b)|(\bpros\b)|(\bcons\b)|"
    r"(\bdefine\b)|(\bdescribe\b)|(\binterview\b)|(\bquestion\b)",
    re.IGNORECASE,
)


def detect_topics(text: str) -> list:
    found = [t for t, p in TOPIC_RULES if re.search(p, text, re.IGNORECASE)]
    return found or ["General Tech"]


def is_question(text: str) -> bool:
    return bool(QUESTION_RE.search(text)) or detect_topics(text) != ["General Tech"]


# ─────────────────────────────────────────────
#  TWITTER API v2 CLIENT
# ─────────────────────────────────────────────
API_BASE = "https://api.twitter.com/2"


def _bearer() -> str:
    token = os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not token:
        raise RuntimeError("TWITTER_BEARER_TOKEN env var not set")
    return token


def _headers() -> dict:
    return {"Authorization": f"Bearer {_bearer()}"}


def _get(path: str, params: dict) -> Optional[dict]:
    """Make a GET request to Twitter API v2. Returns JSON or None on error."""
    try:
        r = requests.get(
            f"{API_BASE}{path}",
            headers=_headers(),
            params=params,
            timeout=15,
        )
        if r.status_code == 429:
            # Rate limited — wait and retry once
            reset = int(r.headers.get("x-rate-limit-reset", time.time() + 60))
            wait  = max(reset - int(time.time()), 5)
            print(f"  Rate limited, waiting {wait}s…", flush=True)
            time.sleep(min(wait, 30))
            r = requests.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=15)
        if r.status_code == 200:
            return r.json()
        print(f"  API error {r.status_code}: {r.text[:200]}", flush=True)
    except Exception as e:
        print(f"  Request error: {e}", flush=True)
    return None


def _format_date(iso: str) -> tuple:
    """Convert ISO 8601 → (YYYY-MM-DD, DD Mon YYYY)"""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%d %b %Y")
    except Exception:
        return "", iso[:10]


def _tweet_url(username: str, tweet_id: str) -> str:
    return f"https://twitter.com/{username}/status/{tweet_id}"


# ─────────────────────────────────────────────
#  USER LOOKUP
# ─────────────────────────────────────────────
def _get_user_id(username: str) -> Optional[str]:
    data = _get(f"/users/by/username/{username}", {"user.fields": "id"})
    if data and "data" in data:
        return data["data"]["id"]
    return None


# ─────────────────────────────────────────────
#  TWEET FETCHING
# ─────────────────────────────────────────────
TWEET_FIELDS  = "created_at,text,referenced_tweets,in_reply_to_user_id"
TWEET_EXPANSIONS = "referenced_tweets.id,in_reply_to_user_id"
USER_FIELDS   = "username"

def _fetch_user_tweets(user_id: str, username: str) -> tuple:
    """
    Fetch recent tweets + replies for a user.
    Returns (tweets_list, replies_list)
    """
    tweets_out  = []
    replies_out = []

    # Fetch last 7 days (free tier limit)
    start_time = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    params = {
        "max_results":  MAX_TWEETS_PER_USER,
        "tweet.fields": TWEET_FIELDS,
        "expansions":   TWEET_EXPANSIONS,
        "user.fields":  USER_FIELDS,
        "start_time":   start_time,
        "exclude":      "retweets",          # skip RTs
    }

    data = _get(f"/users/{user_id}/tweets", params)
    if not data or "data" not in data:
        return [], []

    # Build a map of referenced tweet id → text (for reply context)
    ref_map = {}
    if "includes" in data and "tweets" in data["includes"]:
        for ref in data["includes"]["tweets"]:
            ref_map[ref["id"]] = ref.get("text", "")

    # Build author map from expansions (for reply question authors)
    user_map = {}
    if "includes" in data and "users" in data["includes"]:
        for u in data["includes"]["users"]:
            user_map[u["id"]] = u.get("username", "unknown")

    for tw in data["data"]:
        text       = tw.get("text", "").strip()
        tweet_id   = tw["id"]
        created_at = tw.get("created_at", "")
        date_s, date_d = _format_date(created_at)
        link = _tweet_url(username, tweet_id)

        refs = tw.get("referenced_tweets", [])
        replied_to_id   = tw.get("in_reply_to_user_id")
        is_reply_tweet  = any(r["type"] == "replied_to" for r in refs)

        if is_reply_tweet and replied_to_id and replied_to_id != user_id:
            # This is a reply to someone else — treat as Q&A
            # Find the original tweet text
            orig_id   = next((r["id"] for r in refs if r["type"] == "replied_to"), None)
            orig_text = ref_map.get(orig_id, "") if orig_id else ""
            q_author  = user_map.get(replied_to_id, "unknown")

            # Strip the leading @mention from the reply text
            answer = re.sub(r'^@\w+\s*', '', text).strip()

            if orig_text and len(answer) > 20:
                topics = detect_topics(orig_text + " " + answer)
                replies_out.append({
                    "replier":         username,
                    "question_author": q_author,
                    "question_text":   orig_text,
                    "answer_text":     answer,
                    "answer_link":     link,
                    "date_str":        date_s,
                    "date_display":    date_d,
                    "topics":          topics,
                })
            continue

        # Regular tweet (not a reply to someone else)
        if text.startswith("@"):
            continue   # skip @mentions that aren't captured as replies

        topics = detect_topics(text)
        tweets_out.append({
            "handle":       username,
            "text":         text,
            "link":         link,
            "date_str":     date_s,
            "date_display": date_d,
            "topics":       topics,
            "is_question":  is_question(text),
        })

    return tweets_out, replies_out


# ─────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────
def scrape_user(handle: str, verbose: bool = False) -> tuple:
    """Returns (tweets, replies) for one handle."""
    if verbose:
        print(f"  → @{handle}", flush=True)

    user_id = _get_user_id(handle)
    if not user_id:
        if verbose:
            print(f"    ⚠ could not find user @{handle}", flush=True)
        return [], []

    tweets, replies = _fetch_user_tweets(user_id, handle)
    if verbose:
        print(f"    ✓ {len(tweets)} tweets, {len(replies)} replies", flush=True)
    return tweets, replies


def scrape_all(verbose: bool = False) -> tuple:
    """Scrape all FOLLOWEES in parallel. Returns (all_tweets, all_replies)."""
    all_tweets, all_replies = [], []

    # 3 workers — avoid hammering Twitter API rate limits
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(scrape_user, h, verbose): h for h in FOLLOWEES}
        for future in as_completed(futures):
            try:
                t, r = future.result()
                all_tweets.extend(t)
                all_replies.extend(r)
            except Exception as e:
                if verbose:
                    print(f"  ⚠ {futures[future]}: {e}", flush=True)

    return all_tweets, all_replies
