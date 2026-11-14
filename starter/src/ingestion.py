"""Read and normalize the corpus, then recover its legal structure.

Pipeline: PDF page -> normalized lines (per page) -> paragraphs that keep
page span + chapter/section/article metadata. Chunkers consume paragraphs.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

# A page is "content" if it has at least this many normalized characters.
MIN_CONTENT_CHARS = 200

RE_CHAPTER = re.compile(r"^Chương ([IVXLC]+)$")
RE_SECTION = re.compile(r"^Mục (\d+)\.\s*(.*)$")
RE_ARTICLE = re.compile(r"^Điều (\d+)\.\s*(.*)$")
RE_ITEM = re.compile(r"^(\d+\.|[a-zđ]\))\s")
RE_SEPARATOR = re.compile(r"^[-_=.\s]{3,}$")


def load_pdf(path: Path, document_id: str, source: str) -> tuple[list[DocumentPage], list[dict]]:
    """Extract each physical page with its 1-based page number.

    Returns (pages, issues). Pages with no/too little text are kept (so page
    numbers stay aligned) but flagged in `issues` and `metadata['is_content']`.
    """
    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    issues: list[dict] = []
    for number, pdf_page in enumerate(reader.pages, start=1):
        try:
            raw = pdf_page.extract_text() or ""
        except Exception as exc:  # record, never hide extraction errors
            issues.append({"page": number, "type": "extract_error", "detail": repr(exc)})
            raw = ""
        text = normalize_text(raw)
        is_content = len(text) >= MIN_CONTENT_CHARS
        if not text:
            issues.append({"page": number, "type": "empty_page"})
        elif not is_content:
            issues.append({"page": number, "type": "short_page_excluded",
                           "chars": len(text), "text": text})
        pages.append(DocumentPage(
            document_id=document_id, source=source, page=number, text=text,
            metadata={"raw_chars": len(raw), "chars": len(text), "is_content": is_content},
        ))
    return pages, issues


def normalize_text(text: str) -> str:
    """NFC Unicode, unify whitespace, drop separator lines; keep line structure.

    Vietnamese text can mix precomposed and combining diacritics; NFC makes
    'ư' + tone marks compare equal between queries, evidence and chunks.
    """
    text = unicodedata.normalize("NFC", text)
    text = text.replace(" ", " ").replace("​", "").replace("\t", " ")
    lines = []
    for line in text.splitlines():
        line = re.sub(r" {2,}", " ", line).strip()
        if not line or RE_SEPARATOR.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)


def flatten(text: str) -> str:
    """Collapse all whitespace; used to compare evidence quotes with page text."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


# ---------------------------------------------------------------- structure

@dataclass
class Paragraph:
    text: str
    kind: str                       # chapter | chapter_title | section | article | item | text
    pages: list[int]
    chapter: str | None = None      # roman numeral, e.g. "X"
    chapter_title: str | None = None
    section: str | None = None      # e.g. "Mục 1. GIAO KẾT HỢP ĐỒNG LAO ĐỘNG"
    article: int | None = None
    article_title: str | None = None
    extra: dict = field(default_factory=dict)


def _is_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def _kind(line: str) -> str:
    if RE_CHAPTER.match(line):
        return "chapter"
    if RE_SECTION.match(line):
        return "section"
    if RE_ARTICLE.match(line):
        return "article"
    if RE_ITEM.match(line):
        return "item"
    if _is_caps(line):
        return "caps"
    return "text"


def to_paragraphs(pages: list[DocumentPage]) -> list[Paragraph]:
    """Re-join PDF-wrapped lines (also across page breaks) into paragraphs.

    Each paragraph records every page it touches and the chapter / section /
    article it belongs to, so chunks can be traced back to the source.
    """
    paras: list[Paragraph] = []
    chapter = chapter_title = section = article_title = None
    article: int | None = None

    for page in pages:
        if not page.metadata.get("is_content"):
            continue
        for line in page.text.split("\n"):
            kind = _kind(line)
            prev = paras[-1] if paras else None

            # Continuation of a wrapped line -> append to previous paragraph.
            joinable = prev is not None and (
                (kind == "text" and prev.kind in ("text", "item"))
                or (kind == "text" and prev.kind == "article" and line[:1].islower())
                or (kind == "caps" and prev.kind in ("section", "chapter_title"))
            )
            if joinable:
                prev.text += " " + line
                if page.page not in prev.pages:
                    prev.pages.append(page.page)
                if prev.kind == "chapter_title":
                    chapter_title = prev.chapter_title = prev.text
                elif prev.kind == "section":
                    section = prev.section = prev.text
                elif prev.kind == "article":
                    article_title = prev.article_title = RE_ARTICLE.match(prev.text).group(2)
                continue

            if kind == "chapter":
                chapter = RE_CHAPTER.match(line).group(1)
                chapter_title = section = article_title = None
                article = None
            elif kind == "caps" and prev is not None and prev.kind == "chapter":
                kind = "chapter_title"
                chapter_title = line
            elif kind == "caps":
                kind = "text"            # e.g. document header lines
            elif kind == "section":
                section = line
                article = None
                article_title = None
            elif kind == "article":
                m = RE_ARTICLE.match(line)
                article, article_title = int(m.group(1)), m.group(2)

            paras.append(Paragraph(
                text=line, kind=kind, pages=[page.page], chapter=chapter,
                chapter_title=chapter_title, section=section,
                article=article, article_title=article_title,
            ))
    return paras


def structure_report(paras: list[Paragraph]) -> dict:
    """Sanity checks that are written to the ingest log."""
    chapters = [p.chapter for p in paras if p.kind == "chapter"]
    articles = [p.article for p in paras if p.kind == "article"]
    expected = list(range(1, (max(articles) if articles else 0) + 1))
    return {
        "chapters_found": len(chapters),
        "chapters": chapters,
        "sections_found": sum(p.kind == "section" for p in paras),
        "articles_found": len(articles),
        "articles_sequential": articles == expected,
        "articles_missing": sorted(set(expected) - set(articles)),
        "articles_duplicated": sorted({a for a in articles if articles.count(a) > 1}),
        "paragraphs": len(paras),
    }
