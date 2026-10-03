"""config/semantic_model.yaml loader.

Minimal for spec 04: it reads `verified_queries` only. Spec 02 (M6) adds tables, personas and validation.
"""

from pathlib import Path
from typing import Self

import yaml
from pydantic import BaseModel, ConfigDict

from insurai.semantic.schemas import VerifiedQuery
from insurai.settings import ROOT

SEMANTIC_MODEL_FILE = ROOT / "config" / "semantic_model.yaml"


class SemanticModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    verified_queries: list[VerifiedQuery]

    @classmethod
    def load(cls, path: Path = SEMANTIC_MODEL_FILE) -> Self:
        return cls.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
