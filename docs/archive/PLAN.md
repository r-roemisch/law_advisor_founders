# Build Plan

> **Not legal advice.** The Founder Legal Guide provides general legal information only. It does not replace consultation with a qualified lawyer.

Two weeks at about 6 hours a day. The hard requirements are complete by day 6. Everything after that is extra, ordered so that cutting from the end loses the least.

Terms are defined in [`CONTEXT.md`](../../CONTEXT.md), scope in [`SCOPE.md`](../SCOPE.md), and the reasons for big decisions in [`adr/`](../adr/).

## Status (2026-10-12)

Done:
- **Days 1–3:** skeleton, plug-in registry, the two Answering Modes (single-pass and agentic), all 11 Retrieval Strategies in config, chat UI, demo mode, OpenRouter request-format tests, and the EUR-Lex and gesetze-im-internet importers. The ingestion command parses 72 documents (26 EU acts in EN and DE, 20 German laws) into 7,876 passages.
- **Day 6:** agentic mode, done early.
- **Days 4–5:**
  - Four Rule Checks as tools: AI Act risk classifier, applicability checker (GDPR, CCPA, COPPA, DSA, NIS2), compliance timeline, live source check. Dates come from `sources.yaml`; thresholds from `config/thresholds.yaml`.
  - A question check before every answer: Escalation Triggers, removal of personal data, tax-scope flag.
  - Founder Profile questionnaire. Tool results visualised in the UI.

- **Days 7–8:**
  - Adapters for US Code, eCFR, and HTML/PDF web pages (robots and TDM opt-outs honoured).
  - Update run with per-section fingerprints and Change Records (*applied* / *review needed* / *approved* / *rejected*).
  - Admin update with live progress, review queue, daily schedule, "What changed" feed.
  - Live check of all 148 Sources: 133 fetch with stable fingerprints. 12 are refused by their sites (California and Colorado legislatures, FTC blog, EUIPO, DPF; marked BLOCKED). 3 were transient errors, now retried.

- **Days 9–14 (in progress):**
  - Corpus live in S1: 136 Sources, 9,571 passages. Strategies share indexes by chunker + embedding (11 strategies, 8 indexes).
  - Tier weights rank official law above practical pages (Q7).
  - Golden Set drafted (53 items), waiting for review.
  - Retrieval evaluation runs. RAGAs-style metrics implemented in-house (ragas 0.4.3 is incompatible with langchain-community 0.4).
  - MCP server with 5 tools.
  - Request log with cost and Gap Signals; admin dashboard.
  - Rate limiting; conversation history and export (JSON / Markdown / CSV / PDF via print).

Open:
- The 12 BLOCKED Sources need another official source or a manual snapshot.
- Golden Set review (you), then headline evaluation on reviewed items only.
- Embedding the Corpus needs `OPENROUTER_API_KEY`.

## Days

| Days | Work | Requirement coverage |
|---|---|---|
| 1–2 | Repo skeleton: docker-compose (Postgres+pgvector, Qdrant, Chroma), FastAPI, Next.js. Plug-in registry and `config/strategies.yaml` / `config/models.yaml`. Draft of the Source Registry and Coverage Map (**for your review**). | Tech implementation |
| 2–3 | EUR-Lex and gesetze-im-internet adapters, structure-aware chunking, S1 index. `search_corpus` tool. Single-pass Answering Mode (LangGraph). Chat UI with streaming, citations, progress indicators, disclaimer everywhere. | RAG, UI |
| 4–5 | Tools: AI Act risk classifier, applicability checker, compliance timeline, live source check. Escalation Triggers. Input validation, injection defence, citation check, personal-data warning. Founder Profile questionnaire. Answer Model picker. | Tools, domain, security, multi-model |
| 6 | **Agentic Answering Mode** (second LangGraph graph reusing `search_corpus` and the tools). Mode picker in UI. | Agentic RAG |
| 7–8 | US federal adapters (eCFR, Federal Register, US Code); pinned state and agency sources with *review needed*. Write the US "other states" privacy-law summary table from the states' official sites. Legal Status, Change Records, daily scheduler, refresh button, "What changed" feed. Tier 3 sources. | Automated and real-time KB updates |
| 9–10 | Golden Set (LLM-drafted, **you review ~2–3 h**). RAGAs and citation accuracy. Strategies S2–S8 and the embedding variants. Evaluation runs record strategy × mode × model. | RAG evaluation, A/B testing, hybrid search |
| 11–12 | MCP server for the 4 tools and `search_corpus`. Coverage and Gap dashboard with request logs and costs. | MCP, analytics, logging, token costs |
| 13–14 | Conversation history and export (JSON/MD/PDF), "how this answer was found" panel, interactive help, rate limiting. README, demo script, buffer. | Easy items, rate limiting |

## Cut-line

If behind schedule, drop in this order (first = first to go):

1. S5 (Chroma)
2. Texas and Colorado sources
3. S4 and S4-oai-large (Qdrant)
4. MCP server
5. S6–S8
6. Dashboard beyond coverage and costs
7. PDF export

Agentic mode, model switching and the extension points are core and are not on the cut-line.
