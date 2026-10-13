# Founder Legal Guide

> **Not legal advice.** The Founder Legal Guide provides general legal information only. It does not replace consultation with a qualified lawyer.

A RAG assistant that gives early-stage tech and AI founders practical legal Guidance on EU, German and US law: company formation, contracts, data protection, AI regulation, platform law, IP, employment, cybersecurity and fundraising. Answers cite the law and official guidance they rely on, show each source's Legal Status, and say when to talk to a lawyer.

Turing College bootcamp project. Requirements: [`hard_requirements.txt`](hard_requirements.txt), [`soft_requirements.txt`](soft_requirements.txt).

## Documentation

| File | What it holds |
|---|---|
| [`CONTEXT.md`](CONTEXT.md) | Glossary: the project's terms (Source, Legal Status, Retrieval Strategy, Answering Mode, …) |
| [`docs/SCOPE.md`](docs/SCOPE.md) | What is covered: jurisdictions, Legal Areas, Escalation Triggers, Tier 3 policy |
| [`docs/PLAN.md`](docs/PLAN.md) | Two-week build plan and cut-line |
| [`docs/adr/`](docs/adr/) | Why the big decisions were made |
| [`config/`](config/) | Editable: Retrieval Strategies, models, Source Registry, Coverage Map |

## Quick start

```bash
cp .env.example .env          # add your OPENROUTER_API_KEY
docker compose up --build     # http://localhost:3000
```

No API key yet? Demo mode runs the whole app without a language model, using a small sample Corpus in memory. Answers only list the retrieved passages:

```bash
DEMO_MODE=1 docker compose up --build
```

For development, run the databases in docker and the apps locally:

```bash
docker compose up -d postgres qdrant chroma
cd backend && uv sync && uv run founder-legal-guide       # API on :8000
cd frontend && npm install && npm run dev                 # UI on :3000
```

## Filling the knowledge base

The ingestion command reads [`config/sources.yaml`](config/sources.yaml), downloads each Source from its official site (EUR-Lex via the Publications Office, gesetze-im-internet.de), and indexes it into one or more Retrieval Strategies. Downloads are cached in `data/cache/`.

```bash
cd backend
uv run founder-legal-guide-ingest --dry-run                        # parse + chunk only, shows volume; no key needed
uv run founder-legal-guide-ingest --jurisdiction EU DE --tier 1    # embed into the default strategy (S1)
uv run founder-legal-guide-ingest --all-strategies                 # every enabled strategy
uv run founder-legal-guide-ingest --source eu-gdpr --refresh       # one Source, bypassing the cache
```

Inside docker: `docker compose run --rm backend uv run --no-dev founder-legal-guide-ingest --dry-run`.

Adapters: `eurlex` (EU law), `gii` (German law), `uscode` (US Code release points), `ecfr` (eCFR), and `web_pinned` / `edpb` / `ec_digital` (guidance and practical pages, HTML or PDF). Web adapters honour robots.txt and machine-readable text-and-data-mining opt-outs (ADR 0006). Sites that refuse automated access are marked `BLOCKED` in `sources.yaml`.

## Keeping it current

`founder-legal-guide-update` (or **What changed → Run update now** in the UI, with `ADMIN_TOKEN`) re-checks every Source:

- Each section is fingerprinted. Unchanged text produces nothing, even if the version label moved.
- Changed official texts (`update: auto`) are re-indexed at once and recorded as **applied**.
- Changed web pages (`update: review`) are recorded as **review needed** with the fetched text; approving indexes exactly that text, rejecting keeps the old one.
- Every change becomes a Change Record in the public **What changed** feed, listing the sections added, removed or modified.

The update run tracks what is indexed per Source, not per strategy. To fill a strategy that is new or was skipped, run `founder-legal-guide-ingest --strategy <name>` (a full rebuild); the update run then keeps it current.

In docker the backend runs this daily (`UPDATE_CRON`, default `0 3 * * *`) when an OpenRouter key is set.

```bash
cd backend && uv run founder-legal-guide-update                   # all Sources, all enabled strategies
ADMIN_TOKEN=… docker compose up -d                                # enables the admin panel
```

## Evaluation

The **Golden Set** (`config/golden_set.yaml`) holds test questions, each with the passages it must retrieve and a reference answer. It is drafted by the judge model from real provisions sampled per Coverage Map cell, then **reviewed by a person** (`status: reviewed`).

```bash
cd backend
uv run founder-legal-guide-golden                                   # draft the Golden Set for review
uv run founder-legal-guide-eval retrieval                           # hit@k, recall, MRR for every enabled strategy
uv run founder-legal-guide-eval answers --strategy S1 --mode single_pass agentic
uv run founder-legal-guide-eval answers --model openai/gpt-6-sol mistralai/mistral-large-4-0
```

Retrieval evaluation is cheap (embeddings only). Answer evaluation runs the real chat pipeline and checks valid citations, whether the expected passages were cited, Escalation Triggers and tax referrals, latency and tokens. Results go to `data/eval/`.

## MCP server

The four Rule Checks and corpus search are also an MCP server, usable from Claude Desktop, Claude Code or an IDE. Every result carries the "not legal advice" statement.

```bash
cd backend && uv run founder-legal-guide-mcp              # stdio
cd backend && uv run founder-legal-guide-mcp --http 8765  # streamable HTTP at http://localhost:8765/mcp
claude mcp add founder-legal-guide -- uv --directory "$PWD/backend" run founder-legal-guide-mcp   # Claude Code
```

Tools: `classify_ai_system_tool`, `check_applicability_tool`, `compliance_timeline_tool`, `check_source_currency_tool`, `search_corpus`.

## Architecture

- **backend/**: Python, FastAPI, LangChain and LangGraph, with models via OpenRouter (ADR 0001)
- **frontend/**: Next.js; `/api/*` is proxied to the backend and answers stream as server-sent events
- **Postgres + pgvector**: the default search index plus bookkeeping data. **Qdrant** and **Chroma** are alternative index backends (ADR 0005).

Three things are designed to be extended without touching the rest of the app (ADR 0007):

| To add… | Do this |
|---|---|
| A Retrieval Strategy | Add an entry to `config/strategies.yaml` |
| A chunker, query transform, reranker or index backend | Write one class, register it by name (`@CHUNKERS.register("name")` etc. in `backend/src/founder_legal_guide/retrieval/`), reference it in `strategies.yaml` |
| An Answer Model | Add an OpenRouter model id to `config/models.yaml` |
| An Answering Mode | Write a LangGraph graph class in `answering/modes.py` and register it with `@ANSWERING_MODES.register("name")` |

Config is validated at startup. An unknown component name or a search mode that the backend doesn't support fails loudly.

## Tests

```bash
cd backend
uv run pytest                                             # unit tests, no network
docker compose up -d postgres qdrant chroma
FLG_INTEGRATION=1 uv run pytest tests/integration         # backends against real databases
```

---

_This is general legal information, not legal advice. It does not replace consultation with a qualified lawyer._
