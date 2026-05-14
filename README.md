<div align="center">

```
███╗   ██╗███████╗██╗  ██╗ ██████╗ ██████╗  █████╗
████╗  ██║██╔════╝╚██╗██╔╝██╔═══██╗██╔══██╗██╔══██╗
██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║██████╔╝███████║
██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║██╔══██╗██╔══██║
██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝██║  ██║██║  ██║
╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝
```

**Ask anything about any codebase. Get the exact file, the exact line, every time.**

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Groq](https://img.shields.io/badge/LLM-Llama_3.3_70B-F55036?style=flat-square)](https://groq.com)
[![License](https://img.shields.io/badge/License-MIT-green?style=flat-square)](LICENSE)

</div>

---

## What is Nexora?

Nexora is an AI-powered codebase intelligence engine. Paste any public GitHub URL — Nexora indexes the entire repo using AST parsing and a structured code graph, then lets you ask natural language questions and get answers with **exact precision**.

Not summaries. Not guesses. The actual file path and line number.

```
You:     where is JWT validation handled?

Nexora:  Found in auth/jwt.py at line 47

         def validate_token(token: str) -> dict:
             payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
             return payload

         Called by → auth_middleware  (middleware.py : 23)
                    → login_required  (decorators.py  : 8)
```

---

## Why it works differently

Most AI code tools use **text similarity search** — they convert your code to embeddings, find the closest match, and ask an LLM to guess. That is why they say *"it might be in the auth folder"* instead of *"auth/jwt.py line 47"*.

Nexora uses a **two-layer intelligence system**:

**Layer 1 — AST Code Graph (Precision)**
Every function, class, call relationship, and import is extracted using Abstract Syntax Tree parsing — the same technique compilers use. All symbols are stored in a structured SQLite graph database. Location queries are direct database lookups, not similarity searches. This is why the answers are always exact.

**Layer 2 — Vector Search (Context)**
For broad questions like *"explain the architecture"*, semantic search over code chunks provides the right context. This layer handles nuance where exact lookup is too narrow.

The combination means precise answers when you ask *where*, and intelligent answers when you ask *how* or *why*.

---

## Features

| Question | What Nexora returns |
|---|---|
| `where is redact_text defined` | Exact file + line number |
| `what does process_payment do` | Purpose, source code, parameters |
| `how does authentication work` | Step-by-step with full call chain |
| `trace the flow of file upload` | End-to-end execution across every file |
| `what calls validate_token` | Every caller, every file, every line |
| `what uses upload-zone` | Every import and reference in the codebase |
| `how many tsx files are there` | Exact count + complete list |
| `what functions are in app.py` | Every symbol with line numbers |
| `explain the architecture` | Full technical overview with data flow |
| `list all classes` | Complete codebase inventory |

Supported languages: **Python · TypeScript · JavaScript · React (TSX/JSX) · Java · Go · Rust · Ruby · PHP · C# · C/C++**

---

## Tech Stack

```
Backend          FastAPI + Python 3.11
AST Parsing      Built-in ast module (Python) + Regex patterns (JS/TS)
Code Graph       SQLite — symbols, calls, imports, file summaries
Vector Store     ChromaDB 0.5
Embeddings       sentence-transformers (all-MiniLM-L6-v2) — runs locally
LLM              Groq API — Llama 3.3 70B (free tier)
Repo Cloning     GitPython
Frontend         Vanilla HTML/CSS/JS — zero dependencies
```

Everything except the LLM runs **locally on your machine**. No data is sent anywhere except the final question to Groq's API.

---

## Project Structure

```
Nexora/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── repo.py          # POST /api/process-repo
│   │   │   ├── query.py         # POST /api/ask
│   │   │   └── status.py        # GET  /api/status/{repo_id}
│   │   ├── core/
│   │   │   ├── ast_parser.py    # AST extraction for Python + JS/TS
│   │   │   ├── code_graph.py    # SQLite code graph — symbols & relationships
│   │   │   ├── query_engine.py  # 11-type question classifier + handlers
│   │   │   ├── groq_client.py   # LLM prompting with developer persona
│   │   │   ├── chunker.py       # File chunking + skip logic
│   │   │   ├── embedder.py      # Local sentence-transformers
│   │   │   ├── vector_store.py  # ChromaDB wrapper
│   │   │   ├── github.py        # Repo cloning + nested root detection
│   │   │   └── repo_intel.py    # File importance scoring
│   │   ├── workers/
│   │   │   └── indexer.py       # Background indexing pipeline
│   │   └── main.py              # FastAPI app entry point
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    └── index.html               # Full UI — dark theme, 3-panel layout
```

---

## Running Locally

**Prerequisites:** Python 3.11+, Git

**1. Clone the repo**
```bash
git clone https://github.com/shivaa-palaniyappan/Nexora.git
cd Nexora
```

**2. Set up the backend**
```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**3. Add your Groq API key**

Get a free key at [console.groq.com](https://console.groq.com) — takes 30 seconds, no credit card.

```bash
cp .env.example .env
# Open .env and add your key:
# GROQ_API_KEY=gsk_your_key_here
```

**4. Start the backend**
```bash
uvicorn app.main:app --reload --port 8000
```

**5. Open the frontend**

Open `frontend/index.html` directly in your browser — no build step, no npm, no setup.

**6. Index a repo and start asking**

Paste any GitHub URL in the input field, click Process, wait for indexing to complete, then ask anything.

---

## How Indexing Works

When you submit a GitHub URL:

1. **Clone** — The repo is cloned locally using GitPython. Nested repo structures are auto-detected.
2. **Parse** — Every `.py`, `.ts`, `.tsx`, `.js`, `.jsx` file is parsed with AST extraction. Functions, classes, imports, and call relationships are extracted.
3. **Graph** — All symbols are stored in a SQLite code graph with relationship edges between callers and callees.
4. **Embed** — Code chunks are embedded using a local sentence-transformers model and stored in ChromaDB.
5. **Ready** — The repo is queryable. All subsequent questions hit the graph database first, then the vector store for additional context.

Indexing a medium-sized repo (~500 files) takes 2-5 minutes. After that, every question is answered in seconds.

---

## Question Types

Nexora classifies every question into one of 11 types and routes it to a dedicated handler:

| Type | Trigger phrases | Handler |
|---|---|---|
| WHERE | "where is X defined" | Exact symbol lookup in code graph |
| WHAT | "what does X do" | Symbol lookup + source extraction |
| HOW | "how does X work" | Vector search + call chain |
| EXPLAIN | "explain the architecture" | Repo map + top symbols overview |
| TRACE | "trace the flow of X" | 4-level deep call chain traversal |
| CALLS | "what calls X" | Reverse lookup in calls table |
| CALLED_BY | "what does X call" | Forward lookup in calls table |
| USES | "what uses X" | Cross-file import + reference search |
| STATS | "how many tsx files" | Aggregation queries on graph DB |
| FILE | "functions in app.py" | All symbols in a specific file |
| LIST | "list all classes" | Full symbol inventory query |

---

## Environment Variables

```bash
GROQ_API_KEY=gsk_...          # Required — get free at console.groq.com
CHROMA_PATH=./data/chroma     # ChromaDB storage location
DB_PATH=./data/jobs.db        # Job tracking database
CLONE_DIR=./data/repos        # Temporary clone directory
GRAPH_DB_PATH=./data/code_graph.db   # AST code graph database
ANONYMIZED_TELEMETRY=False    # Disable ChromaDB telemetry
```

---

## Built by

**Shiva Palaniyappan**

Nexora was conceived, designed, and built from scratch — every parsing decision, every query type, every layer of the architecture. The two-layer intelligence system (AST graph + vector search) was designed specifically to solve the precision problem that makes existing AI code tools frustrating to use.

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Connect-0077B5?style=flat-square&logo=linkedin)](https://www.linkedin.com/in/shivaa-palaniyappan-3545b6297/)

---

*If Nexora impressed you, a ⭐ means everything.*
