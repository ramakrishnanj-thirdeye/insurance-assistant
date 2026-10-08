"""config/semantic_model.yaml: tables, columns, metrics, filters, allowed joins, verified queries (spec 02).

What a persona may query is the model minus its personas.yaml `hidden_columns` and `analytics_hidden_tables`;
`blocked_columns` are never allowed for anyone.
"""

from functools import lru_cache
from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from insurai.semantic.schemas import Column, Relationship, TableModel, VerifiedQuery
from insurai.settings import ROOT
from insurai.tools.access import load_personas
from insurai.tools.schemas import Persona

SEMANTIC_MODEL_FILE = ROOT / "config" / "semantic_model.yaml"


class SemanticModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    tables: list[TableModel]
    relationships: list[Relationship]
    verified_queries: list[VerifiedQuery]

    @classmethod
    def load(cls, path: Path = SEMANTIC_MODEL_FILE) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    @model_validator(mode="after")
    def _check_references(self) -> Self:
        names = [t.name for t in self.tables]
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate table names: {names}")
        columns = {t.name: {c.name for c in t.columns} for t in self.tables}
        for t in self.tables:
            seen = [c.name for c in t.columns]
            if len(set(seen)) != len(seen):
                raise ValueError(f"{t.name}: duplicate column names")
            if t.primary_key and not set(t.primary_key.columns) <= columns[t.name]:
                raise ValueError(f"{t.name}: primary key not among its columns")
            if overlap := set(t.blocked_columns) & columns[t.name]:
                raise ValueError(f"{t.name}: blocked columns also declared as columns: {sorted(overlap)}")
        for r in self.relationships:
            for side, table in (("left", r.left_table), ("right", r.right_table)):
                if table not in columns:
                    raise ValueError(f"relationship {r.name}: unknown {side} table {table!r}")
            for jc in r.relationship_columns:
                if (
                    jc.left_column not in columns[r.left_table]
                    or jc.right_column not in columns[r.right_table]
                ):
                    raise ValueError(f"relationship {r.name}: unknown column in {jc}")
        if len({q.name for q in self.verified_queries}) != len(self.verified_queries):
            raise ValueError("duplicate verified query names")
        return self

    # --- access --------------------------------------------------------------------------------------

    def table(self, name: str) -> TableModel:
        return next(t for t in self.tables if t.name == name)

    def allowed_tables(self) -> dict[str, str]:
        """Logical name -> "schema.table" for every table in the model."""
        return {t.name: t.base_table.qualified for t in self.tables}

    def tables_for(self, persona: Persona) -> dict[str, str]:
        """allowed_tables() minus the persona's `analytics_hidden_tables`."""
        hidden = set(load_personas()[persona].analytics_hidden_tables)
        return {k: v for k, v in self.allowed_tables().items() if k not in hidden}

    def allowed_columns(self, persona: Persona) -> dict[str, set[str]]:
        """Logical table -> selectable columns for the persona (hidden and blocked columns removed)."""
        hidden = set(load_personas()[persona].hidden_columns)
        return {
            t.name: {c.name for c in t.columns} - hidden - set(t.blocked_columns)
            for t in self.tables
            if t.name in self.tables_for(persona)
        }

    def allowed_joins(self) -> set[frozenset[tuple[str, str]]]:
        """Each declared join column pair as {(table, col), (table, col)}; direction does not matter."""
        return {
            frozenset({(r.left_table, jc.left_column), (r.right_table, jc.right_column)})
            for r in self.relationships
            for jc in r.relationship_columns
        }

    # --- prompt --------------------------------------------------------------------------------------

    def prompt_context(self, persona: Persona | None = None) -> str:
        """Compact text for the text-to-SQL prompt: tables, columns, enums, synonyms, filters, metrics, joins.
        With a persona, hidden tables and columns are left out."""
        tables = self.tables_for(persona) if persona else self.allowed_tables()
        cols = self.allowed_columns(persona) if persona else None
        lines: list[str] = []
        for t in self.tables:
            if t.name not in tables:
                continue
            lines.append(f"TABLE {t.base_table.qualified} -- {t.description.strip()}")
            for c in t.columns:
                if cols is not None and c.name not in cols[t.name]:
                    continue
                lines.append("  " + _column_line(c))
            lines += [f"  metric {m.name} = {m.expr}" for m in t.metrics]
            lines += [f"  filter {f.name}: {f.expr}{_synonyms(f.synonyms)}" for f in t.filters]
        lines.append("JOINS (the only allowed join conditions):")
        for r in self.relationships:
            if r.left_table in tables and r.right_table in tables:
                on = " AND ".join(
                    f"{tables[r.left_table]}.{jc.left_column} = {tables[r.right_table]}.{jc.right_column}"
                    for jc in r.relationship_columns
                )
                lines.append(f"  {on}")
        return "\n".join(lines)


def _synonyms(words: list[str]) -> str:
    return f" (synonyms: {', '.join(words)})" if words else ""


def _column_line(c: Column) -> str:
    parts = [f"{c.name} {c.data_type}"]
    if c.description:
        parts.append(f"-- {c.description}")
    if c.sample_values:
        parts.append(f"values: {', '.join(map(str, c.sample_values))}")
    return " ".join(parts) + _synonyms(c.synonyms)


@lru_cache(maxsize=1)
def load_semantic_model() -> SemanticModel:
    return SemanticModel.load()
