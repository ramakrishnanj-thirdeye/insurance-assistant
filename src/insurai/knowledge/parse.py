"""Policy wordings → sections → retrieval chunks (spec 03)."""

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import get_args

import yaml

from insurai.knowledge.schemas import PolicyChunk, PolicySection, PolicyType
from insurai.settings import ROOT

HEADING = re.compile(r"^(\d{1,2})\.\s+([A-Z][A-Z /&-]+?)\s*$", re.MULTILINE)
POLICY_TYPE_LINE = re.compile(r"^Policy Type:\s*(\S+)\s*$")
FAQ_QUESTION = re.compile(r"^Q:", re.MULTILINE)
ACRONYMS = {"FAQ"}
FAQ_SECTION = 15
ALL = "ALL"
ALL_LABEL = "All products"
GUARDRAILS_FILE = ROOT / "config" / "guardrails.yaml"


def parse_policy_file(path: Path) -> list[PolicySection]:
    """Split one wording into its numbered sections. Raises ValueError on a malformed file."""
    raw = path.read_text(encoding="utf-8").lstrip("﻿")
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(f"{path.name}: missing product name or policy type line")
    product = lines[0]
    match = POLICY_TYPE_LINE.match(lines[1])
    if not match or match.group(1) not in get_args(PolicyType):
        raise ValueError(f"{path.name}: expected 'Policy Type: Health|Motor|Travel', got {lines[1]!r}")
    policy_type = match.group(1)

    headings = list(HEADING.finditer(raw))
    numbers = [int(h.group(1)) for h in headings]
    if not numbers or numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"{path.name}: section numbering is not 1..n in order: {numbers}")
    source_path = _source_path(path)
    sections: list[PolicySection] = []
    for i, h in enumerate(headings):
        end = headings[i + 1].start() if i + 1 < len(headings) else len(raw)
        text = raw[h.end() : end].strip()
        sections.append(
            PolicySection(
                product=product,
                policy_type=policy_type,
                section_no=int(h.group(1)),
                section_name=section_name(h.group(2)),
                text=text,
                content_hash=content_hash(text),
                source_path=source_path,
            )
        )
    return sections


def parse_corpus(dir: Path) -> list[PolicySection]:
    return [s for path in sorted(dir.glob("*.txt")) for s in parse_policy_file(path)]


def common_section_nos(sections: list[PolicySection]) -> set[int]:
    """Section numbers whose wording (by content hash) is identical for every product in `sections`."""
    products = {s.product for s in sections}
    variants: dict[int, set[str]] = {}
    present: dict[int, set[str]] = {}
    for s in sections:
        variants.setdefault(s.section_no, set()).add(s.content_hash)
        present.setdefault(s.section_no, set()).add(s.product)
    return {no for no, hashes in variants.items() if len(hashes) == 1 and present[no] == products}


def build_chunks(sections: list[PolicySection]) -> list[PolicyChunk]:
    """Per-product chunks for variable sections, one "ALL" chunk per common section, FAQ as Q/A pairs."""
    common = common_section_nos(sections)
    chunks = [_product_chunk(s) for s in sections if s.section_no not in common]
    seen: set[int] = set()
    for s in sorted(sections, key=lambda s: s.section_no):
        if s.section_no not in common or s.section_no in seen:
            continue
        seen.add(s.section_no)
        if s.section_no == FAQ_SECTION:
            chunks.extend(_faq_chunks(s))
        else:
            chunks.append(_common_chunk(s, f"all-s{s.section_no}", s.text, _header(ALL_LABEL, s)))
    return chunks


def section_name(heading: str) -> str:
    """Title-case a heading: 'CASHLESS / NETWORK PROCESS' → 'Cashless / Network Process'.

    Acronyms in ACRONYMS stay upper case.
    """
    spaced = re.sub(r"\s*/\s*", " / ", heading.strip())
    return " ".join(w if w in ACRONYMS or w == "/" else w.capitalize() for w in spaced.split())


def content_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()[:16]


def citation_label(product: str, section_no: int, name: str) -> str:
    """Label in config/guardrails.yaml citation_format; product "ALL" reads as "All products"."""
    shown = ALL_LABEL if product == ALL else product
    return _citation_format().format(product=shown, section_no=section_no, section_name=name)


def slug(product: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", product.lower()).strip("-")


@lru_cache(maxsize=1)
def _citation_format() -> str:
    guardrails = yaml.safe_load(GUARDRAILS_FILE.read_text(encoding="utf-8"))
    return str(guardrails["citation_format"])


def _source_path(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else resolved.as_posix()


def _header(product_label: str, s: PolicySection) -> str:
    return f"{product_label} › §{s.section_no} {s.section_name}"


def _product_chunk(s: PolicySection) -> PolicyChunk:
    header = _header(f"{s.product} ({s.policy_type})", s)
    return PolicyChunk(
        chunk_id=f"{slug(s.product)}-s{s.section_no}",
        product=s.product,
        policy_type=s.policy_type,
        section_no=s.section_no,
        section_name=s.section_name,
        is_common=False,
        text=s.text,
        header=header,
        embed_text=f"{header}: {s.text}",
        citation_label=citation_label(s.product, s.section_no, s.section_name),
        content_hash=s.content_hash,
        source_path=s.source_path,
    )


def _common_chunk(s: PolicySection, chunk_id: str, text: str, header: str) -> PolicyChunk:
    return PolicyChunk(
        chunk_id=chunk_id,
        product=ALL,
        policy_type=None,
        section_no=s.section_no,
        section_name=s.section_name,
        is_common=True,
        text=text,
        header=header,
        embed_text=f"{header}: {text}",
        citation_label=citation_label(ALL, s.section_no, s.section_name),
        content_hash=content_hash(text),
        source_path=s.source_path,
    )


def _faq_chunks(s: PolicySection) -> list[PolicyChunk]:
    starts = [m.start() for m in FAQ_QUESTION.finditer(s.text)]
    pairs = [s.text[a:b].strip() for a, b in zip(starts, [*starts[1:], len(s.text)], strict=True)]
    return [
        _common_chunk(s, f"all-s{s.section_no}-q{k}", pair, f"{_header(ALL_LABEL, s)} › Q{k}")
        for k, pair in enumerate(pairs, start=1)
    ]
