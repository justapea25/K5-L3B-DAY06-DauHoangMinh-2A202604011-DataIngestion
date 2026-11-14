"""Validate benchmark/questions.jsonl against the normalized corpus.

Checks: required fields, ≥20 questions, ≥15 dev / ≥5 test, ≥3 filter questions
with ≥1 in test, filter values exist in chunk metadata, and every
evidence_quote occurs (whitespace-insensitive) on its gold_page.
Run from starter/: python -m src.check_benchmark
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .ingestion import flatten

STARTER = Path(__file__).resolve().parents[1]
QUESTIONS = STARTER.parent / "benchmark" / "questions.jsonl"
REQUIRED = ["id", "split", "question", "expected_answer", "gold_source_id",
            "gold_page", "evidence_quote"]


def main() -> None:
    pages = {}
    for line in open(STARTER / "results" / "pages.jsonl", encoding="utf-8"):
        p = json.loads(line)
        pages[(p["document_id"], p["page"])] = flatten(p["text"])
    chapters = {json.loads(l)["metadata"]["chapter"]
                for l in open(STARTER / "results" / "chunks_B.jsonl", encoding="utf-8")}

    qs = [json.loads(l) for l in open(QUESTIONS, encoding="utf-8") if l.strip()]
    errors = []
    for q in qs:
        for f in REQUIRED:
            if q.get(f) in (None, ""):
                errors.append(f"{q.get('id')}: missing {f}")
        golds = [(q["gold_source_id"], q["gold_page"], q["evidence_quote"])]
        golds += [(a["source_id"], a["page"], a["evidence_quote"])
                  for a in q.get("alternative_gold", [])]
        for src, page, quote in golds:
            text = pages.get((src, page))
            if text is None:
                errors.append(f"{q['id']}: page {src}#{page} not in corpus")
            elif flatten(quote) not in text:
                found = [pg for (s, pg), t in pages.items() if s == src and flatten(quote) in t]
                errors.append(f"{q['id']}: evidence not on page {page} (found on {found})")
        if q.get("filter"):
            for k, v in q["filter"].items():
                if k != "chapter" or v not in chapters:
                    errors.append(f"{q['id']}: invalid filter {k}={v}")

    split = {s: [q for q in qs if q["split"] == s] for s in ("dev", "test")}
    filt = {s: sum(bool(q.get("filter")) for q in v) for s, v in split.items()}
    ids = [q["id"] for q in qs]
    if len(set(ids)) != len(ids):
        errors.append("duplicate ids")
    if len(qs) < 20: errors.append(f"only {len(qs)} questions")
    if len(split["dev"]) < 15: errors.append("fewer than 15 dev")
    if len(split["test"]) < 5: errors.append("fewer than 5 test")
    if sum(filt.values()) < 3: errors.append("fewer than 3 filter questions")
    if filt["test"] < 1: errors.append("no filter question in test")
    dev_art = {q.get("gold_article") for q in split["dev"]}
    overlap = sorted(a for a in {q.get("gold_article") for q in split["test"]} & dev_art if a)

    print(f"questions={len(qs)} dev={len(split['dev'])} test={len(split['test'])} "
          f"filter dev={filt['dev']} test={filt['test']}")
    print(f"types: { {t: sum(q.get('type') == t for q in qs) for t in sorted({q.get('type') for q in qs})} }")
    print(f"test articles also used in dev: {overlap or 'none'}")
    if errors:
        print("ERRORS:\n  " + "\n  ".join(errors))
        sys.exit(1)
    print("OK: all evidence quotes found on their gold pages")


if __name__ == "__main__":
    main()
