import csv
import re
from pathlib import Path

import pytest
import yaml

from insurai.knowledge.parse import build_chunks, common_section_nos, parse_corpus, parse_policy_file
from insurai.knowledge.schemas import PolicyChunk, PolicySection
from insurai.settings import ROOT, get_settings

pytestmark = pytest.mark.unit

VARIABLE = {2, 4, 5, 9, 10}
COMMON = {1, 3, 6, 7, 8, 11, 12, 13, 14, 15}


@pytest.fixture(scope="module")
def sections() -> list[PolicySection]:
    return parse_corpus(get_settings().paths.policy_docs_dir)


@pytest.fixture(scope="module")
def chunks(sections: list[PolicySection]) -> list[PolicyChunk]:
    return build_chunks(sections)


def _by_product(sections: list[PolicySection]) -> dict[str, list[PolicySection]]:
    out: dict[str, list[PolicySection]] = {}
    for s in sections:
        out.setdefault(s.product, []).append(s)
    return out


def test_AC_03_01_every_file_parses_to_15_sections() -> None:
    files = sorted(get_settings().paths.policy_docs_dir.glob("*.txt"))
    assert len(files) == 10
    for path in files:
        parsed = parse_policy_file(path)
        assert [s.section_no for s in parsed] == list(range(1, 16)), path.name
        assert all(s.text for s in parsed)
        assert all(len(s.content_hash) == 16 for s in parsed)
        assert parsed[0].source_path == f"data/raw/policy_documents/{path.name}"


def test_AC_03_01_product_and_type_match_policies_csv(sections: list[PolicySection]) -> None:
    with (ROOT / "data" / "raw" / "policies.csv").open(encoding="utf-8", newline="") as f:
        expected = {(row["product_name"], row["policy_type"]) for row in csv.DictReader(f)}
    parsed = {(s.product, s.policy_type) for s in sections}
    assert len(expected) == 10
    assert parsed == expected


def test_AC_03_01_section_names_title_cased(sections: list[PolicySection]) -> None:
    names = {s.section_no: s.section_name for s in sections if s.product == "Health Secure Plus"}
    assert names[1] == "Purpose"
    assert names[5] == "Maternity"
    assert names[6] == "Hospitalization / Loss Coverage"
    assert names[7] == "Cashless / Network Process"
    assert names[13] == "Human Review"
    assert names[15] == "Training FAQ"


def test_AC_03_01_bad_numbering_raises(tmp_path: Path) -> None:
    bad = tmp_path / "Bad.txt"
    bad.write_text(
        "\nBad Plan\nPolicy Type: Health\n\n1. PURPOSE\nx\n\n3. ELIGIBILITY\ny\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="numbering"):
        parse_policy_file(bad)


def test_AC_03_01_unknown_policy_type_raises(tmp_path: Path) -> None:
    bad = tmp_path / "Bad.txt"
    bad.write_text("Bad Plan\nPolicy Type: Pet\n\n1. PURPOSE\nx\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_policy_file(bad)


def test_AC_03_02_common_sections_are_exactly_1_3_6_7_8_11_to_15(sections: list[PolicySection]) -> None:
    assert common_section_nos(sections) == COMMON


def test_AC_03_02_edit_in_one_file_makes_section_variable(sections: list[PolicySection]) -> None:
    edited = [
        s.model_copy(update={"content_hash": "0" * 16})
        if (s.product, s.section_no) == ("Car Shield Plus", 13)
        else s
        for s in sections
    ]
    assert common_section_nos(edited) == COMMON - {13}


def test_AC_03_03_62_chunks_12_all_50_product(chunks: list[PolicyChunk]) -> None:
    assert len(chunks) == 62
    common = [c for c in chunks if c.product == "ALL"]
    assert len(common) == 12
    assert all(c.is_common and c.policy_type is None for c in common)
    assert sum(1 for c in chunks if not c.is_common) == 50


def test_AC_03_03_five_chunks_per_product_for_sections_2_4_5_9_10(chunks: list[PolicyChunk]) -> None:
    product_chunks = [c for c in chunks if c.product != "ALL"]
    per_product: dict[str, set[int]] = {}
    for c in product_chunks:
        per_product.setdefault(c.product, set()).add(c.section_no)
        assert c.policy_type in {"Health", "Motor", "Travel"}
    assert len(per_product) == 10
    assert all(nos == VARIABLE for nos in per_product.values())
    # Shared wording ("Not applicable.") still yields one chunk per product.
    maternity_na = [c for c in product_chunks if c.section_no == 5 and c.text == "Not applicable."]
    assert len(maternity_na) == 4


def test_AC_03_03_faq_split_into_three_pairs(chunks: list[PolicyChunk]) -> None:
    faq = sorted((c for c in chunks if c.section_no == 15), key=lambda c: c.chunk_id)
    assert [c.chunk_id for c in faq] == ["all-s15-q1", "all-s15-q2", "all-s15-q3"]
    assert all(c.text.startswith("Q: ") and "\nA: " in c.text for c in faq)
    assert "invent a clause" in faq[2].text
    assert faq[1].header == "All products › §15 Training FAQ › Q2"


def test_AC_03_03_chunk_ids_unique_and_shaped(chunks: list[PolicyChunk]) -> None:
    ids = [c.chunk_id for c in chunks]
    assert len(set(ids)) == len(ids)
    assert "health-secure-plus-s5" in ids
    assert "all-s13" in ids
    assert all(re.fullmatch(r"[a-z0-9-]+-s\d{1,2}(-q\d)?", i) for i in ids)


def test_AC_03_04_embed_text_starts_with_header(chunks: list[PolicyChunk]) -> None:
    for c in chunks:
        assert c.embed_text == f"{c.header}: {c.text}"
    hsp5 = next(c for c in chunks if c.chunk_id == "health-secure-plus-s5")
    assert hsp5.header == "Health Secure Plus (Health) › §5 Maternity"
    assert next(c for c in chunks if c.chunk_id == "all-s13").header == "All products › §13 Human Review"


def test_AC_03_04_citation_label_matches_guardrails_format(chunks: list[PolicyChunk]) -> None:
    guardrails = yaml.safe_load((ROOT / "config" / "guardrails.yaml").read_text(encoding="utf-8"))
    fmt: str = guardrails["citation_format"]
    pattern = re.escape(fmt)
    for field in ("product", "section_no", "section_name"):
        pattern = pattern.replace(re.escape("{" + field + "}"), r"\d+" if field == "section_no" else ".+")
    for c in chunks:
        assert re.fullmatch(pattern, c.citation_label), c.citation_label
        product = "All products" if c.product == "ALL" else c.product
        assert c.citation_label == fmt.format(
            product=product, section_no=c.section_no, section_name=c.section_name
        )
    labels = {c.chunk_id: c.citation_label for c in chunks}
    assert labels["health-secure-plus-s5"] == "[Health Secure Plus §5 Maternity]"
    assert labels["all-s13"] == "[All products §13 Human Review]"
