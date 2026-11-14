"""Data step: read PDF -> normalize -> structure -> chunk A/B -> manifest + logs.

Run from starter/:  python -m src.prepare
Outputs (all regenerated, deterministic):
  ../data/manifest.json          corpus manifest (source, licence, counted pages)
  results/pages.jsonl            normalized text per physical page
  results/ingest_log.json        issues, structure checks, timings, chunk stats
  results/chunks_A.jsonl / chunks_B.jsonl
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from .chunking import by_article, fixed_size, stats
from .ingestion import MIN_CONTENT_CHARS, load_pdf, structure_report, to_paragraphs

STARTER = Path(__file__).resolve().parents[1]
ROOT = STARTER.parent
RESULTS = STARTER / "results"

CORPUS = {
    "source_id": "bllđ-2019",
    "title": "Bộ luật Lao động số 45/2019/QH14",
    "issuer": "Quốc hội nước CHXHCN Việt Nam khóa XIV, kỳ họp thứ 8",
    "issued_date": "2019-11-20",
    "local_path": "starter/data/bo-luat-lao-dong-2019.pdf",
    "source_path_or_url": "https://phongtochuc.hub.edu.vn/DATA/DOCUMENT/2022/11/24/lu%E1%BA%ADt%20lao%20%C4%91%E1%BB%99ng%20m%E1%BB%9Bi%20nh%E1%BA%A5t%202019.pdf",
    "reference_urls": [
        "https://thuvienphapluat.vn/van-ban/lao-dong-tien-luong/Law-45-2019-QH14-Labor-Code-432162.aspx",
        "https://vbpl.vn",
    ],
    "license_or_permission": (
        "Văn bản quy phạm pháp luật không thuộc đối tượng bảo hộ quyền tác giả "
        "(khoản 1 Điều 15 Luật Sở hữu trí tuệ 50/2005/QH11, sửa đổi bổ sung)."
    ),
    "accessed_at": "2026-11-14",
    "language": "vi",
    "version": (
        "Nguyên văn 45/2019/QH14 khi ban hành; KHÔNG phải văn bản hợp nhất. "
        "Các sửa đổi sau này (VBHN 125/VBHN-VPQH 2025, 18/VBHN-VPQH 2026) không có trong corpus."
    ),
    "provenance_note": (
        "Bản PDF chuyển từ Word (metadata Creator: Microsoft Word 2016, 2022-11-24) đăng trên "
        "website trường ĐH Ngân hàng TP.HCM, không phải cổng chính thức. Cần đối chiếu các "
        "điều dùng trong benchmark với bản trên vbpl.vn / thuvienphapluat."
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_jsonl(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    RESULTS.mkdir(exist_ok=True)
    pdf = ROOT / CORPUS["local_path"]
    doc_id, source = CORPUS["source_id"], CORPUS["local_path"]

    t0 = time.perf_counter()
    pages, issues = load_pdf(pdf, doc_id, source)
    t_read = time.perf_counter() - t0

    paras = to_paragraphs(pages)
    structure = structure_report(paras)

    t1 = time.perf_counter()
    chunks = {"A": fixed_size(paras, doc_id, source, size=500, overlap=50),
              "B": by_article(paras, doc_id, source, max_size=1500)}
    t_chunk = time.perf_counter() - t1

    # chapter of each page (chapters starting on / running through the page)
    page_chapters: dict[int, list[str]] = {}
    for p in paras:
        for pg in p.pages:
            if p.chapter and p.chapter not in page_chapters.setdefault(pg, []):
                page_chapters[pg].append(p.chapter)

    content = [p for p in pages if p.metadata["is_content"]]
    manifest = {
        **CORPUS,
        "sha256": sha256(pdf),
        "physical_pages": len(pages),
        "content_pages": len(content),
        "page_counting_rule": (
            f"Trang PDF vật lý (1-based). Tính là trang nội dung nếu sau chuẩn hóa có ≥ "
            f"{MIN_CONTENT_CHARS} ký tự. Không có bìa/mục lục; trang chỉ có chữ ký bị loại."
        ),
        "excluded_pages": [{"page": i["page"], "reason": i["type"], "text": i.get("text")}
                           for i in issues],
        "pages": [{"page": p.page, "chars": p.metadata["chars"],
                   "is_content": p.metadata["is_content"],
                   "chapters": page_chapters.get(p.page, [])} for p in pages],
        "total_content_chars": sum(p.metadata["chars"] for p in content),
        "metadata_fields": {
            "document_id": "str – ID nguồn",
            "source": "str – đường dẫn file",
            "page": "int – trang PDF bắt đầu chunk; `pages` = mọi trang chunk chạm tới",
            "chapter": "str – số La Mã của Chương (I…XVII), lấy từ dòng 'Chương X' trong văn bản; trường dùng để FILTER",
            "chapter_title": "str – tên chương in hoa trong văn bản",
            "section": "str|null – 'Mục n. …' nếu chương có mục",
            "articles": "list[int] – các Điều nằm trong chunk",
            "year": "int – năm ban hành 2019 (hằng số, chỉ để truy vết)",
        },
    }
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    write_jsonl(RESULTS / "pages.jsonl", (asdict(p) for p in pages))
    for name, cs in chunks.items():
        write_jsonl(RESULTS / f"chunks_{name}.jsonl", (asdict(c) for c in cs))

    log = {
        "pdf_sha256": manifest["sha256"],
        "issues": issues,
        "structure": structure,
        "timing_seconds": {"read_normalize": round(t_read, 3), "chunk": round(t_chunk, 3)},
        "chunk_params": {"A": {"size": 500, "overlap": 50}, "B": {"max_size": 1500}},
        "chunk_stats": {k: stats(v) for k, v in chunks.items()},
    }
    (RESULTS / "ingest_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"pages: {len(pages)} physical, {len(content)} content, "
          f"{manifest['total_content_chars']} chars")
    print(f"issues: {issues}")
    print(f"structure: {structure}")
    for k, v in log["chunk_stats"].items():
        print(f"strategy {k}: {v}")


if __name__ == "__main__":
    main()
