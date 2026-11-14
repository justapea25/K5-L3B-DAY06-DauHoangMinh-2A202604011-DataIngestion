"""Two chunking strategies over the same paragraphs.

A  fixed_size  : character windows over the whole document text (ignores structure).
B  by_article  : one chunk per "Điều"; oversized articles are split at khoản/điểm
                 boundaries and every piece repeats the article heading.
Both keep page span + chapter/section/article metadata for tracing and filtering.
"""
from __future__ import annotations

import hashlib
import re

from .ingestion import Paragraph
from .models import Chunk


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _meta(paras: list[Paragraph], document_id: str, strategy: str, **extra) -> dict:
    first = paras[0]
    pages = sorted({pg for p in paras for pg in p.pages})
    chapters = list(dict.fromkeys(p.chapter for p in paras if p.chapter))
    articles = list(dict.fromkeys(p.article for p in paras if p.article))
    return {
        "strategy": strategy,
        "document_id": document_id,
        "pages": pages,
        "page_end": pages[-1],
        "chapter": first.chapter,             # filter field (chapter at chunk start)
        "chapter_title": first.chapter_title,
        "chapters": chapters,                 # all chapters touched (A may straddle)
        "section": first.section,
        "articles": articles,
        "year": 2019,
        "document_type": "bo_luat",
        **extra,
    }


def fixed_size(paras: list[Paragraph], document_id: str, source: str,
               size: int = 500, overlap: int = 50) -> list[Chunk]:
    """Slide a `size`-char window (step size-overlap) over the joined text."""
    if not 0 <= overlap < size:
        raise ValueError("need 0 <= overlap < size")
    # Build one string and remember which paragraph owns each char range.
    spans, parts, pos = [], [], 0
    for p in paras:
        spans.append((pos, pos + len(p.text), p))
        parts.append(p.text)
        pos += len(p.text) + 1          # +1 for the "\n" joiner
    full = "\n".join(parts)

    chunks, start, idx = [], 0, 0
    while start < len(full):
        end = min(start + size, len(full))
        text = full[start:end].strip()
        owners = [p for s, e, p in spans if s < end and e > start]
        if text and owners:
            chunks.append(Chunk(
                chunk_id=f"{document_id}:A:{idx:04d}", document_id=document_id,
                source=source, page=owners[0].pages[0], text=text,
                metadata=_meta(owners, document_id, "A", char_start=start,
                               char_end=end, content_hash=_hash(text)),
            ))
            idx += 1
        if end == len(full):
            break
        start = end - overlap
    return chunks


def _split_long(text: str, max_size: int) -> list[str]:
    """Split one very long paragraph at sentence/semicolon boundaries."""
    pieces = re.split(r"(?<=[.;:])\s+", text)
    out, cur = [], ""
    for piece in pieces:
        if cur and len(cur) + 1 + len(piece) > max_size:
            out.append(cur)
            cur = piece
        else:
            cur = f"{cur} {piece}".strip()
    if cur:
        out.append(cur)
    return out


def by_article(paras: list[Paragraph], document_id: str, source: str,
               max_size: int = 1500) -> list[Chunk]:
    """One chunk per Điều; split oversized ones but keep the article heading."""
    groups: list[list[Paragraph]] = []
    for p in paras:
        if p.kind in ("chapter", "chapter_title", "section"):
            continue                       # headings live in metadata, not text
        if p.kind == "article" or not groups or groups[-1][0].article != p.article:
            groups.append([p])
        else:
            groups[-1].append(p)

    chunks: list[Chunk] = []
    for group in groups:
        head = group[0]
        key = f"art{head.article:03d}" if head.article else "preamble"
        body = "\n".join(p.text for p in group)
        if len(body) <= max_size:
            pieces = [group]
        else:
            # Greedy pack paragraphs (khoản/điểm) under max_size; heading repeated.
            heading = head.text if head.kind == "article" else ""
            # budget for the repeated heading incl. " (tiếp theo)" suffix
            head_len = len(heading) + len(" (tiếp theo)") if heading else 0
            pieces, cur, cur_len = [], [], head_len
            for p in (group[1:] if heading else group):
                sub = ([p] if len(p.text) <= max_size - head_len - 1
                       else [Paragraph(**{**p.__dict__, "text": t})
                             for t in _split_long(p.text, max_size - head_len - 1)])
                for s in sub:
                    if cur and cur_len + len(s.text) + 1 > max_size:
                        pieces.append(cur)
                        cur, cur_len = [], head_len
                    cur.append(s)
                    cur_len += len(s.text) + 1
            if cur:
                pieces.append(cur)
            if heading:
                pieces = [[head] + piece for piece in pieces]

        for part, piece in enumerate(pieces):
            text = "\n".join(p.text for p in piece)
            if part > 0 and head.kind == "article":
                text = text.replace(head.text, f"{head.text} (tiếp theo)", 1)
            chunks.append(Chunk(
                chunk_id=f"{document_id}:B:{key}:{part}", document_id=document_id,
                source=source, page=piece[0].pages[0], text=text,
                metadata=_meta(piece, document_id, "B", article=head.article,
                               article_title=head.article_title, part=part,
                               parts=len(pieces), content_hash=_hash(text)),
            ))
    return chunks


def stats(chunks: list[Chunk]) -> dict:
    lengths = sorted(len(c.text) for c in chunks)
    n = len(lengths)
    pct = lambda q: lengths[min(n - 1, int(q * n))]
    return {
        "chunks": n, "total_chars": sum(lengths), "min": lengths[0], "p25": pct(.25),
        "median": pct(.5), "p75": pct(.75), "max": lengths[-1],
        "mean": round(sum(lengths) / n, 1),
        "multi_page_chunks": sum(len(c.metadata["pages"]) > 1 for c in chunks),
        "multi_chapter_chunks": sum(len(c.metadata["chapters"]) > 1 for c in chunks),
    }
