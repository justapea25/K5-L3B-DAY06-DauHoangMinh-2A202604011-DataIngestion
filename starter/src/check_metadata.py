"""Verify metadata of every test top-3 record against the normalized source pages.

For each (strategy, question, rank) row in results/audit_metadata_test.csv:
  source  : file exists and equals the manifest local_path
  page    : the chunk's first 40 chars occur on `page`
  pages   : the chunk's last 40 chars occur on the last listed page
  chapter : equals the last "Chương X" heading before the chunk start in the PDF text
  filter  : when the question required a chapter, the record's chapter matches it
Writes the verdict into metadata_complete_correct_Y_N / error_note (draft labels
for the author to review). Run from starter/: python -m src.check_metadata
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from .ingestion import flatten

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"


def main() -> None:
    manifest = json.loads((ROOT / "data" / "manifest.json").read_text(encoding="utf-8"))
    pages = {p["page"]: flatten(p["text"])
             for p in map(json.loads, open(RESULTS / "pages.jsonl", encoding="utf-8"))}
    # full text with page offsets, to locate chapter headings before a position
    full, starts = "", {}
    for n in sorted(pages):
        starts[n] = len(full)
        full += pages[n] + " "
    chapters = [(m.start(), m.group(1)) for m in re.finditer(r"Chương ([IVXLC]+) [A-ZĐ]", full)]

    traces = {(t["strategy"], t["id"]): t
              for t in map(json.loads, open(RESULTS / "traces_test.jsonl", encoding="utf-8"))}
    path = RESULTS / "audit_metadata_test.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    ok_count = 0
    for row in rows:
        hit = traces[(row["strategy"], row["id"])]["results"][int(row["rank"]) - 1]
        raw = hit["text"]
        # Continuation chunks repeat "Điều N. … (tiếp theo)" as their first line; that
        # line is added by the chunker, so locate the chunk by the text after it.
        if raw.split("\n", 1)[0].endswith("(tiếp theo)") and "\n" in raw:
            raw = raw.split("\n", 1)[1]
        text = flatten(raw)
        listed = hit.get("pages") or [hit["page"]]
        head = text[:40] if len(listed) == 1 else text[:20]
        tail = text[-8:]
        span = " ".join(pages.get(p, "") for p in listed)
        errors = []
        if hit["source"] != manifest["local_path"] or not (ROOT / hit["source"]).exists():
            errors.append("source sai")
        if head not in pages.get(hit["page"], ""):
            errors.append(f"đầu chunk không nằm ở trang {hit['page']}")
        if text[-40:] not in span or tail not in pages.get(listed[-1], ""):
            errors.append(f"cuối chunk không nằm ở trang {listed[-1]}")
        pos = full.find(head, starts.get(hit["page"], 0))
        true_ch = next((c for p, c in reversed(chapters) if p <= pos), None) if pos >= 0 else None
        if true_ch != hit["chapter"]:
            errors.append(f"chapter ghi {hit['chapter']} nhưng văn bản thuộc Chương {true_ch}")
        req = row["filter_required"]
        if req and hit["chapter"] != req:
            errors.append(f"không tuân thủ filter {req}")
        row["metadata_complete_correct_Y_N"] = "N" if errors else "Y"
        row["error_note"] = "; ".join(errors) or (
            f"source/page {hit['page']}{'→' + str(listed[-1]) if len(listed) > 1 else ''}"
            f"/chapter {hit['chapter']} khớp văn bản gốc")
        ok_count += not errors
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    for s in ("A", "B", "C"):
        sub = [r for r in rows if r["strategy"] == s]
        print(s, f"{sum(r['metadata_complete_correct_Y_N'] == 'Y' for r in sub)}/{len(sub)}",
              [r["error_note"] for r in sub if r["metadata_complete_correct_Y_N"] == "N"])
    print(f"total {ok_count}/{len(rows)}")


if __name__ == "__main__":
    main()
