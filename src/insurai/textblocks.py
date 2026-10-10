"""Idempotent answer assembly (spec 08): appended blocks never repeat, and a paragraph or line the model
wrote twice is kept once. Comparison is on normalised text (casefold, markdown emphasis and whitespace
collapsed, trailing punctuation stripped); table rows and blank lines are never deduplicated.
"""

import re

_EMPHASIS = re.compile(r"[*_`]+")
_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")
_HEADING = re.compile(r"^\s*[^|\n]{1,60}:\s*$")  # "Next steps:", "Also noted:" (a line that only introduces)


def norm(text: str) -> str:
    return " ".join(_EMPHASIS.sub("", text).casefold().split()).strip(" .:;,")


def is_heading(line: str) -> bool:
    return bool(_HEADING.match(line))


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def append_once(text: str, block: str) -> str:
    """`text` with `block` appended as its own paragraph, unless the text already carries it."""
    block = block.strip()
    if not block:
        return text
    if norm(block) and norm(block) in norm(text):
        return text
    return f"{text.rstrip()}\n\n{block}" if text.strip() else block


def dedupe_paragraphs(text: str) -> str:
    """Repeated paragraphs and repeated non-table lines removed (first kept); a heading with nothing under it
    removed; one blank line between paragraphs."""
    seen_paragraphs: set[str] = set()
    seen_lines: set[str] = set()
    paragraphs: list[str] = []
    for paragraph in _PARAGRAPH_BREAK.split(text.strip()):
        key = norm(paragraph)
        if not key or key in seen_paragraphs:
            continue
        seen_paragraphs.add(key)
        lines: list[str] = []
        for line in paragraph.split("\n"):
            line_key = norm(line)
            if line_key and not _is_table_row(line) and not is_heading(line):
                if line_key in seen_lines:
                    continue
                seen_lines.add(line_key)
            lines.append(line)
        if any(norm(line) for line in lines):
            paragraphs.append("\n".join(lines))
    return _drop_empty_headings("\n\n".join(paragraphs))


def _drop_empty_headings(text: str) -> str:
    """A heading line ("Next steps:") followed by nothing, or directly by another heading, is removed."""
    lines = text.split("\n")
    out: list[str] = []
    for k, line in enumerate(lines):
        if is_heading(line):
            nxt = next((ln for ln in lines[k + 1 :] if norm(ln)), None)
            if nxt is None or is_heading(nxt):
                continue
        out.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
