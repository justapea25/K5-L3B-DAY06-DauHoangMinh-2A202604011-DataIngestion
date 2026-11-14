"""Automatic retrieval scoring (Hit@1, Evidence Hit@3) + per-query traces.

A retrieved chunk is a HIT when it belongs to a gold source, covers a gold page,
and contains the WHOLE evidence quote (whitespace-insensitive). Human labels
(coherence, grounding) are NOT inferred here; see the audit CSVs.
"""
from __future__ import annotations

from typing import Any

from .ingestion import flatten


def _golds(q: dict[str, Any]) -> list[dict[str, Any]]:
    golds = [{"source_id": q["gold_source_id"], "page": q["gold_page"],
              "evidence_quote": q["evidence_quote"]}]
    return golds + list(q.get("alternative_gold", []))


def _match(hit: dict[str, Any], gold: dict[str, Any]) -> dict[str, bool]:
    text = flatten(hit["text"])
    quote = flatten(gold["evidence_quote"])
    head, tail = quote[: max(15, len(quote) // 3)], quote[-max(15, len(quote) // 3):]
    return {
        "source": hit["document_id"] == gold["source_id"],
        "page": gold["page"] in (hit.get("pages") or [hit["page"]]),
        "full_evidence": quote in text,
        "partial_evidence": quote not in text and (head in text or tail in text),
    }


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = []
    for rank, hit in enumerate(hits, start=1):
        checks = [_match(hit, g) for g in _golds(question)]
        is_hit = any(c["source"] and c["page"] and c["full_evidence"] for c in checks)
        partial = (not is_hit) and any(c["source"] and c["page"] and c["partial_evidence"]
                                       for c in checks)
        ranked.append({
            "rank": rank, "chunk_id": hit["chunk_id"], "score": round(float(hit["score"]), 4),
            "document_id": hit["document_id"], "source": hit["source"], "page": hit["page"],
            "pages": hit.get("pages"), "chapter": hit.get("chapter"),
            "section": hit.get("section"), "articles": hit.get("articles"),
            "text": hit["text"], "hit": is_hit, "evidence_split": partial,
        })
    first = next((r["rank"] for r in ranked if r["hit"]), None)
    filt = question.get("filter")
    return {
        "hit@1": bool(ranked and ranked[0]["hit"]),
        "hit@3": first is not None and first <= 3,
        "first_hit_rank": first,
        "evidence_split_in_top3": any(r["evidence_split"] for r in ranked[:3]),
        # automatic filter-compliance check (still to be confirmed manually)
        "filter_compliant": (all(r["chapter"] == filt["chapter"] for r in ranked[:3])
                             if filt else None),
        "results": ranked,
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in traces:
        key = f"{t['strategy']}/{t['split']}"
        s = out.setdefault(key, {"n": 0, "hit1": 0, "hit3": 0, "evidence_split": 0,
                                 "filter_n": 0, "filter_compliant": 0,
                                 "filter_q_hit3": 0, "misses": []})
        s["n"] += 1
        s["hit1"] += t["hit@1"]
        s["hit3"] += t["hit@3"]
        s["evidence_split"] += t["evidence_split_in_top3"]
        if t["question_has_filter"]:       # compliance is measured for A/B too
            s["filter_n"] += 1
            s["filter_compliant"] += bool(t["filter_compliant"])
            s["filter_q_hit3"] += t["hit@3"]
        if not t["hit@3"]:
            s["misses"].append(t["id"])
    for s in out.values():
        s["hit@1"] = f"{s['hit1']}/{s['n']} = {s['hit1'] / s['n']:.2f}"
        s["hit@3"] = f"{s['hit3']}/{s['n']} = {s['hit3'] / s['n']:.2f}"
        s["filter_compliance_top3"] = (f"{s['filter_compliant']}/{s['filter_n']}"
                                       if s["filter_n"] else "N/A")
    return out
