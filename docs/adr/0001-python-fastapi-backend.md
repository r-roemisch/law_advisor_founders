# Python FastAPI backend behind a Next.js frontend

The app is two services: a Python FastAPI backend running LangChain (Python) with OpenRouter, and a Next.js frontend kept as a thin UI. An all-in-one Next.js app using LangChain.js would be simpler to deploy, but the hard parts of this project are in Python's ecosystem: parsing legal XML (Formex, the gesetze-im-internet XML, USLM), scheduled ingestion jobs, hybrid retrieval, and RAGAs evaluation, which is Python-only. Running two services is the accepted cost.
