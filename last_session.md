# Last session: summary and next steps

> **Not legal advice.** The Founder Legal Guide provides general legal information only. It does not replace consultation with a qualified lawyer.

Session date: 2026-10-12. Deadline: two weeks from that date. The day-by-day plan is in [`docs/PLAN.md`](docs/PLAN.md).

## Where things stand

The full app exists and works end to end with real models.

**Done:**
- The corpus: 136 Sources, 9,571 passages in the default strategy S1.
- 10 of 11 Retrieval Strategies are indexed. S6 was still importing at the end of the session.
- Two Answering Modes (single-pass and agentic), with four Rule Check tools.
- Update pipeline and admin features: an update run with Change Records, a review queue, a "What changed" feed, an admin dashboard and an MCP server.
- Tests: 190 pass, including the database integration tests.

**Waiting on you:**
- The Golden Set review.
- A decision on the evaluation budget.

## What happened this session

### 1. Planning: the grilling session
We agreed on scope, architecture and plan in about 40 questions. Everything is written down:
- [`CONTEXT.md`](CONTEXT.md): the glossary (Founder, Founder Profile, AI Role, Source, Source Tier, Legal Status, Change Record, Coverage Map, Gap Signal, Retrieval Strategy, Answering Mode, Answer Model, Rule Check, Escalation Trigger, …).
- [`docs/SCOPE.md`](docs/SCOPE.md): jurisdictions (EU, Germany, and the US from a market-entry angle), 9 Legal Areas, the Tier 3 policy, 8 Escalation Triggers, and what is out of scope (tax, personalised advice, US employment law).
- [`docs/adr/`](docs/adr/): 8 decision records. 0001 FastAPI backend, 0002 guidance not advice, 0003 official languages, 0004 latest text plus Legal Status, 0005 switchable index and the strategy table, 0006 Tier 3 reuse policy, 0007 extension points, 0008 models within the OpenRouter guardrail.
- The "not legal advice" statement appears everywhere: README, first-run screen, banner, every answer, every export, every API response, every MCP result.

### 2. Build, days 1–8 of the plan
- **Backend** (Python, FastAPI, LangChain, LangGraph, OpenRouter):
  - A plug-in registry for chunkers, index backends, query transforms and rerankers.
  - Retrieval Strategies declared in `config/strategies.yaml`.
  - Models declared by role in `config/models.yaml`.
- **Retrieval:**
  - Structure-aware, fixed-size and semantic chunking.
  - pgvector, Qdrant and Chroma backends.
  - Hybrid search with German and English stemming.
  - Bilingual query expansion, multi-query and LLM reranking.
  - Tier weights, so official law ranks above practical pages.
  - Strategies that cut and embed text the same way share one index.
- **Answering:**
  - Single-pass and agentic modes, both able to call the four Rule Checks: AI Act risk classifier, applicability checker (GDPR, CCPA, COPPA, DSA, NIS2), compliance timeline, and live source currency check.
  - A citation check after every answer.
  - A question check before every answer: Escalation Triggers, removal of personal data, tax scope.
  - The Founder Profile shapes which law is treated as relevant.
- **Importers:**
  - EUR-Lex, gesetze-im-internet.de, US Code release points, eCFR, and web pages or PDFs.
  - Web importers honour robots.txt and machine-readable text-mining opt-outs (ADR 0006).
  - The Source Registry is `config/sources.yaml`: 148 Sources, all with an importer.
- **Keeping current:**
  - The update run compares per-section fingerprints.
  - Official texts are applied automatically; web pages wait for review.
  - Every change becomes a Change Record, shown in the "What changed" feed.
  - Admin features: an update button with live progress, approve/reject, and a daily schedule (`UPDATE_CRON`).
- **Frontend** (Next.js):
  - Chat with streaming, citations, and the "how this answer was found" panel (searches, rule checks, question check).
  - The Founder Profile questionnaire.
  - The "What changed" panel and the `/dashboard` page (coverage, usage and cost, Gap Signals, evaluations).
  - Per-answer cost, conversation history, and export as JSON, Markdown, CSV or PDF via print.
- **Other:**
  - Demo mode (`DEMO_MODE=1`) runs everything without a key, using verbatim sample excerpts.
  - Rate limiting per client.
  - An MCP server (`founder-legal-guide-mcp`) with 5 tools.

### 3. After you added the OpenRouter key
- **Your OpenRouter guardrail blocks some models:** Claude Haiku, bge-m3, Qwen embeddings, Voyage and Gemini embeddings. We switched to allowed models (ADR 0008):
  - helper model: `gpt-6-luna`
  - default embedding: `text-embedding-3-small`
  - embedding comparison: 3-small vs `mistral-embed` vs 3-large
- **Bug fixed:** Claude Sonnet 5.5 and GPT-6 don't accept `temperature`. Each model's supported parameters are now checked first.
- **Real answers are good:**
  - well grounded, and every citation checks out
  - cross-lingual retrieval works: an English question found BGB § 312k
  - escalations and rule checks fire
  - about $0.05–0.08 per answer with Sonnet
- **Bugs and fixes found by real use:**
  - Tool schemas now accept only valid Legal Areas.
  - Answers are asked to stay at 200–400 words.
  - Tier weights were implemented: agreed in planning, but missing until now.
  - Mistral's per-request token limit: embedding batches are now limited by an estimated token count.
  - Semantic chunks were too long for the embedding model; they are now capped.
  - Imports were slow; strategies now run in parallel per document.
  - The admin token wasn't forwarded by the frontend proxy.
  - Test traffic was going into the real database; tests are now isolated.
