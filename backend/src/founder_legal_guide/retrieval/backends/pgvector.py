"""Postgres + pgvector backend.

Hybrid search fuses vector similarity with Postgres full-text search. Each passage is
stemmed in its own language (German or English), and keyword queries are matched under
both configurations, which a single-language LangChain hybrid config cannot do.
"""

import json

import psycopg
from psycopg import sql

from ..fusion import reciprocal_rank_fusion
from ..types import Hit, Passage, Query, SearchFilters, SearchMode
from .base import BACKENDS, IndexBackend

# pgvector indexes `vector` up to 2000 dimensions and `halfvec` up to 4000.
_VECTOR_MAX_DIM = 2000
_HALFVEC_MAX_DIM = 4000


@BACKENDS.register("pgvector")
class PgVectorBackend(IndexBackend):
    search_modes = frozenset({"vector", "hybrid"})

    def __init__(self, index_name, settings, **params):
        super().__init__(index_name, settings)
        self._table = f"passages_{self.slug}"
        self._vector_type: str | None = None

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.settings.database_url, autocommit=True)

    def _ensure(self, conn: psycopg.Connection, dim: int) -> None:
        if dim > _HALFVEC_MAX_DIM:
            raise ValueError(f"{dim}-dimensional embeddings exceed pgvector's index limit")
        vtype = "vector" if dim <= _VECTOR_MAX_DIM else "halfvec"
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            sql.SQL(
                """
                CREATE TABLE IF NOT EXISTS {table} (
                    id text PRIMARY KEY,
                    source_id text NOT NULL,
                    language text NOT NULL,
                    jurisdiction text NOT NULL,
                    tier int NOT NULL,
                    legal_areas text[] NOT NULL,
                    payload jsonb NOT NULL,
                    content text NOT NULL,
                    embedding {vtype}({dim}) NOT NULL,
                    tsv tsvector GENERATED ALWAYS AS (
                        to_tsvector(
                            CASE WHEN language = 'de' THEN 'german'::regconfig
                                 ELSE 'english'::regconfig END,
                            content)
                    ) STORED
                )
                """
            ).format(table=sql.Identifier(self._table), vtype=sql.SQL(vtype), dim=sql.Literal(dim))
        )
        conn.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {idx} ON {table} USING hnsw (embedding {ops})"
            ).format(
                idx=sql.Identifier(f"{self._table}_hnsw"),
                table=sql.Identifier(self._table),
                ops=sql.SQL(f"{vtype}_cosine_ops"),
            )
        )
        conn.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} USING gin (tsv)").format(
                idx=sql.Identifier(f"{self._table}_tsv"), table=sql.Identifier(self._table)
            )
        )
        conn.execute(
            sql.SQL("CREATE INDEX IF NOT EXISTS {idx} ON {table} (source_id, language)").format(
                idx=sql.Identifier(f"{self._table}_source"), table=sql.Identifier(self._table)
            )
        )
        self._vector_type = vtype

    def _detect_vector_type(self, conn: psycopg.Connection) -> str | None:
        row = conn.execute(
            """
            SELECT format_type(a.atttypid, a.atttypmod)
            FROM pg_attribute a JOIN pg_class c ON a.attrelid = c.oid
            WHERE c.relname = %s AND a.attname = 'embedding'
            """,
            (self._table,),
        ).fetchone()
        if row is None:
            return None
        return "halfvec" if row[0].startswith("halfvec") else "vector"

    def upsert(self, passages: list[Passage], vectors: list[list[float]]) -> None:
        if not passages:
            return
        with self._connect() as conn:
            self._ensure(conn, len(vectors[0]))
            with conn.cursor() as cur:
                cur.executemany(
                    sql.SQL(
                        """
                        INSERT INTO {table}
                            (id, source_id, language, jurisdiction, tier, legal_areas,
                             payload, content, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::{vtype})
                        ON CONFLICT (id) DO UPDATE SET
                            payload = EXCLUDED.payload, content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding
                        """
                    ).format(table=sql.Identifier(self._table), vtype=sql.SQL(self._vector_type)),
                    [
                        (
                            p.id,
                            p.source.id,
                            p.language,
                            p.source.jurisdiction,
                            p.source.tier,
                            list(p.source.legal_areas),
                            json.dumps(p.to_payload()),
                            p.embedding_text,
                            _vector_literal(v),
                        )
                        for p, v in zip(passages, vectors, strict=True)
                    ],
                )

    def delete_source(self, source_id: str, language: str) -> None:
        with self._connect() as conn:
            if self._detect_vector_type(conn) is None:
                return
            conn.execute(
                sql.SQL("DELETE FROM {table} WHERE source_id = %s AND language = %s").format(
                    table=sql.Identifier(self._table)
                ),
                (source_id, language),
            )

    def search(
        self, query: Query, vector: list[float], k: int, mode: SearchMode, filters: SearchFilters
    ) -> list[Hit]:
        with self._connect() as conn:
            vtype = self._vector_type or self._detect_vector_type(conn)
            if vtype is None:
                return []
            conditions, params = _filter_conditions(filters)
            pool = k * 3 if mode == "hybrid" else k
            dense = self._dense(conn, vtype, vector, pool, conditions, params)
            if mode == "vector":
                return dense[:k]
            keyword = self._keyword(conn, query.text, pool, conditions, params)
            return reciprocal_rank_fusion([dense, keyword], limit=k)

    def _dense(self, conn, vtype, vector, limit, conditions, params) -> list[Hit]:
        where = sql.SQL("WHERE " + " AND ".join(conditions)) if conditions else sql.SQL("")
        rows = conn.execute(
            sql.SQL(
                """
                SELECT payload, 1 - (embedding <=> %s::{vtype}) AS score
                FROM {table} {where}
                ORDER BY embedding <=> %s::{vtype}
                LIMIT %s
                """
            ).format(table=sql.Identifier(self._table), vtype=sql.SQL(vtype), where=where),
            [_vector_literal(vector), *params, _vector_literal(vector), limit],
        ).fetchall()
        return [Hit(Passage.from_payload(payload), float(score)) for payload, score in rows]

    def _keyword(self, conn, text, limit, conditions, params) -> list[Hit]:
        # OR the lexemes of both language configurations, so long questions still match.
        tsq = (
            "(SELECT replace(websearch_to_tsquery('english', %s)::text, '&', '|')::tsquery"
            " || replace(websearch_to_tsquery('german', %s)::text, '&', '|')::tsquery AS q)"
        )
        where = sql.SQL(" AND ".join(["tsv @@ q", *conditions]))
        rows = conn.execute(
            sql.SQL(
                """
                SELECT payload, ts_rank_cd(tsv, q) AS score
                FROM {table}, {tsq} AS query
                WHERE {where}
                ORDER BY score DESC
                LIMIT %s
                """
            ).format(table=sql.Identifier(self._table), tsq=sql.SQL(tsq), where=where),
            [text, text, *params, limit],
        ).fetchall()
        return [Hit(Passage.from_payload(payload), float(score)) for payload, score in rows]

    def count(self) -> int:
        with self._connect() as conn:
            if self._detect_vector_type(conn) is None:
                return 0
            return conn.execute(
                sql.SQL("SELECT count(*) FROM {table}").format(table=sql.Identifier(self._table))
            ).fetchone()[0]


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"


def _filter_conditions(filters: SearchFilters) -> tuple[list[str], list]:
    """SQL conditions (fixed strings with %s placeholders) and their parameters."""
    parts, params = [], []
    if filters.jurisdictions:
        parts.append("jurisdiction = ANY(%s)")
        params.append(sorted(filters.jurisdictions))
    if filters.legal_areas:
        parts.append("legal_areas && %s")
        params.append(sorted(filters.legal_areas))
    if filters.tiers:
        parts.append("tier = ANY(%s)")
        params.append(sorted(filters.tiers))
    return parts, params
