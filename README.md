# Tech Interview Feed — Vercel Deploy Guide

A daily-refreshing feed of technical interview tweets and Q&A replies
from your Twitter followees, deployed on Vercel with KV storage.

---

## Project Structure

```
twitter-feed/
├── api/
│   ├── scraper_core.py   # shared scraping logic (edit FOLLOWEES here)
│   ├── scrape.py         # cron endpoint  →  GET /api/scrape
│   └── tweets.py         # data endpoint  →  GET /api/tweets
├── public/
│   └── index.html        # frontend SPA
├── vercel.json           # cron schedule + routing
├── requirements.txt      # Python dependencies
└── README.md
```

---

## Deploy Steps

### 1 — Push to GitHub
```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/twitter-feed.git
git push -u origin main
```

### 2 — Create Vercel project
1. Go to [vercel.com](https://vercel.com) → **Add New → Project**
2. Import your GitHub repo
3. Framework: **Other**
4. Root directory: `.` (default)
5. Click **Deploy**

### 3 — Create Vercel KV store
1. Vercel dashboard → your project → **Storage** tab
2. Click **Create Database** → choose **KV**
3. Name it anything (e.g. `interview-feed-kv`)
4. Click **Connect** — this auto-adds the env vars below

### 4 — Set environment variables
Go to **Settings → Environment Variables** and add:

| Variable              | Value                              |
|-----------------------|------------------------------------|
| `KV_REST_API_URL`     | auto-added when you connect KV     |
| `KV_REST_API_TOKEN`   | auto-added when you connect KV     |
| `CRON_SECRET`         | any random string you choose e.g. `mys3cr3t42` |

### 5 — Trigger first scrape
After deploy, visit:
```
https://your-app.vercel.app/api/scrape
```
Add the header `Authorization: Bearer <your CRON_SECRET>` — or temporarily
remove the CRON_SECRET env var for the first run, then re-add it.

Easiest first-time trigger via curl:
```bash
curl -H "Authorization: Bearer mys3cr3t42" \
     https://your-app.vercel.app/api/scrape
```

From then on, Vercel cron runs it automatically every day at **00:00 UTC**.

---

## Adding / Removing Followees

Edit `api/scraper_core.py`:
```python
FOLLOWEES = [
    "tiwarisuhani_11",
    "krunalbuilds",
    # add more handles here
]
```
Commit + push → Vercel auto-redeploys. Trigger `/api/scrape` once to refresh data.

---

## Cron Schedule

Defined in `vercel.json`:
```json
{
  "crons": [{ "path": "/api/scrape", "schedule": "0 0 * * *" }]
}
```
`0 0 * * *` = every day at 00:00 UTC.
Change to `0 18 * * *` for 11:30 PM IST (18:00 UTC = 23:30 IST).

---

## Local Testing

```bash
pip install requests beautifulsoup4 upstash-redis

# Test scraping (prints to console, no KV needed)
python3 - <<'EOF'
import sys; sys.path.insert(0, 'api')
from scraper_core import scrape_all
tweets, replies = scrape_all(verbose=True)
print(f"\n{len(tweets)} tweets, {len(replies)} replies")
EOF
```

---

## Nitter Instances

If scraping returns 0 results, Nitter instances may be down.
Check https://status.d420.de/ for live Nitter status.
Add working instances to the `NITTER_INSTANCES` list in `scraper_core.py`.
