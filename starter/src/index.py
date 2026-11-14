"""Embed chunks A/B and load them into pgvector (idempotent re-ingest).

Run from starter/ after `python -m src.prepare`:
    python -m src.index            # embed + upsert + delete obsolete, log to results/
    python -m src.index --query "thời gian thử việc" [--chapter III]
Strategy C uses the B rows plus a metadata filter, so it needs no separate index.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from .embeddings import E5Embedder
from .models import Chunk
from .store import PgVectorStore

STARTER = Path(__file__).resolve().parents[1]
RESULTS = STARTER / "results"
STRATEGIES = ("A", "B")


def load_chunks(strategy: str) -> list[Chunk]:
    path = RESULTS / f"chunks_{strategy}.jsonl"
    if not path.exists():
        raise SystemExit(f"{path} missing: run `python -m src.prepare` first")
    with path.open(encoding="utf-8") as f:
        return [Chunk(**json.loads(line)) for line in f]


def get_store(dimensions: int) -> PgVectorStore:
    load_dotenv(STARTER / ".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing: copy .env.example to .env")
    return PgVectorStore(url, dimensions)


def index_all(embedder: E5Embedder, store: PgVectorStore) -> dict:
    store.create_schema()
    report = {"embedding": embedder.info(), "strategies": {}}
    for strategy in STRATEGIES:
        chunks = load_chunks(strategy)
        doc_ids = {c.document_id for c in chunks}
        t0 = time.perf_counter()
        embedded = deleted = 0
        for doc_id in doc_ids:
            doc_chunks = [c for c in chunks if c.document_id == doc_id]
            existing = store.existing_hashes(strategy, doc_id, embedder.model_name)
            todo = [c for c in doc_chunks
                    if existing.get(c.chunk_id) != c.metadata["content_hash"]]
            if todo:
                vectors = embedder.embed_documents([c.text for c in todo])
                store.upsert(strategy, todo, vectors, embedder.model_name)
            embedded += len(todo)
            deleted += store.delete_obsolete(strategy, doc_id, [c.chunk_id for c in doc_chunks])
        rows, distinct = store.count(strategy)
        report["strategies"][strategy] = {
            "chunks_in_file": len(chunks), "embedded_this_run": embedded,
            "skipped_unchanged": len(chunks) - embedded, "deleted_obsolete": deleted,
            "rows_in_db": rows, "distinct_ids_in_db": distinct,
            "duplicates": rows - distinct, "seconds": round(time.perf_counter() - t0, 2),
        }
        if rows != len(chunks):
            raise RuntimeError(f"{strategy}: db has {rows} rows, file has {len(chunks)}")
        print(strategy, report["strategies"][strategy])
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query")
    ap.add_argument("--chapter", help="metadata filter (strategy C)")
    ap.add_argument("--strategy", default="B", choices=STRATEGIES)
    args = ap.parse_args()

    embedder = E5Embedder()
    store = get_store(embedder.dimensions)

    if args.query:
        filters = {"chapter": args.chapter} if args.chapter else None
        hits = store.search(args.strategy, embedder.embed_query(args.query), 3, filters)
        for h in hits:
            print(f"{h['score']:.3f} {h['chunk_id']} p{h['pages']} ch{h['chapter']}\n"
                  f"   {h['text'][:160]!r}")
        return

    report = index_all(embedder, store)
    log_path = RESULTS / "index_log.json"
    runs = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    runs.append({"run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **report})
    log_path.write_text(json.dumps(runs, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
