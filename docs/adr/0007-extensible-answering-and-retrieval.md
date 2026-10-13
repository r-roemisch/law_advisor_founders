# Retrieval Strategies, Answer Models and Answering Modes are extension points

The guide is a test bench for RAG approaches as much as a product, so the three things most likely to grow are open for extension rather than hard-coded.

- **Retrieval Strategies** are declared in `config/strategies.yaml` and composed from building blocks registered by name in code: chunker, embedding model, index backend, search mode, plus optional query-transformation and reranking steps. Adding a technique (semantic chunking, HyDE, a reranker, parent-document retrieval) means one new class plus one YAML entry. The update pipeline, the UI picker and the evaluation pick it up automatically. Query expansion into both languages is the first query-transformation plug-in.
- **Models** are declared in `config/models.yaml` by role (answer, utility, judge). Any OpenRouter model ID works. The judge model stays fixed across comparisons.
- **Answering Modes** are separate LangGraph graphs: *single-pass* and *agentic*, both part of the core scope. Agentic reuses the `search_corpus(query, strategy, filters)` tool, which is also exposed via MCP.

The citation check validates against every chunk retrieved during a turn, so it works in both modes. Each evaluation run records Retrieval Strategy × Answering Mode × Answer Model.

A single fixed pipeline would be faster to write, but adding a strategy, model or mode would then touch ingestion, retrieval, UI and evaluation code at once.
