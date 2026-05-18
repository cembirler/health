import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import agent, meta, sessions

load_dotenv()
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

app = FastAPI(title="Health Price Transparency API")

# Dev-only permissive CORS — tighten before public deploy
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# Agent function-calling surface (all data tools live here).
app.include_router(agent.router)

# Chat session persistence + server-owned agent runs.
app.include_router(sessions.router)

# Liveness probe (`/api/meta/health`) + caller info (`/api/meta/whoami`).
app.include_router(meta.router)
