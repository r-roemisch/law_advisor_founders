# ⚖️ Founder Legal Guide

**A RAG assistant that explains EU, German and US law to early-stage tech and AI founders, citing every source it uses.**

> [!WARNING]
> **Not legal advice.** The Founder Legal Guide gives general legal information only. It does not replace a consultation with a qualified lawyer.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-agents-1C3C3C)
![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-compose-2496ED?logo=docker&logoColor=white)

Founders ask about company formation, contracts, data protection, AI regulation, platform law, IP, employment, cybersecurity and fundraising. The guide answers from official legal texts and regulator guidance. Each answer:

- 📎 **cites** the provisions and guidance it relies on
- 🗓️ **shows the Legal Status** of each source (in force, applicable from a date, pending proposal, repealed)
- 🚨 **says when to talk to a lawyer**, for example on litigation, high-risk AI or international data transfers

Built as a Turing College bootcamp project.

---

## Contents

- [Features](#features)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Filling the knowledge base](#filling-the-knowledge-base)
- [Keeping it current](#keeping-it-current)
- [Evaluation](#evaluation)
- [MCP server](#mcp-server)
- [Extending it](#extending-it)
- [Tests](#tests)
- [Documentation](#documentation)

---

## Features

| | |
|---|---|
| **Knowledge base** | About 140 Sources: EU and German law in their official languages, US law, and regulator guidance |
| **Two Answering Modes** | *Single-pass* (search once, then answer) or *agentic* (the model decides what to search, possibly several times) |
| **11 Retrieval Strategies** | Different chunkers, embeddings, hybrid search, query rewriting and reranking, side by side for comparison |
| **4 Rule Checks** | AI Act risk classifier, applicability checker (GDPR, CCPA, COPPA, DSA, NIS2), compliance timeline, source currency check |
| **Founder Profile** | Stage, company seat, target markets and AI Role shape both retrieval and answers |
| **Multiple models** | Claude, GPT, Gemini and Mistral through OpenRouter, with token use and cost shown in the UI |
| **Live updates** | Daily re-check of every Source, with a public "What changed" feed and a review queue for web pages |
| **Safety** | Question check before every answer: Escalation Triggers, personal-data removal, tax-scope flag |
| **MCP server** | Rule Checks and corpus search available in Claude Desktop, Claude Code or an IDE |

---

## Quick start

**Requirements:** Docker with Compose. An [OpenRouter](https://openrouter.ai) API key for real answers.

```bash
git clone https://github.com/r-roemisch/law_advisor_founders.git
cd law_advisor_founders
cp .env.example .env          # add your OPENROUTER_API_KEY
docker compose up --build
```

Then open **http://localhost:3000**.

> [!TIP]
> **No API key?** Demo mode runs the whole app without a language model, on a small sample Corpus held in memory. Answers list the retrieved passages instead of a written answer.
>
> ```bash
> DEMO_MODE=1 docker compose up --build
> ```

<details>
<summary><b>Local development</b> (databases in Docker, apps on your machine)</summary>

Needs [uv](https://docs.astral.sh/uv/) and Node.js.

```bash
docker compose up -d postgres qdrant chroma
cd backend  && uv sync && uv run founder-legal-guide    # API on :8000
cd frontend && npm install && npm run dev              # UI on :3000
```

</details>

---

## How it works

```
 Next.js UI ──/api/*──▶ FastAPI backend ──▶ OpenRouter (Answer Model)
 (:3000)    ◀── SSE ──  (:8000)        │
                        LangGraph      ├──▶ Postgres + pgvector   default index, bookkeeping
                        Rule Checks    ├──▶ Qdrant                alternative index
                                       └──▶ Chroma                alternative index
```

| Part | Stack |
|---|---|
| `backend/` | Python, FastAPI, LangChain, LangGraph; models via OpenRouter ([ADR 0001](docs/adr/0001-python-fastapi-backend.md)) |
| `frontend/` | Next.js; `/api/*` is proxied to the backend, answers stream as server-sent events |
| Search index | Postgres + pgvector by default; Qdrant and Chroma are switchable alternatives ([ADR 0005](docs/adr/0005-switchable-search-index.md)) |
| `config/` | Editable YAML: Sources, Retrieval Strategies, models, Coverage Map, thresholds, Golden Set |

---

## Filling the knowledge base

The ingestion command reads [`config/sources.yaml`](config/sources.yaml), downloads each Source from its official site and indexes it into one or more Retrieval Strategies. Downloads are cached in `data/cache/`.

```bash
cd backend
uv run founder-legal-guide-ingest --dry-run                       # parse + chunk only; no API key needed
uv run founder-legal-guide-ingest --jurisdiction EU DE --tier 1   # embed into the default strategy (S1)
uv run founder-legal-guide-ingest --all-strategies                # every enabled strategy
uv run founder-legal-guide-ingest --source eu-gdpr --refresh      # one Source, bypassing the cache
```

In Docker: `docker compose run --rm backend uv run --no-dev founder-legal-guide-ingest --dry-run`

<details>
<summary><b>Source adapters</b></summary>

| Adapter | Fetches |
|---|---|
| `eurlex` | EU law from EUR-Lex (Publications Office) |
| `gii` | German law from gesetze-im-internet.de |
| `uscode` | US Code release points |
| `ecfr` | Electronic Code of Federal Regulations |
| `web_pinned`, `edpb`, `ec_digital` | Guidance and practical pages, HTML or PDF |

Web adapters honour `robots.txt` and machine-readable text-and-data-mining opt-outs ([ADR 0006](docs/adr/0006-tier-3-only-reusable-sources.md)). Sites that refuse automated access are marked `BLOCKED` in `sources.yaml`.

</details>

---

## Keeping it current

`founder-legal-guide-update` re-checks every Source. You can also start it in the UI under **What changed → Run update now** (requires `ADMIN_TOKEN`).

- Each section is fingerprinted. Unchanged text produces nothing, even if the version label moved.
- **Official texts** (`update: auto`) are re-indexed at once and recorded as *applied*.
- **Web pages** (`update: review`) are recorded as *review needed*. Approving indexes exactly the fetched text; rejecting keeps the old one.
- Every change becomes a **Change Record** in the public "What changed" feed, listing the sections added, removed or modified.

```bash
cd backend && uv run founder-legal-guide-update   # all Sources, all enabled strategies
ADMIN_TOKEN=… docker compose up -d                # enables the admin panel
```

In Docker the backend runs the update daily (`UPDATE_CRON`, default `0 3 * * *`) when an OpenRouter key is set.

> [!NOTE]
> The update run tracks what is indexed per Source, not per strategy. To fill a new or skipped strategy, run `founder-legal-guide-ingest --strategy <name>` once; the update run keeps it current from then on.

---

## Evaluation

The **Golden Set** ([`config/golden_set.yaml`](config/golden_set.yaml)) holds test questions, each with the passages it must retrieve and a reference answer. The judge model drafts it from real provisions sampled per Coverage Map cell; a person then reviews each item (`status: reviewed`).

```bash
cd backend
uv run founder-legal-guide-golden                                        # draft the Golden Set for review
uv run founder-legal-guide-eval retrieval                                # hit@k, recall, MRR per strategy
uv run founder-legal-guide-eval answers --strategy S1 --mode single_pass agentic
uv run founder-legal-guide-eval answers --model openai/gpt-6-sol mistralai/mistral-large-4-0
```

| Evaluation | Measures | Cost |
|---|---|---|
| `retrieval` | hit@k, recall, MRR | Low (embeddings only) |
| `answers` | Valid citations, expected passages cited, Escalation Triggers, tax referrals, latency, tokens | Runs the real chat pipeline |

Results are written to `data/eval/`.

---

## MCP server

The four Rule Checks and corpus search are also available as an MCP server. Every result carries the "not legal advice" statement.

```bash
cd backend && uv run founder-legal-guide-mcp               # stdio
cd backend && uv run founder-legal-guide-mcp --http 8765   # streamable HTTP at http://localhost:8765/mcp

# Add to Claude Code
claude mcp add founder-legal-guide -- uv --directory "$PWD/backend" run founder-legal-guide-mcp
```

Tools: `classify_ai_system_tool`, `check_applicability_tool`, `compliance_timeline_tool`, `check_source_currency_tool`, `search_corpus`.

---

## Extending it

Retrieval, models and answering can each be extended without touching the rest of the app ([ADR 0007](docs/adr/0007-extensible-answering-and-retrieval.md)):

| To add… | Do this |
|---|---|
| A Retrieval Strategy | Add an entry to [`config/strategies.yaml`](config/strategies.yaml) |
| A chunker, query transform, reranker or index backend | Write one class in `backend/src/founder_legal_guide/retrieval/`, register it by name (`@CHUNKERS.register("name")` etc.), reference it in `strategies.yaml` |
| An Answer Model | Add an OpenRouter model id to [`config/models.yaml`](config/models.yaml) |
| An Answering Mode | Write a LangGraph graph class in `answering/modes.py` and register it with `@ANSWERING_MODES.register("name")` |

Config is validated at startup: an unknown component name, or a search mode the backend doesn't support, fails loudly.

---

## Tests

```bash
cd backend
uv run pytest                                       # unit tests, no network

docker compose up -d postgres qdrant chroma
FLG_INTEGRATION=1 uv run pytest tests/integration   # backends against real databases
```

---

## Documentation

| File | Contents |
|---|---|
| [`CONTEXT.md`](CONTEXT.md) | Glossary of the project's terms (Source, Legal Status, Retrieval Strategy, Answering Mode, …) |
| [`docs/SCOPE.md`](docs/SCOPE.md) | Coverage: jurisdictions, Legal Areas, Escalation Triggers, Tier 3 policy |
| [`docs/archive/PLAN.md`](docs/archive/PLAN.md) | The original two-week build plan (archived) |
| [`docs/adr/`](docs/adr/) | Architecture decision records: why the big choices were made |

---

<sub>This is general legal information, not legal advice. It does not replace consultation with a qualified lawyer.</sub>
