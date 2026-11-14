"""Run strategies A/B/C on the benchmark, save traces, metrics and audit sheets.

    python -m src.run                 # dev only (default; use this to choose)
    python -m src.run --split test    # run ONCE after the configuration is fixed

A = fixed-size chunks, no filter
B = article chunks,    no filter
C = article chunks (same rows as B) + chapter filter when the question has one
Prerequisites: python -m src.prepare && python -m src.index
"""
from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

from .embeddings import E5Embedder
from .evaluation import evaluate_query, summarize
from .index import get_store, load_chunks
from .ingestion import flatten

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"
QUESTIONS = ROOT / "benchmark" / "questions.jsonl"

STRATEGIES = {
    "A": {"index": "A", "use_filter": False, "chunking": "fixed_size 500/50"},
    "B": {"index": "B", "use_filter": False, "chunking": "by_article max 1500"},
    "C": {"index": "B", "use_filter": True, "chunking": "by_article max 1500"},
}
TOP_K = 3
# Coherence sample positions, fixed BEFORE looking at any score:
# the first line of physical pages 2–11 (page 1 starts with the national header).
COHERENCE_PAGES = list(range(2, 12))


def load_questions(split: str) -> list[dict]:
    qs = [json.loads(l) for l in open(QUESTIONS, encoding="utf-8") if l.strip()]
    return [q for q in qs if split == "all" or q["split"] == split]


def run(split: str) -> None:
    questions = load_questions(split)
    embedder = E5Embedder()
    store = get_store(embedder.dimensions)
    traces = []
    for q in questions:
        t0 = time.perf_counter()
        qvec = embedder.embed_query(q["question"])
        embed_ms = (time.perf_counter() - t0) * 1000
        for name, cfg in STRATEGIES.items():
            filters = q.get("filter") if cfg["use_filter"] and q.get("filter") else None
            t1 = time.perf_counter()
            hits = store.search(cfg["index"], qvec, TOP_K, filters)
            search_ms = (time.perf_counter() - t1) * 1000
            ev = evaluate_query(q, hits)
            traces.append({
                "id": q["id"], "split": q["split"], "type": q.get("type"),
                "strategy": name, "question": q["question"],
                "expected_answer": q["expected_answer"], "gold_page": q["gold_page"],
                "gold_article": q.get("gold_article"), "evidence_quote": q["evidence_quote"],
                "question_has_filter": bool(q.get("filter")),
                "filter_applied": filters, "embed_ms": round(embed_ms, 1),
                "search_ms": round(search_ms, 1), **ev,
            })
    metrics = {"split": split, "run_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "embedding": embedder.info(), "top_k": TOP_K, "strategies": STRATEGIES,
               "summary": summarize(traces)}

    with open(RESULTS / f"traces_{split}.jsonl", "w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    (RESULTS / f"metrics_{split}.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    for key, s in metrics["summary"].items():
        print(f"{key:8} Hit@1 {s['hit@1']:14} Hit@3 {s['hit@3']:14} "
              f"split-evidence {s['evidence_split']}  filter {s['filter_compliance_top3']}"
              f"  misses {s['misses']}")

    if split == "test":
        write_test_audits(traces)
    write_coherence_audit()


LABEL_COLS = ("grounding_0_1_2", "metadata_complete_correct_Y_N", "coherence_0_1_2")


def _one_line(row: list) -> list:
    """Keep every CSV record on one physical line (spreadsheet viewers break on \\n)."""
    return [v.replace("\n", " / ") if isinstance(v, str) else v for v in row]


def _has_labels(path: Path) -> bool:
    """True if an audit sheet already contains labels (never overwrite them)."""
    if not path.exists():
        return False
    with open(path, encoding="utf-8") as f:
        return any(row.get(c) for row in csv.DictReader(f) for c in LABEL_COLS)


def write_test_audits(traces: list[dict]) -> None:
    """Blank sheets for manual grounding + metadata labels (5 test q × top-3)."""
    for name in ("audit_grounding_test.csv", "audit_metadata_test.csv"):
        if _has_labels(RESULTS / name):
            print(f"skip {name}: already labelled")
            return
    with open(RESULTS / "audit_grounding_test.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "id", "question", "expected_answer", "evidence_quote",
                    "top3_chunk_ids", "top1_text", "top2_text", "top3_text",
                    "auto_hit@3", "grounding_0_1_2", "reason"])
        for t in traces:
            texts = [r["text"] for r in t["results"]] + [""] * (3 - len(t["results"]))
            w.writerow(_one_line([t["strategy"], t["id"], t["question"], t["expected_answer"],
                        t["evidence_quote"], " | ".join(r["chunk_id"] for r in t["results"]),
                        *texts[:3], t["hit@3"], "", ""]))
    with open(RESULTS / "audit_metadata_test.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["strategy", "id", "rank", "chunk_id", "source", "page", "pages",
                    "chapter", "section", "articles", "filter_required",
                    "metadata_complete_correct_Y_N", "error_note"])
        for t in traces:
            for r in t["results"]:
                w.writerow([t["strategy"], t["id"], r["rank"], r["chunk_id"], r["source"],
                            r["page"], r["pages"], r["chapter"], r["section"], r["articles"],
                            (t["filter_applied"] or {}).get("chapter", ""), "", ""])


def write_coherence_audit() -> None:
    """For each sample position, the chunk of each strategy that contains it."""
    if _has_labels(RESULTS / "audit_coherence.csv"):
        print("skip audit_coherence.csv: already labelled")
        return
    pages = {json.loads(l)["page"]: json.loads(l)
             for l in open(RESULTS / "pages.jsonl", encoding="utf-8")}
    chunks = {"A": load_chunks("A"), "B": load_chunks("B")}
    rows = []
    for pg in COHERENCE_PAGES:
        anchor = flatten(pages[pg]["text"].split("\n")[0])[:60]
        for name, cfg in STRATEGIES.items():
            cands = [c for c in chunks[cfg["index"]]
                     if pg in c.metadata["pages"] and anchor[:40] in flatten(c.text)]
            c = cands[0] if cands else None
            rows.append([f"page{pg}", anchor, name, c.chunk_id if c else "NOT FOUND",
                         len(c.text) if c else "", c.text if c else "", "", ""])
    with open(RESULTS / "audit_coherence.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["position", "anchor_text", "strategy", "chunk_id", "chars",
                    "chunk_text", "coherence_0_1_2", "reason"])
        w.writerows(_one_line(r) for r in rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="dev", choices=["dev", "test", "all"])
    ap.add_argument("--audit-only", action="store_true",
                    help="rebuild audit sheets from saved test traces (no retrieval)")
    args = ap.parse_args()
    if args.audit_only:
        traces = [json.loads(l) for l in open(RESULTS / "traces_test.jsonl", encoding="utf-8")]
        write_test_audits(traces)
        write_coherence_audit()
        return
    run(args.split)


if __name__ == "__main__":
    main()
