# 03 – Policy knowledge: parsing, chunks and coverage matrix

Milestone: M2 · Depends on: data/raw/policy_documents, config/coverage_matrix.yaml · ADR: none

## Goal
Turn the 10 policy wordings into (a) section records, (b) retrieval chunks with contextual headers and
rich payload, and (c) a reviewed coverage matrix that answers comparisons and feeds the rules engine.

## Facts about the corpus (verified)
- 10 files, about 2.2 KB each, identical 15 numbered headings (`1. PURPOSE` … `15. TRAINING FAQ`).
- Line 1: product name; line 2: `Policy Type: Health|Motor|Travel`. Product names match policies.csv exactly.
- Sections 1, 3, 6, 7, 8, 11, 12, 13, 14, 15 are byte-identical in all 10 files. Sections 2, 4, 5, 9, 10 vary.
- §14 requires any assistant to cite sections and never guarantee approval; §13 requires escalation; §15 forbids invented clauses.

## Interfaces
```python
# src/insurai/knowledge/schemas.py
class PolicySection(BaseModel):
    product: str; policy_type: Literal["Health", "Motor", "Travel"]
    section_no: int; section_name: str; text: str; content_hash: str; source_path: str
class PolicyChunk(BaseModel):
    chunk_id: str                   # "health-secure-plus-s5", "all-s13", "all-s15-q2"
    product: str                    # canonical product name or "ALL"
    policy_type: str | None         # None for ALL
    section_no: int; section_name: str; is_common: bool
    text: str                       # clause text only
    header: str                     # "Health Secure Plus (Health) › §5 Maternity"
    embed_text: str                 # f"{header}: {text}"  ← what gets embedded
    citation_label: str             # "[Health Secure Plus §5 Maternity]" / "[All products §13 Human Review]"
    content_hash: str; source_path: str

# src/insurai/knowledge/parse.py
def parse_policy_file(path: Path) -> list[PolicySection]: ...
def parse_corpus(dir: Path) -> list[PolicySection]: ...
def build_chunks(sections: list[PolicySection]) -> list[PolicyChunk]: ...

# src/insurai/knowledge/coverage.py
class CoverageMatrix(BaseModel): ...             # strict schema for config/coverage_matrix.yaml
def load_coverage(path: Path) -> CoverageMatrix: ...
def coverage_grid(m: CoverageMatrix) -> list[CoverageGridRow]: ...   # same function spec 01 uses
def get_coverage(product: str | None, attribute: str | None) -> list[CoverageCell]: ...  # backs the tool
def extract_coverage_draft(sections: list[PolicySection]) -> CoverageMatrix: ...      # LLM, one-off
```

## Behaviour
1. Heading regex (multiline): `^(\d{1,2})\.\s+([A-Z][A-Z /&-]+?)\s*$`. Body = text until the next heading, stripped.
2. `section_name` = heading in title case, keeping acronyms upper (`FAQ`), slashes spaced: "Hospitalization / Loss Coverage", "Training FAQ".
3. Normalise text for hashing: collapse whitespace, strip. `content_hash` = sha256[:16].
4. A (section_no, content_hash) present in all 10 products → common: emit ONE chunk with product "ALL".
   §15 (common) is split into its three Q/A pairs → chunks `all-s15-q1..q3`.
5. Variable sections (2, 4, 5, 9, 10) → one chunk per product even when two products share wording
   (e.g. "Not applicable."), because the product label is the retrieval key.
6. Result: 12 common chunks (9 sections + 3 FAQ pairs) + 50 product chunks = 62 chunks.
7. Coverage matrix workflow:
   - `make coverage-draft` runs `extract_coverage_draft` (LLM role generator, structured output) over the
     variable sections and writes `data/coverage_draft.yaml`, then prints a field-level diff against
     `config/coverage_matrix.yaml`.
   - A person reviews the committed YAML line by line against the wordings and sets `status: reviewed`.
   - At runtime, a `draft` status logs a warning and is shown in the eval report header.
8. `get_coverage` returns cells with `SourceRef(kind="policy", product, section_no, section_name, label)`;
   comparison answers cite these labels.

## Acceptance criteria
- [x] AC-03-01 Every file parses to exactly 15 sections; product and policy type match policies.csv (10/10).
- [x] AC-03-02 Common detection returns exactly sections {1, 3, 6, 7, 8, 11, 12, 13, 14, 15}.
- [x] AC-03-03 `build_chunks` returns 62 chunks: 12 with product ALL, 50 product chunks (5 per product).
- [x] AC-03-04 Every `embed_text` starts with its header; every `citation_label` matches config/guardrails.yaml `citation_format`.
- [x] AC-03-05 `config/coverage_matrix.yaml` validates; every product in policies.csv is present; every exclusion list matches the §9 text split on commas (unit test reads the wordings).
- [x] AC-03-06 Manual gate: coverage matrix reviewed against the wordings and `status: reviewed` committed.
- [x] AC-03-07 `coverage_grid` meets AC-01-05 (shared test).
- [~] deferred: 3-day scope. AC-03-08 `extract_coverage_draft` agrees with the committed matrix on ≥ 90% of fields (reported, not gated).
- [x] AC-03-09 `get_coverage("Health Secure Plus", "maternity")` returns status covered, 24 months, label `[Health Secure Plus §5 Maternity]`.
- [x] AC-03-10 Each §15 FAQ pair has its own citation label (`faq_citation_format`, e.g. `[All products §15 Training FAQ Q2]`); `section_name` stays "Training FAQ".

## Eval hooks
Comparisons slice (10 items) reads gold from the reviewed matrix.

## Open questions
- Critical illness list for Critical Care Elite (#6) and specified-disease list (assumption A2) need business confirmation.
  - Resolved for the PoC (2026-10-04): assumptions A1 (accident-exempt diagnoses), A2 (specified diseases:
    Cataract, Kidney Stone) and A3 (Critical Care Elite: Cardiac Procedure only) are accepted as written in
    config/coverage_matrix.yaml. Business confirmation is still needed before production.
