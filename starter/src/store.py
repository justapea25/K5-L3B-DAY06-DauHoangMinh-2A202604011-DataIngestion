"""PostgreSQL + pgvector store: one table, rows keyed by (strategy, chunk_id).

Search is exact (sequential scan, no ANN index) with cosine distance `<=>`;
score = 1 - distance. Strategy C reuses the B rows and adds a metadata filter.
"""
from __future__ import annotations

from typing import Any

import psycopg
from pgvector.psycopg import register_vector
from psycopg.types.json import Jsonb

from .models import Chunk

TABLE = "chunks"
# Only these columns may be used in filters (user values are always bound params).
FILTERABLE = {"chapter": "chapter", "document_id": "document_id", "section": "section",
              "page": "page"}


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def connect(self) -> psycopg.Connection:
        conn = psycopg.connect(self.database_url, connect_timeout=5)
        register_vector(conn)
        return conn

    def create_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            register_vector(conn)
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy      text    NOT NULL,
                    chunk_id      text    NOT NULL,
                    document_id   text    NOT NULL,
                    source        text    NOT NULL,
                    page          integer NOT NULL,
                    pages         integer[] NOT NULL,
                    chapter       text,
                    chapter_title text,
                    section       text,
                    articles      integer[],
                    text          text    NOT NULL,
                    content_hash  text    NOT NULL,
                    metadata      jsonb   NOT NULL,
                    embedding_model text  NOT NULL,
                    embedding     vector({self.dimensions}) NOT NULL,
                    updated_at    timestamptz NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_filter_idx "
                         f"ON {TABLE} (strategy, chapter)")
            # Refuse to mix dimensions if the table already existed with another size.
            dim = conn.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = %s::regclass "
                "AND attname = 'embedding'", (TABLE,)).fetchone()[0]
            if dim != self.dimensions:
                raise RuntimeError(f"table has vector({dim}), model gives {self.dimensions}")

    def existing_hashes(self, strategy: str, document_id: str, model: str) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT chunk_id, content_hash FROM {TABLE} "
                "WHERE strategy = %s AND document_id = %s AND embedding_model = %s",
                (strategy, document_id, model)).fetchall()
        return dict(rows)

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]],
               model: str) -> int:
        """Insert or update by stable (strategy, chunk_id); no duplicates possible."""
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        for v in vectors:
            if len(v) != self.dimensions:
                raise ValueError(f"vector has {len(v)} dims, expected {self.dimensions}")
        rows = [(strategy, c.chunk_id, c.document_id, c.source, c.page,
                 c.metadata["pages"], c.metadata.get("chapter"),
                 c.metadata.get("chapter_title"), c.metadata.get("section"),
                 c.metadata.get("articles"), c.text, c.metadata["content_hash"],
                 Jsonb(c.metadata), model, v) for c, v in zip(chunks, vectors)]
        with self.connect() as conn, conn.cursor() as cur:
            cur.executemany(f"""
                INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, pages,
                    chapter, chapter_title, section, articles, text, content_hash, metadata,
                    embedding_model, embedding)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                    document_id = EXCLUDED.document_id, source = EXCLUDED.source,
                    page = EXCLUDED.page, pages = EXCLUDED.pages,
                    chapter = EXCLUDED.chapter, chapter_title = EXCLUDED.chapter_title,
                    section = EXCLUDED.section, articles = EXCLUDED.articles,
                    text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                    metadata = EXCLUDED.metadata, embedding_model = EXCLUDED.embedding_model,
                    embedding = EXCLUDED.embedding, updated_at = now()""", rows)
        return len(rows)

    def delete_obsolete(self, strategy: str, document_id: str, keep_ids: list[str]) -> int:
        """Remove chunks of this document that no longer exist after re-chunking."""
        with self.connect() as conn:
            cur = conn.execute(
                f"DELETE FROM {TABLE} WHERE strategy = %s AND document_id = %s "
                "AND NOT (chunk_id = ANY(%s))", (strategy, document_id, keep_ids))
            return cur.rowcount

    def count(self, strategy: str) -> tuple[int, int]:
        with self.connect() as conn:
            return conn.execute(
                f"SELECT count(*), count(DISTINCT chunk_id) FROM {TABLE} WHERE strategy = %s",
                (strategy,)).fetchone()

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dimensions:
            raise ValueError("query vector has wrong dimensions")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE:
                raise ValueError(f"filter on '{key}' not allowed")
            where.append(f"{FILTERABLE[key]} = %s")
            params.append(value)
        import numpy as np
        q = np.asarray(query_vector, dtype=np.float32)
        sql = (f"SELECT chunk_id, document_id, source, page, pages, chapter, section, "
               f"articles, text, metadata, 1 - (embedding <=> %s) AS score FROM {TABLE} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s LIMIT %s")
        with self.connect() as conn:
            cur = conn.execute(sql, [q, *params, q, top_k])
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
