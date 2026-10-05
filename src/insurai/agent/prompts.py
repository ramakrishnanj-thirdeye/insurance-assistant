"""Versioned prompt files in config/prompts (front matter `id`, `version`; `## name` template sections)."""

import re
from functools import cache, lru_cache

import yaml
from pydantic import BaseModel

from insurai.settings import ROOT

PROMPTS_DIR = ROOT / "config" / "prompts"
_FRONT = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class Prompt(BaseModel):
    id: str
    version: str
    body: str

    def render(self, **values: object) -> str:
        """Fill `{name}` placeholders for the given names only; other braces (examples) stay as written."""
        return render(self.body, **values)


@cache
def load_prompt(name: str) -> Prompt:
    text = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")
    match = _FRONT.match(text)
    if match is None:
        raise ValueError(f"prompt {name} has no front matter")
    meta = yaml.safe_load(match.group(1))
    return Prompt(id=str(meta["id"]), version=str(meta["version"]), body=text[match.end() :])


@lru_cache(maxsize=1)
def templates() -> dict[str, str]:
    """`## name` sections of templates.md; the first line after the heading is the template."""
    sections: dict[str, str] = {}
    for block in re.split(r"^## ", load_prompt("templates").body, flags=re.MULTILINE)[1:]:
        name, _, rest = block.partition("\n")
        sections[name.strip()] = rest.strip().splitlines()[0].strip()
    return sections


def template(name: str, **values: object) -> str:
    return render(templates()[name], **values)


def render(text: str, **values: object) -> str:
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text
