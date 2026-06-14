"""
scraper_core.py  —  shared scraping logic used by both api/scrape.py and local runner
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
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

NITTER_INSTANCES = [
    "https://nitter.poast.org",
    "https://nitter.net",
    "https://nitter.1d4.us",
    "https://nitter.kavin.rocks",
    "https://nitter.it",
    "https://n.l5.ca",
    "https://nitter.privacydev.net",
]

MAX_TWEETS_PER_USER = 40

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

AT_START = re.compile(r'^@\w+')
REPLY_RE = re.compile(r'^R to @(\w+):\s*(.*)', re.DOTALL)


def detect_topics(text: str) -> list:
    found = [t for t, p in TOPIC_RULES if re.search(p, text, re.IGNORECASE)]
    return found or ["General Tech"]


def is_question(text: str) -> bool:
    return bool(QUESTION_RE.search(text)) or detect_topics(text) != ["General Tech"]


# ─────────────────────────────────────────────
#  HTTP + RSS HELPERS
# ─────────────────────────────────────────────
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
    "Accept": "application/rss+xml,application/xml,text/xml,*/*",
}


def _nitter_to_twitter(link: str) -> str:
    link = link.replace("nitter.net", "twitter.com")
    for inst in NITTER_INSTANCES:
        domain = inst.replace("https://", "").replace("http://", "")
        link = link.replace(domain, "twitter.com")
    return link


def _fetch_rss(handle: str, instance: str, with_replies: bool = False) -> Optional[str]:
    suffix = "/with_replies" if with_replies else ""
    url = f"{instance}/{handle}{suffix}/rss"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=12)
        if r.status_code == 200 and "<rss" in r.text:
            return r.text
    except Exception:
        pass
    return None


def _parse_date(item) -> tuple:
    s = item.findtext("pubDate", "").strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S +0000"):
        try:
            d = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return d.strftime("%Y-%m-%d"), d.strftime("%d %b %Y")
        except ValueError:
            pass
    return "", s[:16] if s else "Unknown"


def _clean(html_text: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html_text)
    return re.sub(r"\s+", " ", t).strip()


def _item_text(item) -> str:
    title = item.findtext("title", "").strip()
    desc  = _clean(item.findtext("description", ""))
    return desc if len(desc) > len(title) else title


# ─────────────────────────────────────────────
#  PARSERS
# ─────────────────────────────────────────────
def _parse_tweets(xml_text: str, handle: str) -> list:
    out = []
    try:
        root    = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item")[:MAX_TWEETS_PER_USER]:
            text = _item_text(item)
            if text.startswith("RT @") or AT_START.match(text):
                continue
            link       = _nitter_to_twitter(item.findtext("link", "").strip())
            date_s, date_d = _parse_date(item)
            out.append({
                "handle":       handle,
                "text":         text,
                "link":         link,
                "date_str":     date_s,
                "date_display": date_d,
                "topics":       detect_topics(text),
                "is_question":  is_question(text),
            })
    except ET.ParseError:
        pass
    return out


def _parse_replies(xml_text: str, replier: str) -> list:
    out = []
    try:
        root    = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []
        for item in channel.findall("item")[:MAX_TWEETS_PER_USER]:
            title = item.findtext("title", "").strip()
            m = REPLY_RE.match(title)
            if not m:
                continue
            q_author = m.group(1)
            q_text   = m.group(2).strip()
            if q_author.lower() == replier.lower():
                continue                         # skip self-replies
            answer = re.sub(r'^@\w+\s*', '', _clean(item.findtext("description", ""))).strip()
            if len(answer) < 20:
                continue
            link       = _nitter_to_twitter(item.findtext("link", "").strip())
            date_s, date_d = _parse_date(item)
            topics = detect_topics(q_text + " " + answer)
            out.append({
                "replier":         replier,
                "question_author": q_author,
                "question_text":   q_text,
                "answer_text":     answer,
                "answer_link":     link,
                "date_str":        date_s,
                "date_display":    date_d,
                "topics":          topics,
            })
    except ET.ParseError:
        pass
    return out


# ─────────────────────────────────────────────
#  PUBLIC API
# ─────────────────────────────────────────────
def scrape_user(handle: str, verbose: bool = False) -> tuple:
    """Returns (tweets, replies) for one handle."""
    tweets, replies = [], []
    for instance in NITTER_INSTANCES:
        if verbose:
            print(f"  {instance} / @{handle} ...", end=" ", flush=True)
        # tweets
        xml = _fetch_rss(handle, instance, with_replies=False)
        if xml:
            tweets = _parse_tweets(xml, handle)
            if verbose:
                print(f"✓ {len(tweets)} tweets", end="  ")
        # replies (same instance — avoids re-negotiating a working one)
        xml_r = _fetch_rss(handle, instance, with_replies=True)
        if xml_r:
            replies = _parse_replies(xml_r, handle)
            if verbose:
                print(f"✓ {len(replies)} replies", end="")
        if verbose:
            print()
        if tweets or replies:
            break
        time.sleep(0.4)
    if verbose and not tweets and not replies:
        print(f"  ⚠  could not reach any Nitter instance for @{handle}")
    return tweets, replies


def scrape_all(verbose: bool = False) -> tuple:
    """Scrape all FOLLOWEES in parallel. Returns (all_tweets, all_replies)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_tweets, all_replies = [], []

    def _scrape(handle):
        if verbose:
            print(f"→ @{handle}", flush=True)
        return scrape_user(handle, verbose=verbose)

    # 5 workers — enough parallelism without hammering Nitter
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_scrape, h): h for h in FOLLOWEES}
        for future in as_completed(futures):
            try:
                t, r = future.result()
                all_tweets.extend(t)
                all_replies.extend(r)
            except Exception as e:
                if verbose:
                    print(f"  ⚠ {futures[future]}: {e}", flush=True)

    return all_tweets, all_replies
