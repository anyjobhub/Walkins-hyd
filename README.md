# Walk-in Jobs Aggregation System

A production-ready job aggregation platform that scrapes walk-in interviews from **Naukri**, **LinkedIn RSS**, and **Indeed RSS**, stores them in PostgreSQL, broadcasts via a Telegram bot, and displays on a Next.js website.

---

## 🏗 Project Structure

```
walkins/
├── backend/           # Python Flask API + scraper engine
├── frontend/          # Next.js 14 website
├── database/          # PostgreSQL schema
├── docker-compose.yml # Full stack local development
├── Procfile           # Render.com deployment
└── .env.example       # Environment variable template
```

---

## 🚀 Quick Start

### 1. Prerequisites

```bash
# Install Python 3.11+, Node.js 20+, PostgreSQL 15+
sudo apt install python3.11 postgresql nodejs
```

### 2. Clone and configure

```bash
git clone <your-repo>
cd walkins
cp .env.example .env
# Edit .env and fill in your DATABASE_URL, TELEGRAM_BOT_TOKEN, etc.
```

### 3. Set up the database

```bash
# Create DB
createdb walkins_db

# Apply schema
psql walkins_db < database/schema.sql
```

### 4. Run the backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

Backend runs at **http://localhost:5000**

### 5. Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at **http://localhost:3000**

---

## 🐳 Docker (Recommended)

```bash
# Copy and configure env
cp .env.example .env
# Edit .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f backend
```

---

## 🤖 Telegram Bot Setup

1. Message [@BotFather](https://t.me/BotFather) on Telegram
2. Send `/newbot` and follow the prompts
3. Copy the token to `TELEGRAM_BOT_TOKEN` in `.env`
4. Create a channel/group and add your bot as admin
5. Get the channel ID (forward a message to @userinfobot)
6. Set `TELEGRAM_CHANNEL_ID` in `.env`
7. Run the bot: `python backend/telegram_bot_handler.py`

### Bot Commands
| Command | Description |
|---|---|
| `/start` | Subscribe to notifications |
| `/stop` | Unsubscribe |
| `/jobs` | Recent jobs |
| `/walkin` | Walk-in only |
| `/fresher` | Fresher-friendly only |
| `/filter Mumbai` | Filter by city |
| `/stats` | System statistics |

---

## 🌐 API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/jobs` | List jobs (with filters) |
| GET | `/api/jobs/:id` | Single job |
| GET | `/api/jobs/search?q=` | Search |
| GET | `/api/jobs/walkin` | Walk-in jobs |
| GET | `/api/stats` | System statistics |
| GET | `/health` | Health check |
| POST | `/api/scraper/trigger` | Trigger scrape (admin) |
| GET | `/api/admin/dashboard` | Full dashboard (admin) |

**Admin routes** require `X-API-Key: <ADMIN_API_KEY>` header.

---

## ⚙️ Scheduler

| Task | Schedule |
|---|---|
| Naukri scraper | Every 4 hours |
| LinkedIn RSS | Every 6 hours |
| Indeed RSS | Every 6 hours |
| Telegram posting | Every 15 minutes |
| Daily digest | 9:00 AM IST |
| Deduplication | 3:00 AM IST daily |
| Job cleanup | Sunday 2:00 AM IST |

---

## ☁️ Deploying to Render

1. Connect GitHub repo to Render
2. Create **Web Service** → Python → `cd backend && gunicorn "app:create_app()"`
3. Create **Background Worker** → `python backend/telegram_bot_handler.py`
4. Create **PostgreSQL** database and add its URL to env vars
5. Add all `.env` variables in Render's Environment tab
6. Deploy frontend to **Vercel** → set `NEXT_PUBLIC_API_URL` to your Render backend URL

---

## ⚖️ Compliance Notes

- Naukri scraper uses **2-4 second delays** and respects `robots.txt`
- LinkedIn and Indeed use **public RSS feeds** (no HTML scraping)
- Max 20 requests/minute rate limiting
- Review each site's Terms of Service before production deployment
- For high-volume use, consider official APIs

---

## 🧪 Testing

```bash
cd backend
python -m pytest tests/ -v

# Test single scraper manually
python -c "
from scrapers.naukri_scraper import NaukriScraper
s = NaukriScraper()
jobs = s.scrape_jobs(location='Mumbai', max_pages=1)
print(f'Found {len(jobs)} jobs')
"

# Trigger scrape via API
curl -X POST http://localhost:5000/api/scraper/trigger \
  -H "X-API-Key: your_admin_key" \
  -H "Content-Type: application/json" \
  -d '{"sources": ["indeed"], "location": "India"}'
```
