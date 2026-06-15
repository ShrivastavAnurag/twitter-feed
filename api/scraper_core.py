"""
scraper_core.py  —  Twitter API v2 scraper
- Batch user ID lookup (1 API call for all users)
- Parallel tweet fetching (10 workers)
- 7-day window, 50 tweets per user
"""

import os
import re
import time
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import requests

# ─────────────────────────────────────────────
#  FOLLOWEES
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
#  TWITTER API v2 HELPERS
# ─────────────────────────────────────────────
API_BASE = "https://api.twitter.com/2"


def _headers() -> dict:
    token = os.environ.get("TWITTER_BEARER_TOKEN", "")
    if not token:
        raise RuntimeError("TWITTER_BEARER_TOKEN env var not set")
    return {"Authorization": f"Bearer {token}"}


def _get(path: str, params: dict, retries: int = 1) -> Optional[dict]:
    for attempt in range(retries + 1):
        try:
            r = requests.get(
                f"{API_BASE}{path}",
                headers=_headers(),
                params=params,
                timeout=20,
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                reset = int(r.headers.get("x-rate-limit-reset", time.time() + 16))
                wait  = min(max(reset - int(time.time()), 5), 30)
                print(f"  Rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"  HTTP {r.status_code} for {path}: {r.text[:150]}", flush=True)
        except Exception as e:
            print(f"  Request error: {e}", flush=True)
    return None


def _format_date(iso: str) -> tuple:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d"), dt.strftime("%d %b %Y")
    except Exception:
        return "", iso[:10]


# ─────────────────────────────────────────────
#  BATCH USER ID LOOKUP  (1 API call for all users)
# ─────────────────────────────────────────────
def _batch_user_ids(usernames: list) -> dict:
    """
    Returns { username_lower: user_id } for all found users.
    Twitter allows up to 100 usernames per request.
    """
    result = {}
    # Process in chunks of 100
    for i in range(0, len(usernames), 100):
        chunk = usernames[i:i+100]
        data  = _get("/users/by", {"usernames": ",".join(chunk), "user.fields": "id,username"})
        if data and "data" in data:
            for u in data["data"]:
                result[u["username"].lower()] = u["id"]
    return result


# ─────────────────────────────────────────────
#  TWEET FETCHING  (per user)
# ─────────────────────────────────────────────
def _fetch_tweets(user_id: str, username: str, verbose: bool = False) -> tuple:
    tweets_out, replies_out = [], []

    start_time = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = _get(f"/users/{user_id}/tweets", {
        "max_results":  MAX_TWEETS_PER_USER,
        "tweet.fields": "created_at,text,referenced_tweets,in_reply_to_user_id",
        "expansions":   "referenced_tweets.id,in_reply_to_user_id",
        "user.fields":  "username",
        "start_time":   start_time,
        "exclude":      "retweets",
    })

    if not data or "data" not in data:
        return [], []

    # Map referenced tweet id → text
    ref_map  = {t["id"]: t.get("text","") for t in data.get("includes",{}).get("tweets",[])}
    # Map user_id → username (for reply question authors)
    user_map = {u["id"]: u.get("username","unknown") for u in data.get("includes",{}).get("users",[])}

    for tw in data["data"]:
        text     = tw.get("text","").strip()
        tweet_id = tw["id"]
        date_s, date_d = _format_date(tw.get("created_at",""))
        link     = f"https://twitter.com/{username}/status/{tweet_id}"
        refs     = tw.get("referenced_tweets", [])
        replied_to_uid = tw.get("in_reply_to_user_id")
        is_reply = any(r["type"] == "replied_to" for r in refs)

        if is_reply and replied_to_uid and replied_to_uid != user_id:
            # Reply to someone else → Q&A pair
            orig_id   = next((r["id"] for r in refs if r["type"] == "replied_to"), None)
            orig_text = ref_map.get(orig_id, "") if orig_id else ""
            q_author  = user_map.get(replied_to_uid, "unknown")
            answer    = re.sub(r'^@\w+\s*', '', text).strip()
            if orig_text and len(answer) > 20:
                replies_out.append({
                    "replier":         username,
                    "question_author": q_author,
                    "question_text":   orig_text,
                    "answer_text":     answer,
                    "answer_link":     link,
                    "date_str":        date_s,
                    "date_display":    date_d,
                    "topics":          detect_topics(orig_text + " " + answer),
                })
            continue

        if text.startswith("@"):
            continue

        tweets_out.append({
            "handle":      username,
            "text":        text,
            "link":        link,
            "date_str":    date_s,
            "date_display":date_d,
            "topics":      detect_topics(text),
            "is_question": is_question(text),
        })

    if verbose:
        print(f"  @{username}: {len(tweets_out)} tweets, {len(replies_out)} replies", flush=True)

    return tweets_out, replies_out


# ─────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────
def scrape_user(handle: str, verbose: bool = False) -> tuple:
    uid_map = _batch_user_ids([handle])
    uid     = uid_map.get(handle.lower())
    if not uid:
        if verbose:
            print(f"  ⚠ @{handle} not found", flush=True)
        return [], []
    return _fetch_tweets(uid, handle, verbose)


def scrape_all(verbose: bool = False) -> tuple:
    """
    1. One batch API call to resolve all usernames → IDs
    2. Parallel tweet fetching with 10 workers
    """
    all_tweets, all_replies = [], []

    if verbose:
        print(f"Resolving {len(FOLLOWEES)} user IDs in one batch call…", flush=True)

    uid_map = _batch_user_ids(FOLLOWEES)

    if verbose:
        print(f"Found {len(uid_map)}/{len(FOLLOWEES)} users. Fetching tweets in parallel…", flush=True)

    def _fetch(handle):
        uid = uid_map.get(handle.lower())
        if not uid:
            return [], []
        return _fetch_tweets(uid, handle, verbose)

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch, h): h for h in FOLLOWEES}
        for future in as_completed(futures):
            try:
                t, r = future.result()
                all_tweets.extend(t)
                all_replies.extend(r)
            except Exception as e:
                if verbose:
                    print(f"  ⚠ {futures[future]}: {e}", flush=True)

    return all_tweets, all_replies
