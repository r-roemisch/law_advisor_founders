"""Runs each index backend against the real databases from docker-compose.

docker compose up -d postgres qdrant chroma
FLG_INTEGRATION=1 uv run pytest tests/integration
"""

import os
import uuid

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from founder_legal_guide.retrieval.backends import BACKENDS
from founder_legal_guide.retrieval.chunkers import StructureChunker
from founder_legal_guide.retrieval.types import Query, SearchFilters
from founder_legal_guide.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("FLG_INTEGRATION") != "1", reason="set FLG_INTEGRATION=1 with databases running"
)

MODES = [
    ("pgvector", "vector"),
    ("pgvector", "hybrid"),
    ("qdrant", "vector"),
    ("qdrant", "hybrid"),
    ("chroma", "vector"),
]


@pytest.fixture
def make_backend():
    created = []

    def make(name: str):
        backend = BACKENDS.get(name)(f"test-{uuid.uuid4().hex[:8]}", Settings())
        created.append(backend)
        return backend

    yield make
    for backend in created:
        _drop(backend)


def _drop(backend):
    if backend.__class__.__name__ == "PgVectorBackend":
        import psycopg

        with psycopg.connect(backend.settings.database_url, autocommit=True) as conn:
            conn.execute(f'DROP TABLE IF EXISTS "{backend._table}"')
    elif backend.__class__.__name__ == "QdrantBackend":
        backend._client.delete_collection(backend._collection)
    elif backend.__class__.__name__ == "ChromaBackend":
        backend._collection()
        backend._client.delete_collection(backend._name)


def index(backend, ctx, docs, dim=16):
    embeddings = DeterministicFakeEmbedding(size=dim)
    for doc in docs:
        passages = StructureChunker(ctx, "fake").chunk(doc)
        backend.upsert(passages, embeddings.embed_documents([p.embedding_text for p in passages]))
    return embeddings


@pytest.mark.parametrize(("backend_name", "mode"), MODES)
def test_upsert_search_filter_delete(make_backend, ctx, gdpr_doc, bdsg_doc, backend_name, mode):
    backend = make_backend(backend_name)
    assert backend.count() == 0
    assert backend.search(Query("x"), [0.1] * 16, 3, mode, SearchFilters()) == []

    embeddings = index(backend, ctx, [gdpr_doc, bdsg_doc])
    assert backend.count() == 4

    text = "processor documented instructions data processing agreement"
    hits = backend.search(Query(text), embeddings.embed_query(text), 3, mode, SearchFilters())
    assert len(hits) == 3
    assert hits[0].passage.source.title in {"GDPR", "BDSG"}

    de_only = backend.search(
        Query("Beschäftigten"),
        embeddings.embed_query("Beschäftigten"),
        5,
        mode,
        SearchFilters(jurisdictions=frozenset({"DE"})),
    )
    assert {h.passage.source.id for h in de_only} == {"de-bdsg"}

    by_area = backend.search(
        Query("data"),
        embeddings.embed_query("data"),
        5,
        mode,
        SearchFilters(legal_areas=frozenset({"employment"})),
    )
    assert {h.passage.source.id for h in by_area} == {"de-bdsg"}

    backend.delete_source("eu-gdpr", "en")
    assert backend.count() == 1


@pytest.mark.parametrize("backend_name", ["pgvector", "qdrant"])
def test_hybrid_lifts_exact_term_matches_in_both_languages(
    make_backend, ctx, gdpr_doc, bdsg_doc, backend_name
):
    backend = make_backend(backend_name)
    embeddings = index(backend, ctx, [gdpr_doc, bdsg_doc])
    vector = embeddings.embed_query("unrelated")

    def rank(mode: str, text: str, source_id: str) -> int:
        hits = backend.search(Query(text), vector, 4, mode, SearchFilters())
        return [h.passage.source.id for h in hits].index(source_id)

    # A stemmed German keyword ("Beschäftigte" vs. "Beschäftigten") and an English one.
    for text, source_id in [("Beschäftigte", "de-bdsg"), ("notify breach", "eu-gdpr")]:
        hybrid, vector_only = rank("hybrid", text, source_id), rank("vector", text, source_id)
        assert hybrid == 0 or hybrid < vector_only


def test_pgvector_keyword_search_stems_each_language(make_backend, ctx, gdpr_doc, bdsg_doc):
    backend = make_backend("pgvector")
    index(backend, ctx, [gdpr_doc, bdsg_doc])
    with backend._connect() as conn:
        german = backend._keyword(conn, "Beschäftigte", 5, [], [])
        english = backend._keyword(conn, "notifying breaches", 5, [], [])
    assert [h.passage.source.id for h in german] == ["de-bdsg"]
    assert english[0].passage.anchor == "art-33"


def test_pgvector_uses_halfvec_above_2000_dimensions(make_backend, ctx, gdpr_doc):
    backend = make_backend("pgvector")
    embeddings = index(backend, ctx, [gdpr_doc], dim=2560)
    hits = backend.search(
        Query("breach"), embeddings.embed_query("breach"), 2, "hybrid", SearchFilters()
    )
    assert len(hits) == 2
    assert backend._vector_type == "halfvec"


def test_postgres_corpus_state_round_trip():
    from founder_legal_guide.ingestion.state import ChangeRecord, PostgresVersionStore

    store = PostgresVersionStore(Settings().database_url)
    source = f"test-{uuid.uuid4().hex[:8]}"
    assert store.current(source, "en") is None
    store.record(source, "en", "v1", {"Art. 1": "abc"})
    assert store.current(source, "en").section_hashes == {"Art. 1": "abc"}
    change_id = store.add_change(
        ChangeRecord(
            source_id=source,
            language="en",
            kind="changed",
            status="review_needed",
            old_version="v1",
            new_version="v2",
            summary={"added": [], "removed": [], "modified": ["Art. 1"]},
            pending={"version": "v2"},
        )
    )
    assert store.change(change_id).pending == {"version": "v2"}
    assert store.changes(status="review_needed")[0].source_id in {
        source,
        *[c.source_id for c in store.changes(200)],
    }
    store.decide(change_id, "approved")
    decided = store.change(change_id)
    assert (
        decided.status == "approved" and decided.pending is None and decided.decided_at is not None
    )