- **RAGAs 0.4.3 doesn't work with our LangChain version.** Its four metrics (faithfulness, answer relevancy, context precision, context recall) are implemented in-house in `backend/src/founder_legal_guide/evaluation/metrics.py`.

### 4. First evaluation results
These are on the draft Golden Set (not reviewed yet), 46 answerable questions, k = 8:

| Strategy | hit@8 | recall | MRR |
|---|---|---|---|
| S1 hybrid (default) | 0.59 | 0.59 | 0.34 |
| S3 vector-only | 0.67 | 0.66 | 0.41 |
| S7 multi-query | 0.65 | 0.64 | 0.41 |
| **S8 LLM rerank** | **0.80** | **0.79** | **0.71** |

- **S8 is clearly best**, and it got all 6 cross-lingual questions right.
- **Vector-only beats hybrid.** For colloquial questions the keyword side favours practical pages that repeat the user's words. For example, "Impressum" pushes DDG § 5 from rank 15 down to rank 30.
- **Some "misses" are correct retrievals.** The draft's expected passages are too narrow, which is why the review matters (see below).

## Known gaps

- **12 Sources are blocked** by their sites and marked `BLOCKED` in `sources.yaml`:
  - 7 California laws (leginfo returns 403), including the CCPA
  - the 2 Colorado AI laws (406)
  - the FTC AI-claims blog
  - EUIPO
  - the Data Privacy Framework site, which needs JavaScript

  The importer does not disguise itself as a browser to get around this. California privacy and AI law is therefore **not covered** yet.
- **AI Act Annex III point 4** (employment) was not retrieved by S1 for the CV-screening question; S1 found Art. 6 instead. Reranking (S8) should help; the evaluation will show.
- **Answers still run longer than the 200–400 words asked for.**

## Still running at the end of the session

- **The S6 import** (semantic chunking, the last strategy): 13 of 148 sources, with no failures.
- **The retrieval evaluation** for 10 strategies. The result goes to `data/eval/<time>-retrieval.json` and appears on `/dashboard`.

If either was interrupted, re-run:

```bash
cd backend
uv run founder-legal-guide-ingest --strategy S6
uv run founder-legal-guide-eval retrieval                 # all enabled strategies
```

## Next steps

### For you
1. **Review the Golden Set** in `config/golden_set.yaml`: 53 items, roughly 1–2 hours. Instructions are at the top of the file. For each item:
   - Is the question realistic? Is the reference answer correct?
   - **Add other passages that would also be correct answers** to `expected`. The draft lists are too narrow.
   - Set `status: reviewed`, or `rejected` with a reason in `notes`.
   - Start with the 7 escalation and tax items, the German questions, and the 6 cross-lingual ones.
   - Still open from last time: do you want a small review page in the app instead of editing YAML? About 20 minutes to build.
2. **Choose the answer-evaluation budget.** It costs about $8–9 per configuration on 53 questions (Sonnet answers plus judge calls). A sensible set is about $25–35:
   - S1 vs S8, single-pass
   - S8 single-pass vs agentic
   - Sonnet vs a cheaper model, e.g. Gemini 3.8 Flash or Mistral Large
3. **Decide on the blocked Sources:** add manual snapshots (e.g. saved copies of the CCPA text), find other official sources, or leave the gap documented.
4. **Connect GitHub** when ready, and commit so there is history to show reviewers. Nothing is under git yet.

### For me (next session)
1. Check that the S6 import and the 10-strategy retrieval evaluation finished; run S6's retrieval evaluation.
2. After your review: run `eval retrieval --reviewed-only` (headline numbers) and the answer evaluations with `--judge` within the agreed budget.
3. Decide the default strategy from the results. S8 (reranking) and vector-only search look strongest so far.
4. Retrieval tuning, measured against the reviewed Golden Set:
   - lower the weight of recitals vs articles
   - try vector-only plus reranking as a new strategy
   - check whether S7's multi-query helps once the expected lists are fair
5. Days 13–14 polish:
   - README walkthrough and a demo script
   - screenshots for the submission
   - make answers shorter
   - optionally, user accounts (a Medium soft requirement)
6. Rebuild docker without demo mode (`docker compose up -d --build`) and do a final browser walkthrough with real models.

## Useful commands

```bash
docker compose up -d --build                       # app on :3000 (real models, needs .env)
DEMO_MODE=1 docker compose up -d --build           # no-key demo
cd backend
uv run pytest                                      # unit tests
FLG_INTEGRATION=1 uv run pytest                    # plus database integration tests
uv run founder-legal-guide-ingest --dry-run        # parse and chunk only
uv run founder-legal-guide-update                  # incremental update with Change Records
uv run founder-legal-guide-eval retrieval          # retrieval metrics
uv run founder-legal-guide-eval answers --strategy S1 S8 --mode single_pass --judge
uv run founder-legal-guide-mcp                     # MCP server (stdio)
```

Admin features (update button, review queue, dashboard) need `ADMIN_TOKEN` in `.env`.

---

_This is general legal information, not legal advice. It does not replace consultation with a qualified lawyer._
