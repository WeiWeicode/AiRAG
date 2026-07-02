# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Required reading before making changes

This project has its own AI agent conduct policy at [AGENT.md](AGENT.md) (Traditional Chinese) — read it first. Its core rules, summarized:

1. **Think before acting** — state your understanding/plan in 1-3 sentences before writing code; ask when requirements are ambiguous instead of guessing.
2. **Simplicity first** — solve only the stated problem; no speculative abstractions, patterns, or "might need later" code.
3. **Surgical edits** — touch only what the task requires; don't reformat, rename, or "clean up" unrelated code.
4. **Goal-oriented execution** — define done up front, iterate to completion without stopping at every step, report blockers explicitly.
5. **Respect existing conventions** — match the style of the file/directory you're editing rather than introducing your own (see table below).
6. **Fail loudly** — report errors and failures explicitly; never silently swallow exceptions (`try/except: pass`) or delete failing tests to make things "pass".

It also requires logging every change in `docs/DevelopmentProcess/`:
- `BugFix.md` — bug fixes
- `NewFeatures.md` — new features
- `FrontendCorrection.md` — frontend changes
- `BackendCorrection.md` — backend changes

The user tests manually — do not open a browser to verify changes yourself.

Deeper project docs (read the relevant one before working in that area — note some content is aspirational/ahead of actual code, see Known doc/code drift below):
- `docs/01_RPD.md` — product requirements / acceptance criteria
- `docs/02_ARCHITECTURE.md` — system architecture
- `docs/03_API_CONTRACT.md` — API endpoint definitions
- `docs/04_DB_SCHEMA.md` — MongoDB / SQL Server / Qdrant schema
- `docs/05_ACCEPTANCE.md` — acceptance checklist
- `docs/06_API_TESTING_GUIDE.md`, `docs/CodeHybridSearchNote.md`, `docs/DeploymentTroubleshooting.md`

## Code conventions

| Item | Convention |
|:---|:---|
| Frontend framework | Vue 3 Composition API (`<script setup>`) |
| Frontend styling | Tailwind CSS |
| Backend framework | Python FastAPI |
| Backend naming | functions/variables `snake_case`, classes `PascalCase` |
| API paths | `/api/{module}/{action}`, lowercase, hyphen-separated |
| MongoDB ODM | beanie (Document models) |
| Comments | Traditional Chinese or English, consistent within a file |

## Tech stack

| Layer | Technology |
|:---|:---|
| Frontend | Vue 3 + Vite + Tailwind CSS + Pinia |
| Backend | Python FastAPI |
| App database | MongoDB (motor + beanie) |
| Existing knowledge base | SQL Server (read-only, pyodbc) + Oracle (read-only, oracledb) |
| Vector database | Qdrant (dense + sparse, hybrid/RRF search) |
| LLM | vLLM — Qwen3.6-35B-A3B-FP8 |
| Embedding | llama.cpp — Qwen3-Embedding-8B-Q8_0.gguf |
| Deployment | Docker + Docker Compose |

## Commands

There is no root package manager script — frontend and backend are run/built independently.

**Backend** (`backend/`, Python venv at `backend/.venv`):
```
cd backend
uvicorn main:app --reload --port 53020   # dev server
```
No linter/formatter is configured. No pytest config exists (no `pytest.ini`/`conftest.py`); tests use `unittest.IsolatedAsyncioTestCase` and manually manipulate `sys.path` to import backend modules — run individual files directly, e.g. `python backend/tests/test_word_chunker.py`. Only one test file lives under version control (`backend/tests/`); a larger local-only set lives in the git-ignored root `tests/`.

**Frontend** (`frontend/`):
```
cd frontend
npm run dev       # Vite dev server
npm run build     # production build -> frontend/dist
npm run preview   # preview production build
```
No `lint` or `test` script is defined, and no ESLint/Prettier config exists.

**Full stack (Docker)**:
```
docker-compose up --build -d
```
Services: `backend` (port 53020), `mongodb` (mongo:7, 27017), `qdrant` (6333/6334), `frontend` (nginx:alpine serving `frontend/dist`, port 53010, proxies `/api` and `/health` to backend — see root `nginx.conf`). Backend `Dockerfile` bundles Oracle Instant Client + unixODBC/FreeTDS for SQL Server/Oracle connectivity.

Backend config comes from `backend/.env` (git-ignored, no `.env.example` exists) via `backend/config.py`, e.g. `VLLM_BASE_URL`/`VLLM_MODEL`, `LLAMACPP_BASE_URL`/`EMBEDDING_MODEL`, `DenseVector_LLAMACPP_BASE_URL`/`DenseVector_INSTRUCT_MODEL`, `QDRANT_HOST`/`QDRANT_PORT`, `MONGODB_URL`/`MONGODB_DATABASE`, `SQLSERVER_CONNECTION_STRING`, plus RAG defaults (`DEFAULT_TOP_K`, `DEFAULT_SCORE_THRESHOLD`, `DEFAULT_CHUNK_SIZE`, `DEFAULT_CHUNK_OVERLAP`).

## Architecture

Layered flow: Vue 3 SPA → FastAPI routers (all mounted under `/api`) → services → data access (MongoDB via motor/beanie, SQL Server/Oracle read-only, Qdrant dual-vector) → external inference services (vLLM, two llama.cpp instances).

