# CodeAgent — Ask your codebase anything

A web app that lets anyone ask questions about any GitHub repository.
100% free. Powered by Groq + Llama 3.3 70B + ChromaDB.

---

## Project structure

```
codeagent/
├── backend/
│   ├── app/
│   │   ├── main.py              ← FastAPI server entry point
│   │   ├── api/
│   │   │   ├── repo.py          ← POST /api/process-repo
│   │   │   ├── query.py         ← POST /api/ask
│   │   │   └── status.py        ← GET  /api/status/{repo_id}
│   │   ├── core/
│   │   │   ├── database.py      ← SQLite job tracking
│   │   │   ├── embedder.py      ← Local sentence-transformers
│   │   │   ├── vector_store.py  ← ChromaDB wrapper
│   │   │   ├── chunker.py       ← File → overlapping chunks
│   │   │   ├── github.py        ← Clone + walk repo files
│   │   │   └── groq_client.py   ← Groq API calls
│   │   └── workers/
│   │       └── indexer.py       ← Background indexing pipeline
│   ├── requirements.txt
│   ├── render.yaml              ← Render deployment config
│   └── .env.example
└── frontend/
    └── index.html               ← Complete single-file React-less frontend
```

---

## PART 1 — Run locally first (test on your machine)

### Prerequisites
- Python 3.11+
- Git installed
- Groq API key (free at console.groq.com)

### Step 1 — Set up the backend

Open a terminal in the `backend/` folder:

```bash
cd backend

# Create virtual environment (sandbox)
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install all dependencies
pip install -r requirements.txt
```

### Step 2 — Create your .env file

```bash
cp .env.example .env
```

Open `.env` and set your Groq key:
```
GROQ_API_KEY=gsk_your_actual_key_here
```

### Step 3 — Start the backend server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

You should see:
```
INFO: Uvicorn running on http://0.0.0.0:8000
```

### Step 4 — Open the frontend

Open `frontend/index.html` in your browser.
The page will connect to `http://localhost:8000` automatically.

### Step 5 — Test it

1. Paste a GitHub URL: `https://github.com/torvalds/linux` (or any repo)
2. Click **Process** — watch the progress bar
3. Once complete, select the repo in Step 2
4. Ask a question like "Where is memory management handled?"

---

## PART 2 — Deploy to Render (free, public URL)

Render gives you a free backend server with a public URL.
Free tier: 750 hours/month (enough for 24/7 if you only have one service).

### Step 1 — Push your code to GitHub

```bash
# In the project root
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/codeagent.git
git push -u origin main
```

### Step 2 — Create Render account

Go to render.com → Sign up free with GitHub.

### Step 3 — Create a new Web Service

1. Click **"New +"** → **"Web Service"**
2. Connect your GitHub repo
3. Fill in these settings:

| Setting | Value |
|---|---|
| Name | codeagent-backend |
| Region | Oregon (US West) |
| Branch | main |
| Root Directory | backend |
| Runtime | Python 3 |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Plan | **Free** |

4. Under **Environment Variables**, add:
   - `GROQ_API_KEY` = your Groq key
   - `CHROMA_PATH` = `/tmp/chroma`
   - `DB_PATH` = `/tmp/jobs.db`
   - `CLONE_DIR` = `/tmp/repos`

5. Click **Create Web Service**

Render will build and deploy in ~3 minutes.
You'll get a URL like: `https://codeagent-backend.onrender.com`

### Step 4 — Update frontend with Render URL

Open `frontend/index.html` and find this line (~line 260):
```javascript
: 'https://YOUR-RENDER-APP.onrender.com';
```

Replace with your actual Render URL:
```javascript
: 'https://codeagent-backend.onrender.com';
```

### Step 5 — Deploy the frontend

**Option A — GitHub Pages (free, easiest):**
1. Push your code (with updated frontend) to GitHub
2. Go to repo Settings → Pages
3. Source: Deploy from branch → main → /frontend folder
4. Your frontend is live at: `https://YOUR_USERNAME.github.io/codeagent`

**Option B — Netlify (free, drag & drop):**
1. Go to netlify.com → Sign up free
2. Drag the `frontend/` folder onto the Netlify dashboard
3. Done — instant public URL

**Option C — Vercel (free):**
1. Go to vercel.com → Import your GitHub repo
2. Set root directory to `frontend`
3. Deploy

---

## API Reference

### POST /api/process-repo
Submit a GitHub repo for indexing.
```json
Request:  { "github_url": "https://github.com/owner/repo" }
Response: { "repo_id": "owner-repo-abc123", "status": "pending" }
```

### GET /api/status/{repo_id}
Poll this every 2 seconds to track progress.
```json
{
  "status": "indexing",
  "total_files": 1200,
  "processed_files": 340,
  "failed_files": 2,
  "progress_pct": 28,
  "chunks_indexed": 4821
}
```

### POST /api/ask
Ask a question about an indexed repo.
```json
Request:  { "repo_id": "owner-repo-abc123", "question": "Where is auth?" }
Response: { "answer": "Authentication is handled in...", "sources": [...] }
```

### GET /api/repos
List all repos.

---

## Important notes for Render free tier

- **Sleep after 15 min inactivity**: Free tier servers sleep when not used.
  First request after sleep takes ~30 seconds to wake up.
  Solution: upgrade to Starter ($7/mo) or use uptimerobot.com to ping it.

- **Ephemeral storage**: `/tmp` resets on deploy. Indexed repos are lost on redeploy.
  Users need to re-index. For persistence, upgrade to a paid disk mount.

- **512MB RAM**: Enough for small-medium repos. Very large repos (5000+ files)
  may hit memory limits. The batch processing handles this gracefully.

---

## Troubleshooting

**"Model not found" error** — Make sure GROQ_API_KEY is set correctly.

**Indexing stuck at "cloning"** — The repo URL might be private or invalid.
Only public GitHub repos are supported.

**"No chunks found"** — The repo may have only binary files or unsupported types.
Try a code-heavy repo.

**Frontend can't reach backend** — Check the API_BASE URL in index.html
matches your Render URL exactly (no trailing slash).
