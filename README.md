# healthpricetransparency.com

Consumer hospital price search powered by a Gemma 4 agent over Hospital Price
Transparency (HPT) data.

- `apps/api` — FastAPI backend + bundled agent loop (Python, `uv` workspace).
  The agent module lives at `apps/api/agent/` — the same
  code powers the chat path AND the optional terminal REPL.
- `apps/web` — React + Vite frontend (TypeScript, npm workspace)
- `packages/db` — SQLAlchemy models + Alembic migrations (installed editable by `apps/api`)

---

## 1. Prerequisites

Install these once on your machine:

| Tool | Version | Install (macOS) |
| --- | --- | --- |
| Python | ≥ 3.11 | `brew install python@3.12` |
| [uv](https://docs.astral.sh/uv/) | latest | `brew install uv` |
| Node.js | ≥ 20 | `brew install node` |
| MySQL | 8.x | `brew install mysql@8.0 && brew services start mysql@8.0` |

### Create the local database

Alembic can build the schema but can't create the database or user itself, so
run this once:

```bash
mysql -u root <<'SQL'
CREATE DATABASE IF NOT EXISTS health CHARACTER SET utf8mb4;
CREATE USER IF NOT EXISTS 'health'@'127.0.0.1' IDENTIFIED BY 'health_dev';
GRANT ALL ON health.* TO 'health'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
```

Then apply the migrations (this creates all tables):

```bash
uv run --project packages/db alembic -c packages/db/alembic.ini upgrade head
```

---

## 2. Configure your `.env`

Create a `.env` file at the repo root (it is git-ignored). Only
`GOOGLE_API_KEY` is required for local dev — the other variables have
sensible defaults baked into the code.

```bash
# REQUIRED. Google AI Studio key for the model. Get one at
# https://aistudio.google.com/app/apikey
GOOGLE_API_KEY=your_key_here

# OPTIONAL. The model id the agent talks to (any Google AI Studio model
# id is valid). Defaults to gemma-4-26b-a4b-it (A4B mixture-of-experts,
# ~4B active params). Other useful values: gemma-4-31b-it (bigger Gemma)
# or gemini-flash-latest (much higher rate limits, but not Gemma).
MODEL=gemma-4-26b-a4b-it

# OPTIONAL. MySQL connection string. The default below is also the
# code's built-in fallback, so you can skip this line entirely as long
# as you followed the "Create the local database" SQL above.
# DATABASE_URL=mysql+pymysql://health:health_dev@127.0.0.1:3306/health?charset=utf8mb4
```

Both Python entry points ([apps/api/main.py](apps/api/main.py) and
[apps/api/agent/cli.py](apps/api/agent/cli.py)) call `load_dotenv()` and read
from this single file.

---

## 3. Install dependencies

```bash
# Python — resolves apps/api (which bundles the agent) and packages/db
uv sync --project apps/api

# JavaScript — npm workspaces install the web app
npm install
```

---

## 4. Run the app

Open two terminals from the repo root:

```bash
# Terminal 1 — backend (Python) on http://localhost:8000
uv run --project apps/api uvicorn main:app --reload --app-dir apps/api --port 8000
```

```bash
# Terminal 2 — frontend (Node) on http://localhost:5173
npm run web
```

The Vite dev server proxies `/api/*` to the backend (see
[apps/web/vite.config.ts](apps/web/vite.config.ts)), so open
**http://localhost:5173** and you're done.

### Other useful commands

```bash
npm run build:web                                     # production bundle in apps/web/dist
uv run --project apps/api python -m agent.cli         # chat with the agent in your terminal
```

---

## 5. Troubleshooting

- **`GOOGLE_API_KEY` missing** — the backend boots but `/api/sessions/.../messages`
  returns 500. Check that `.env` lives at the repo root, not inside `apps/api`.
- **`Can't connect to MySQL`** — confirm `brew services list` shows
  `mysql@8.0` as `started` and that the credentials in `DATABASE_URL` match
  the user you created above.
- **Empty results in the UI** — migrations created the schema but no data was
  loaded. Ingestion of MRF files is a separate pipeline; see
  [docs/](docs/README.md) and `.claude/skills/ingest-mrf/` for the rule book.
- **Port already in use** — pass `--port` to override the API
  (`uv run --project apps/api uvicorn main:app --reload --app-dir apps/api --port 8001`)
  and update the proxy `target` in [apps/web/vite.config.ts](apps/web/vite.config.ts).
