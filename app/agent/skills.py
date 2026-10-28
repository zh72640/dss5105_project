"""Discover application Skills and pin their exact text for a running conversation."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import yaml

SKILL_ROOT = Path(__file__).resolve().parents[1] / "skills"


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    triggers: str
    tools: tuple[str, ...]
    content: str
    content_hash: str

    def snapshot(self):
        return {"name": self.name, "description": self.description,
                "tools": list(self.tools), "content": self.content, "hash": self.content_hash}


def discover(root=SKILL_ROOT):
    result = {}
    for path in sorted(Path(root).glob("*/SKILL.md")):
        source = path.read_text(encoding="utf-8")
        if not source.startswith("---\n"):
            raise ValueError(f"Invalid Skill front matter: {path}")
        _, header, body = source.split("---", 2)
        data = yaml.safe_load(header)
        name = data["name"]
        if name in result or path.parent.name != name:
            raise ValueError(f"Duplicate or mismatched Skill: {name}")
        result[name] = Skill(name, data["description"], data["triggers"],
                             tuple(data["tools"]), body.strip(), sha256(source.encode()).hexdigest())
    return result


def catalog(root=SKILL_ROOT):
    return [{"name": skill.name, "description": skill.description, "triggers": skill.triggers}
            for skill in discover(root).values()]


def load(name, root=SKILL_ROOT):
    try:
        return discover(root)[name].snapshot()
    except KeyError:
        raise ValueError("SKILL_NOT_FOUND") from None
