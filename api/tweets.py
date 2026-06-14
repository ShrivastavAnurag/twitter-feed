"""
api/tweets.py
-------------
Serves stored tweets, replies, and metadata from Vercel KV to the frontend.

GET /api/tweets          → { tweets: [...], replies: [...], meta: {...} }

If KV is empty (first deploy, KV not yet populated) it returns mock data
so the UI is never blank — and includes a  "is_mock": true  flag so the
frontend can show a "Run scraper first" banner.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(__file__))

from upstash_redis import Redis   # noqa: E402

KV_TWEETS_KEY  = "tweets"
KV_REPLIES_KEY = "replies"
KV_META_KEY    = "meta"


def _get_redis() -> Redis:
    return Redis(
        url=os.environ["KV_REST_API_URL"],
        token=os.environ["KV_REST_API_TOKEN"],
    )


def _days_ago(n: int) -> tuple:
    """Return (YYYY-MM-DD, DD Mon YYYY) for n days ago."""
    d = datetime.now(timezone.utc) - timedelta(days=n)
    return d.strftime("%Y-%m-%d"), d.strftime("%d %b %Y")


def _mock_data() -> tuple:
    """Fallback mock data using today-relative dates."""
    tweets = [
        {"handle": "tiwarisuhani_11", "text": "What is the difference between HashMap and ConcurrentHashMap in Java? HashMap is not thread-safe. ConcurrentHashMap uses CAS operations (Java 8+) for thread safety without locking the whole map.", "link": "https://twitter.com/tiwarisuhani_11/status/mock1", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["Java / JVM", "Data Structures"], "is_question": True},
        {"handle": "tiwarisuhani_11", "text": "Difference between == and .equals() in Java. == checks reference equality. .equals() checks value equality. Always use .equals() for String comparison.", "link": "https://twitter.com/tiwarisuhani_11/status/mock2", "date_str": _days_ago(2)[0], "date_display": _days_ago(2)[1], "topics": ["Java / JVM"], "is_question": True},
        {"handle": "tanujDE3180", "text": "How does indexing work in databases? An index is a B-Tree storing column values + row pointers. Speeds up SELECT but slows INSERT/UPDATE. Composite indexes follow left-prefix rule.", "link": "https://twitter.com/tanujDE3180/status/mock3", "date_str": _days_ago(0)[0], "date_display": _days_ago(0)[1], "topics": ["Databases"], "is_question": True},
        {"handle": "tanujDE3180", "text": "What is N+1 query problem? Fetching N records then 1 query per record = N+1 total. Fix: use JOIN, eager loading, or DataLoader. Very common in ORM-heavy apps.", "link": "https://twitter.com/tanujDE3180/status/mock4", "date_str": _days_ago(3)[0], "date_display": _days_ago(3)[1], "topics": ["Databases"], "is_question": True},
        {"handle": "javarevisited", "text": "Difference between ArrayList and LinkedList? ArrayList: O(1) random access, O(n) insert in middle. LinkedList: O(n) access, O(1) insert at known position. Use ArrayList for most cases — better cache locality.", "link": "https://twitter.com/javarevisited/status/mock5", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["Data Structures", "Java / JVM"], "is_question": True},
        {"handle": "javarevisited", "text": "Difference between abstract class and interface in Java? Abstract class: can have state + constructors, single inheritance. Interface: no state, multiple inheritance. Use interface to define contracts.", "link": "https://twitter.com/javarevisited/status/mock6", "date_str": _days_ago(4)[0], "date_display": _days_ago(4)[1], "topics": ["Java / JVM", "Object-Oriented"], "is_question": True},
        {"handle": "ashoKumar89", "text": "How would you design a notification system at scale? Components: event ingestion → Kafka → notification workers → push/email/SMS channels. Fan-out on write vs fan-out on read trade-off is critical.", "link": "https://twitter.com/ashoKumar89/status/mock7", "date_str": _days_ago(0)[0], "date_display": _days_ago(0)[1], "topics": ["System Design"], "is_question": True},
        {"handle": "ashoKumar89", "text": "Vertical vs horizontal scaling? Vertical: more CPU/RAM, simple but hardware-limited. Horizontal: more machines, complex but unlimited. Modern systems: horizontal + stateless services + load balancer.", "link": "https://twitter.com/ashoKumar89/status/mock8", "date_str": _days_ago(5)[0], "date_display": _days_ago(5)[1], "topics": ["System Design"], "is_question": True},
        {"handle": "krunalbuilds", "text": "Explain the JavaScript event loop. JS is single-threaded. Call stack runs sync code. Web APIs handle async. Microtasks (Promises) drain before macrotasks (setTimeout). This order matters for interview questions!", "link": "https://twitter.com/krunalbuilds/status/mock9", "date_str": _days_ago(2)[0], "date_display": _days_ago(2)[1], "topics": ["JavaScript / Web"], "is_question": True},
        {"handle": "krunalbuilds", "text": "What is closure in JavaScript? A function that remembers variables from its outer scope after the outer function returns. Enables data privacy, factory functions, memoization.", "link": "https://twitter.com/krunalbuilds/status/mock10", "date_str": _days_ago(6)[0], "date_display": _days_ago(6)[1], "topics": ["JavaScript / Web"], "is_question": True},
        {"handle": "devXritesh", "text": "REST vs gRPC? REST: HTTP/1.1, JSON, human-readable. gRPC: HTTP/2, Protocol Buffers, faster + smaller payload, streaming. REST for public APIs. gRPC for internal microservices.", "link": "https://twitter.com/devXritesh/status/mock11", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["Networking", "System Design"], "is_question": True},
        {"handle": "devXritesh", "text": "How does Docker work? Containers use Linux namespaces (isolation) and cgroups (resource limits). Images are layered filesystems (UnionFS). Container ≠ VM — shares host kernel.", "link": "https://twitter.com/devXritesh/status/mock12", "date_str": _days_ago(7)[0], "date_display": _days_ago(7)[1], "topics": ["Cloud / DevOps", "Operating Systems"], "is_question": True},
        {"handle": "system_monarch", "text": "How would you design Twitter's timeline? Fan-out on write for normal users, fan-out on read for celebrities. Twitter uses both — hybrid approach based on follower count threshold.", "link": "https://twitter.com/system_monarch/status/mock13", "date_str": _days_ago(0)[0], "date_display": _days_ago(0)[1], "topics": ["System Design"], "is_question": True},
        {"handle": "system_monarch", "text": "Consistent hashing explained. Normal hashing: adding a server remaps most keys. Consistent hashing: only K/N keys move. Used in Cassandra, DynamoDB, Varnish.", "link": "https://twitter.com/system_monarch/status/mock14", "date_str": _days_ago(3)[0], "date_display": _days_ago(3)[1], "topics": ["System Design", "Algorithms"], "is_question": True},
        {"handle": "Its_Nova1012", "text": "Deadlock prevention strategies: 1) Lock ordering 2) Timeout-based locks 3) tryLock() 4) Avoid nested locks. Deadlock requires 4 conditions: Mutual Exclusion + Hold & Wait + No Preemption + Circular Wait.", "link": "https://twitter.com/Its_Nova1012/status/mock15", "date_str": _days_ago(2)[0], "date_display": _days_ago(2)[1], "topics": ["Operating Systems"], "is_question": True},
        {"handle": "SidJain_80", "text": "SOLID principles explained: Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion. Violating these leads to brittle untestable code.", "link": "https://twitter.com/SidJain_80/status/mock16", "date_str": _days_ago(4)[0], "date_display": _days_ago(4)[1], "topics": ["Object-Oriented"], "is_question": True},
        {"handle": "0xlelouch_", "text": "How does HTTPS work? 1) TLS ClientHello 2) Server cert + public key 3) Client verifies via CA chain 4) Key exchange (ECDHE) → session key 5) Symmetric encryption from here. Asymmetric only bootstraps the handshake.", "link": "https://twitter.com/0xlelouch_/status/mock17", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["Networking", "Security"], "is_question": True},
        {"handle": "0xlelouch_", "text": "Race condition: two threads access shared data and outcome depends on execution order. Fix: mutex/locks, atomic operations, or immutable data.", "link": "https://twitter.com/0xlelouch_/status/mock18", "date_str": _days_ago(5)[0], "date_display": _days_ago(5)[1], "topics": ["Operating Systems"], "is_question": True},
    ]
    replies = [
        {"replier": "krunalbuilds", "question_author": "devchallenger99", "question_text": "Can someone explain null vs undefined in JavaScript? Keeps tripping me up in interviews.", "answer_text": "null = intentional absence, set by developer. undefined = variable declared but not assigned. typeof null is 'object' (JS historical bug). typeof undefined is 'undefined'. Rule: use null to explicitly clear a value.", "answer_link": "https://twitter.com/krunalbuilds/status/r_mock1", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["JavaScript / Web"]},
        {"replier": "krunalbuilds", "question_author": "jslearner_aman", "question_text": "Promise.all() vs Promise.allSettled() — when do I use which?", "answer_text": "Promise.all() fails fast — rejects if ANY promise rejects. Use when you need ALL results. Promise.allSettled() waits for everything, returns {status, value/reason} for each. Use for batch calls where some may fail.", "answer_link": "https://twitter.com/krunalbuilds/status/r_mock2", "date_str": _days_ago(2)[0], "date_display": _days_ago(2)[1], "topics": ["JavaScript / Web"]},
        {"replier": "system_monarch", "question_author": "swe_aspirant", "question_text": "In system design interviews, how do I decide SQL vs NoSQL?", "answer_text": "4 questions: 1) Need ACID? → SQL. 2) Schema changing fast? → NoSQL. 3) Need complex JOINs? → SQL. 4) Horizontal write scale to billions? → NoSQL. Most real systems use both: SQL for transactions, NoSQL for activity feeds.", "answer_link": "https://twitter.com/system_monarch/status/r_mock3", "date_str": _days_ago(0)[0], "date_display": _days_ago(0)[1], "topics": ["System Design", "Databases"]},
        {"replier": "system_monarch", "question_author": "backenddev_rk", "question_text": "Why avoid distributed transactions? Can't I just use 2PC in microservices?", "answer_text": "2PC problems: coordinator is single point of failure, locks held across network = very slow, if coordinator dies mid-commit system gets stuck. Use Saga pattern instead — local transactions + compensating actions. Accept eventual consistency.", "answer_link": "https://twitter.com/system_monarch/status/r_mock4", "date_str": _days_ago(3)[0], "date_display": _days_ago(3)[1], "topics": ["System Design", "Databases"]},
        {"replier": "tanujDE3180", "question_author": "sqlnoob_prakash", "question_text": "Difference between WHERE and HAVING in SQL? Both seem to filter rows?", "answer_text": "WHERE filters BEFORE grouping (works on rows). HAVING filters AFTER grouping (works on aggregates). Example: WHERE salary > 50k removes employees first, HAVING COUNT(*) > 5 removes groups with too few remaining.", "answer_link": "https://twitter.com/tanujDE3180/status/r_mock5", "date_str": _days_ago(4)[0], "date_display": _days_ago(4)[1], "topics": ["Databases"]},
        {"replier": "javarevisited", "question_author": "javabeginner_dev", "question_text": "Checked vs unchecked exceptions in Java — when to use which?", "answer_text": "Checked (IOException, SQLException) — compiler forces handle/declare. For recoverable conditions. Unchecked (RuntimeException, NPE) — compiler doesn't enforce. For programming bugs. Rule: checked if caller can reasonably recover, unchecked for bugs.", "answer_link": "https://twitter.com/javarevisited/status/r_mock6", "date_str": _days_ago(2)[0], "date_display": _days_ago(2)[1], "topics": ["Java / JVM"]},
        {"replier": "devXritesh", "question_author": "devops_learner", "question_text": "Docker vs Kubernetes — what's the relationship?", "answer_text": "Docker = shipping container (packages your app). Kubernetes = the port/logistics system (decides where containers go, restarts failed ones, scales). Docker Compose for dev. K8s for production at scale.", "answer_link": "https://twitter.com/devXritesh/status/r_mock7", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["Cloud / DevOps"]},
        {"replier": "Its_Nova1012", "question_author": "cs_student_mh", "question_text": "Why do we need virtual memory if we already have RAM?", "answer_text": "Virtual memory gives each process the illusion of owning the full address space. Benefits: isolation (process A can't read B's memory), more space than physical RAM (via disk swap), simpler programming. OS + MMU translate virtual → physical via page tables.", "answer_link": "https://twitter.com/Its_Nova1012/status/r_mock8", "date_str": _days_ago(5)[0], "date_display": _days_ago(5)[1], "topics": ["Operating Systems"]},
        {"replier": "SidJain_80", "question_author": "oop_confused", "question_text": "Composition vs inheritance — when should I prefer composition?", "answer_text": "Inheritance = 'is-a'. Composition = 'has-a'. Prefer composition when: you want reuse without tight coupling, the relationship isn't truly is-a, you need to change behaviour at runtime. Favour composition over inheritance (GoF). Inheritance leaks implementation details.", "answer_link": "https://twitter.com/SidJain_80/status/r_mock9", "date_str": _days_ago(3)[0], "date_display": _days_ago(3)[1], "topics": ["Object-Oriented"]},
        {"replier": "0xlelouch_", "question_author": "security_fresher", "question_text": "Symmetric vs asymmetric encryption — which does HTTPS use?", "answer_text": "Symmetric: same key to encrypt/decrypt. Fast. Problem: key sharing. Asymmetric: public encrypts, private decrypts. Slow but solves key-sharing. HTTPS uses BOTH — asymmetric (ECDHE) during TLS handshake, then symmetric (AES) for data. Best of both.", "answer_link": "https://twitter.com/0xlelouch_/status/r_mock10", "date_str": _days_ago(0)[0], "date_display": _days_ago(0)[1], "topics": ["Security", "Networking"]},
        {"replier": "tiwarisuhani_11", "question_author": "java_intern_neha", "question_text": "String vs StringBuilder vs StringBuffer in Java — which is fastest?", "answer_text": "String: immutable, every concat creates new object, slowest for loops. StringBuilder: mutable, NOT thread-safe, fastest for single thread. StringBuffer: mutable, synchronized, slower than StringBuilder. Use StringBuilder in loops, String for constants.", "answer_link": "https://twitter.com/tiwarisuhani_11/status/r_mock11", "date_str": _days_ago(1)[0], "date_display": _days_ago(1)[1], "topics": ["Java / JVM"]},
        {"replier": "ashoKumar89", "question_author": "sde_prep_2024", "question_text": "How detailed should my system design answer be? Interviewers keep saying 'go deeper'.", "answer_text": "Structure: 1) Clarify requirements + scale (5 min) 2) High-level boxes+arrows 3) Deep dive on 2-3 hardest components. Go deeper means: pick the DB layer → talk sharding strategy, indexing, replication lag. Show you've thought about failure modes and trade-offs.", "answer_link": "https://twitter.com/ashoKumar89/status/r_mock12", "date_str": _days_ago(2)[0], "date_display": _days_ago(2)[1], "topics": ["System Design", "Interview Tips"]},
    ]
    return tweets, replies


class handler(BaseHTTPRequestHandler):

    def do_GET(self):  # noqa: N802
        try:
            kv = _get_redis()
            raw_t = kv.get(KV_TWEETS_KEY)
            raw_r = kv.get(KV_REPLIES_KEY)
            raw_m = kv.get(KV_META_KEY)

            if raw_t and raw_r:
                tweets  = json.loads(raw_t)
                replies = json.loads(raw_r)
                meta    = json.loads(raw_m) if raw_m else {}
                is_mock = False
            else:
                tweets, replies = _mock_data()
                meta    = {"note": "KV empty — showing demo data. Trigger /api/scrape to populate."}
                is_mock = True

            payload = json.dumps({
                "tweets":  tweets,
                "replies": replies,
                "meta":    meta,
                "is_mock": is_mock,
            }).encode()

        except Exception as exc:
            payload = json.dumps({"error": str(exc)}).encode()

        self.send_response(200)
        self.send_header("Content-Type",                 "application/json")
        self.send_header("Content-Length",               str(len(payload)))
        self.send_header("Access-Control-Allow-Origin",  "*")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass
