"""Table-aware extraction for SEC filings (Wave 3b).

Fixed/sentence chunking shreds financial tables — a number gets cut from its row
label or column header, so numeric questions miss (Wave 3a confirmed this). This
module pulls tables out as coherent units with Docling and serializes each into a
compact text block (row label + values), so a table becomes one self-contained
chunk that an embedding can represent and a reader can cite.

SEC HTML uses deeply nested formatting tables full of empty spacer cells; Docling
recovers the real cells but emits many blank columns, so serialization drops
empty cells and tables that carry no numbers.

Public surface
--------------
- `extract_tables(html_path)` — list of serialized table strings (data tables only)
"""

from __future__ import annotations

import re
from pathlib import Path

_NUM = re.compile(r"\d")


def _serialize(markdown: str) -> str:
    """Compact a Docling table markdown into 'cell | cell' rows, dropping empties."""
    rows: list[str] = []
    for line in markdown.splitlines():
        if set(line.strip()) <= {"|", "-", " "}:  # separator / empty row
            continue
        cells = [c.strip() for c in line.split("|")]
        # Collapse consecutive duplicate cells (Docling repeats merged cells) and drop blanks.
        compact: list[str] = []
        for c in cells:
            if c and (not compact or compact[-1] != c):
                compact.append(c)
        if compact:
            rows.append(" | ".join(compact))
    return "\n".join(rows)


def extract_tables(html_path: str | Path, *, min_numbers: int = 3) -> list[str]:
    """Return serialized data tables from an SEC filing HTML document.

    Tables with fewer than `min_numbers` numeric tokens are dropped (cover-page
    layout tables, signature blocks, etc.).
    """
    # Imported lazily — Docling is a heavy optional dependency used only at ingest.
    from docling.document_converter import DocumentConverter

    doc = DocumentConverter().convert(str(html_path)).document
    out: list[str] = []
    for table in doc.tables:
        text = _serialize(table.export_to_markdown(doc))
        if len(_NUM.findall(text)) >= min_numbers:
            out.append(text)
    return out
