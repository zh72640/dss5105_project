"""Compose messages from a pinned snapshot using single-pass variable substitution."""
import hashlib
import json
from dataclasses import dataclass
from datetime import date
from string import Template
from typing import Mapping

from .models import ChatMessage, PromptDefinition, PromptRenderError


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, date):
        return value.isoformat()
    try:
        return json.dumps(value, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PromptRenderError("Prompt variables must be strings, dates or JSON values.") from error


@dataclass(frozen=True)
class PromptSnapshot:
    definition: PromptDefinition
    profile: str
    additions: tuple[PromptDefinition, ...] = ()
    retry: PromptDefinition | None = None

    @property
    def variables(self):
        definitions = (self.definition, *self.additions, *((self.retry,) if self.retry else ()))
        return tuple(sorted({name for item in definitions for name in item.variables} - {"feedback"}))

    @property
    def metadata(self):
        components = [{"id": item.id, "version": item.version, "content_hash": item.content_hash}
                      for item in (self.definition, *self.additions, *((self.retry,) if self.retry else ()))]
        identity = {"id": self.definition.id, "version": self.definition.version,
                    "profile": self.profile, "output_contract": self.definition.output_contract,
                    "components": components}
        encoded = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return {**identity, "content_hash": hashlib.sha256(encoded.encode()).hexdigest()}

    def render(self, *, variables: Mapping[str, object], user_message: str | None = None,
               retry_feedback: str | None = None):
        if not isinstance(variables, Mapping) or any(not isinstance(key, str) for key in variables):
            raise PromptRenderError("Prompt variables must be a mapping with string keys.")
        if user_message is not None and not isinstance(user_message, str):
            raise PromptRenderError("The user message must be a string.")
        if retry_feedback is not None and not isinstance(retry_feedback, str):
            raise PromptRenderError("Retry feedback must be a string.")
        if retry_feedback and self.retry is None:
            raise PromptRenderError("This prompt has no retry definition.")
        used = (self.definition, *self.additions, *((self.retry,) if retry_feedback else ()))
        required = {name for item in used for name in item.variables} - {"feedback"}
        missing = required - variables.keys()
        unknown = variables.keys() - set(self.variables)
        if missing:
            raise PromptRenderError("Missing prompt variables: " + ", ".join(sorted(missing)))
        if unknown:
            raise PromptRenderError("Unknown prompt variables: " + ", ".join(sorted(unknown)))
        values = {name: _text(value) for name, value in variables.items()}
        if retry_feedback:
            values["feedback"] = retry_feedback
        def body(item):
            return Template(item.system + item.context).substitute(values)
        system = body(self.definition) + "".join(body(item) for item in self.additions)
        messages = [ChatMessage("system", system)]
        for example in self.definition.examples:
            messages.extend((ChatMessage("user", example.user), ChatMessage("assistant", example.assistant)))
        if retry_feedback:
            messages.append(ChatMessage("system", body(self.retry)))
        if user_message is not None:
            messages.append(ChatMessage("user", user_message))
        return RenderedPrompt(tuple(messages), self)


@dataclass(frozen=True)
class RenderedPrompt:
    messages: tuple[ChatMessage, ...]
    snapshot: PromptSnapshot

    @property
    def metadata(self):
        return self.snapshot.metadata

    def as_messages(self):
        """Return fresh transport dictionaries so callers cannot mutate the catalog."""
        return [{"role": message.role, "content": message.content} for message in self.messages]
