"""Immutable runtime definitions; catalog files contain data, never executable code."""
from dataclasses import dataclass


class PromptCatalogError(ValueError):
    """A catalog definition, version or reference is invalid."""


class PromptRenderError(ValueError):
    """A prompt cannot be rendered with the supplied variables."""


@dataclass(frozen=True)
class PromptReference:
    id: str
    version: str


@dataclass(frozen=True)
class FewShot:
    user: str
    assistant: str


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class PromptDefinition:
    id: str
    version: str
    kind: str
    description: str
    variables: tuple[str, ...]
    system: str
    context: str
    examples: tuple[FewShot, ...]
    profiles: tuple[tuple[str, tuple[PromptReference, ...]], ...]
    retry: PromptReference | None
    output_contract: str | None
    content_hash: str