**Signature pipeline — "semantic hybrid search" / Two-Step Hybrid Retrieval** (used by `/api/rag/chat`, `/api/retrieval/search`, `/api/retrieval/semantic-hybrid-search`, `/api/evaluation/run` when `search_type=semantic_hybrid`):
1. Fetch the knowledge base's structured map via `QdrantService.get_unique_metadata()` — filenames, tags, and each file's `links_to` relations.
2. Local Instruct LLM (Qwen3VL-8B-Instruct) parses the query into structured JSON `{embeddings_input, sparse_keywords}`, with the structured map injected into its prompt and strict anti-hallucination rules (don't invent context beyond what's asked).
3. `embeddings_input` → llama.cpp dense embedding (4096-dim); `sparse_keywords` → fastembed/SPLADE sparse vector.
4. **1st-hop**: Qdrant prefetch (dense + sparse) fused via RRF → core points.
5. **2nd-hop**: if any core point carries a `links_to` payload field, Qdrant does a second filtered hybrid search restricted to those linked filenames/ids (with `score_threshold` applied, `neighbor_limit` default 10) — this replaced an earlier unfiltered `scroll` that diluted context (see `docs/DevelopmentProcess/BugFix.md` 2026-07-01).
6. Neighbor results are deduped by `parent_id`, merged with `get_siblings_and_merge`, combined with the 1st-hop results, and content-deduped.
7. Reranked context is fed to vLLM (Qwen3.6-35B-A3B-FP8) to generate the answer.
8. The whole flow streams to the frontend via SSE with step events (actual field names are `step`/`status`/`content`, not `event`/`detail`): `semantic_analysis` → `vector_search` → `llm_thinking` → `conclusion`, followed by `chunk` events (`type: reasoning|content|done`) and one `sources` event.

`vector` and `hybrid` search types only do the 1st-hop (`search_similar`), not the two-step neighbor expansion. Full endpoint-by-endpoint contract now lives in `docs/03_API_CONTRACT.md` (recently corrected against actual code — several endpoints previously documented as JSON were actually SSE, and `/api/prompt/generate` plus `/api/rag/history` are stubs, not real implementations).

External services and ports: vLLM `:8000/v1/chat/completions`, llama.cpp embedding `:8081/embedding`, llama.cpp instruct `:8082/v1/chat/completions`, Qdrant `:6333`, MongoDB `:27017`, SQL Server (ODBC), Oracle (thin TCP).

**Backend layout** (`backend/`):
- `main.py` — FastAPI app ("AiRAG Testbed API"), `lifespan` initializes MongoDB, CORS wide open (dev), all routers under `/api`, `/health` unauthenticated.
- `routers/` — one file per feature area, all require `Depends(get_current_user)` except `auth.py`: `auth`, `embedding` (upload/chunk/vectorize/tags/classes), `knowledge_base`, `rag` (SSE chat + history), `retrieval` (vector/hybrid/semantic-hybrid search, query-transform, point deletion), `evaluation` (dataset CRUD + RAG eval runs), `prompt` (manual-context chat, A/B test, templates), `feedback`, `sqlserver` (read-only import), `database_indexing` (external DB connection CRUD + ingest for SQL Server/Oracle).
- `models/` — beanie Document models (one per collection/entity).
- `schemas/` — Pydantic request/response schemas for `auth`, `database_indexing`, `embedding`, `knowledge_base`, `retrieval`, `sqlserver`; note `rag`/`evaluation`/`feedback` schemas are defined inline in their routers rather than in `schemas/`.
- `services/` — RAG/chunking pipeline: `chunking_service`, `document_parser`, `embedding_service` (llama.cpp client), `llm_service` (vLLM/OpenAI-compatible client), `qdrant_service` (RRF hybrid search, point deletion), `sparse_embedding_service` (fastembed/SPLADE), plus `parent_child_chunker` / `word_parent_child_chunker` / `markdown_parent_child_chunker` for structured document chunking.
- `utils/security.py` — bcrypt hashing + JWT (`verify_password`, `create_access_token`, `get_current_user`).

**Frontend layout** (`frontend/src/`):
- `views/` — one per route: Login, Dashboard, RagTest, RetrievalTest, Evaluation, PromptTest, EmbeddingTest, Feedback.
- `router/index.js` — all routes except `/login` require `requiresAuth: true`; nav guard checks `authStore.isAuthenticated` and redirects to `/login`.
- `components/chat/`, `components/embedding/`, `components/eval/`, `components/params/`, `components/common/` — grouped by feature.
- `stores/` — Pinia: `authStore`, `chatStore`, `feedbackStore`, `paramsStore`.
- `services/` — axios API clients (`api.js` + one per feature area) — this is the real API layer.
- `vite.config.js` has no dev-server proxy or path aliases; API base URL is set directly in `services/api.js`.

## Known doc/code drift

- `docs/02_ARCHITECTURE.md`, `03_API_CONTRACT.md`, and `04_DB_SCHEMA.md` were corrected against actual code on 2026-07-02 (previous versions referenced a non-existent `middleware/` dir and several services, and had multiple wrong API response shapes/missing endpoints). Keep them in sync when touching routers/models/schemas — re-verify rather than trusting doc prose blindly, since it can drift again.
- `frontend/src/components/API/` is a parallel/legacy set of API modules that duplicates `frontend/src/services/`. Treat `services/` as the real API layer unless told otherwise.
- Several endpoints are stubs, not real implementations: `GET/DELETE /api/rag/history*` (always returns empty / no-op), `POST /api/prompt/generate` (returns a static stub message, ignores its request). Don't build features that assume these work.
