"""Discover versioned YAML definitions and resolve explicit component versions."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from .models import FewShot, PromptCatalogError, PromptDefinition, PromptReference
from .renderer import PromptSnapshot

CATALOG = Path(__file__).parent / "catalog"
Identifier = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")]
Version = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")]
Variable = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class _Reference(_Input):
    id: Identifier
    version: Version


class _Example(_Input):
    user: str = Field(min_length=1)
    assistant: JsonValue


class _Definition(_Input):
    id: Identifier
    version: Version
    kind: Literal["prompt", "fragment"] = "prompt"
    description: str = Field(min_length=1)
    variables: list[Variable] = Field(default_factory=list)
    system: str = Field(min_length=1)
    context: str = ""
    examples: list[_Example] = Field(default_factory=list)
    profiles: dict[Variable, list[_Reference]] = Field(default_factory=dict)
    retry: _Reference | None = None
    output_contract: Version | None = None

    @model_validator(mode="after")
    def consistent(self):
        if not self.system.strip() or len(set(self.variables)) != len(self.variables):
            raise ValueError("Empty system text or duplicate variables.")
        template = Template(self.system + self.context)
        if not template.is_valid() or set(template.get_identifiers()) != set(self.variables):
            raise ValueError("Declared variables must match the template placeholders.")
        if self.kind == "fragment" and (self.examples or self.profiles or self.retry or self.output_contract):
            raise ValueError("Fragments cannot contain examples, profiles, retries or output contracts.")
        if self.kind == "prompt" and "feedback" in self.variables:
            raise ValueError("feedback is reserved for retry fragments.")
        if self.profiles and "default" not in self.profiles:
            raise ValueError("A profiled prompt must define the default profile.")
        return self


class _Manifest(_Input):
    format_version: int = Field(ge=1, le=1)
    active: dict[Identifier, Version] = Field(min_length=1)


class _StrictSafeLoader(yaml.SafeLoader):
    """Keep SafeLoader's tag restrictions and also reject duplicate mapping keys."""


def _mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise PromptCatalogError("YAML mapping keys must be unique strings.")
        result[key] = loader.construct_object(value_node)
    return result


_StrictSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


class PromptRegistry:
    def __init__(self, catalog_dir=CATALOG):
        self._root = Path(catalog_dir).resolve()
        self._definitions = {}
        try:
            manifest = _Manifest.model_validate(self._read(self._root / "manifest.yaml"))
        except ValidationError as error:
            raise PromptCatalogError("Invalid prompt manifest.") from error
        self._active = dict(manifest.active)
        for path in sorted(self._root.rglob("*")):
            if path.suffix not in (".yaml", ".yml") or path.name == "manifest.yaml":
                continue
            raw = self._read(path)
            try:
                entry = _Definition.model_validate(raw)
                encoded = json.dumps(entry.model_dump(), sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False)
                examples = tuple(FewShot(item.user, item.assistant if isinstance(item.assistant, str)
                                         else json.dumps(item.assistant, allow_nan=False)) for item in entry.examples)
            except (ValidationError, TypeError, ValueError) as error:
                raise PromptCatalogError("Invalid prompt definition: " + path.name) from error
            definition = PromptDefinition(entry.id, entry.version, entry.kind, entry.description,
                tuple(entry.variables), entry.system, entry.context, examples,
                tuple((name, tuple(PromptReference(r.id, r.version) for r in refs))
                      for name, refs in entry.profiles.items()),
                PromptReference(entry.retry.id, entry.retry.version) if entry.retry else None,
                entry.output_contract, hashlib.sha256(encoded.encode()).hexdigest())
            key = (definition.id, definition.version)
            if key in self._definitions:
                raise PromptCatalogError("Duplicate prompt ID/version: " + definition.id)
            self._definitions[key] = definition
        for identifier, version in self._active.items():
            self.get(identifier, version)
        for definition in self._definitions.values():
            for _, references in definition.profiles:
                if len(set(references)) != len(references):
                    raise PromptCatalogError("Duplicate profile component: " + definition.id)
                for reference in references:
                    fragment = self._fragment(reference)
                    if "feedback" in fragment.variables:
                        raise PromptCatalogError("Profile fragments cannot use retry feedback.")
            if definition.retry and "feedback" not in self._fragment(definition.retry).variables:
                raise PromptCatalogError("A retry fragment must declare feedback.")

    def _read(self, path):
        if not path.resolve().is_relative_to(self._root):
            raise PromptCatalogError("Prompt files must stay within the catalog directory.")
        try:
            if path.stat().st_size > 256_000:
                raise PromptCatalogError("Prompt file is too large: " + path.name)
            return yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictSafeLoader)
        except (OSError, UnicodeError, yaml.YAMLError, TypeError) as error:
            raise PromptCatalogError("Cannot read prompt YAML: " + path.name) from error

    def get(self, identifier, version=None):
        if version is None:
            version = self._active.get(identifier)
        definition = self._definitions.get((identifier, version))
        if definition is None:
            raise PromptCatalogError("Unknown prompt ID/version: " + str(identifier))
        return definition

    def _fragment(self, reference):
        definition = self.get(reference.id, reference.version)
        if definition.kind != "fragment":
            raise PromptCatalogError("A prompt component must reference a fragment: " + reference.id)
        return definition

    def list(self, *, kind=None, active_only=False):
        return [{"id": item.id, "version": item.version, "kind": item.kind,
                 "description": item.description, "variables": list(item.variables),
                 "profiles": [name for name, _ in item.profiles], "output_contract": item.output_contract,
                 "content_hash": item.content_hash, "active": self._active.get(item.id) == item.version}
                for _, item in sorted(self._definitions.items())
                if (kind is None or item.kind == kind) and
                   (not active_only or self._active.get(item.id) == item.version)]

    def snapshot(self, identifier, version=None, *, profile="default"):
        definition = self.get(identifier, version)
        if definition.kind != "prompt":
            raise PromptCatalogError("Render a root prompt rather than a fragment: " + identifier)
        profiles = dict(definition.profiles) or {"default": ()}
        if profile not in profiles:
            raise PromptCatalogError("Unknown prompt profile: " + str(profile))
        return PromptSnapshot(definition, profile,
            tuple(self._fragment(reference) for reference in profiles[profile]),
            self._fragment(definition.retry) if definition.retry else None)

    def render(self, identifier, *, variables, user_message=None, profile="default",
               retry_feedback=None, version=None):
        return self.snapshot(identifier, version, profile=profile).render(
            variables=variables, user_message=user_message, retry_feedback=retry_feedback)


@lru_cache(maxsize=1)
def get_registry():
    """Cache one validated catalog; construct a new registry to preview another catalog."""
    return PromptRegistry()
