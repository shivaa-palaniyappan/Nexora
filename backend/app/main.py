from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import repo, query, status
from app.core.database import init_db
from app.core.code_graph import init_graph_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_graph_db()   # initialize the AST code graph DB
    yield


app = FastAPI(
    title="Codebase Agent API — AST Powered",
    description="Precise code Q&A using AST parsing + code graph",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(repo.router,   prefix="/api", tags=["Repository"])
app.include_router(query.router,  prefix="/api", tags=["Query"])
app.include_router(status.router, prefix="/api", tags=["Status"])


@app.get("/")
def root():
    return {"status": "ok", "message": "CodeAgent v2 — AST powered"}


@app.get("/health")
def health():
    return {"status": "healthy"}
