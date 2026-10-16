"""Active Chat and Agent prompt catalog behavior."""
import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import yaml

from app.prompts import PromptCatalogError, PromptRegistry, PromptRenderError
from app.prompts.registry import CATALOG


class PromptCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "catalog"
        shutil.copytree(CATALOG, self.root)
        self.registry = PromptRegistry(self.root)

    def read(self, name):
        return yaml.safe_load((self.root / name).read_text(encoding="utf-8"))

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")

    def render(self, message="Allocate ORD-045."):
        return self.registry.render("agent.intent", variables={
            "task": {"state": "COLLECTING"}, "output_schema": {"type": "object"}},
            user_message=message)

    def test_active_catalog_and_no_parser_v1(self):
        entries = self.registry.list()
        self.assertEqual(len(entries), 6)
        self.assertEqual(len(self.registry.list(kind="prompt")), 5)
        self.assertTrue(all(item["active"] and len(item["content_hash"]) == 64 for item in entries))
        self.assertFalse(any(item["id"].startswith("parsing.") for item in entries))

    def test_render_is_immutable_and_single_pass(self):
        bundle = self.render("${task}")
        self.assertEqual(bundle.messages[-1].content, "${task}")
        changed = bundle.as_messages()
        changed[0]["content"] = "changed"
        bundle.metadata["components"].clear()
        self.assertNotEqual(bundle.as_messages()[0]["content"], "changed")
        self.assertTrue(bundle.metadata["components"])
        with self.assertRaises(FrozenInstanceError):
            self.registry.get("agent.intent").system = "changed"

    def test_variables_fail_without_exposing_values(self):
        for variables, expected in (({}, "Missing"),
                                    ({"task": {}, "output_schema": {}, "extra": "private-value"}, "Unknown")):
            with self.subTest(expected=expected), self.assertRaisesRegex(PromptRenderError, expected) as error:
                self.registry.render("agent.intent", variables=variables)
            self.assertNotIn("private-value", str(error.exception))

    def test_new_function_and_version_are_discovered(self):
        self.write("intent/classify_v1.yaml", {"id": "intent.classify", "version": "intent_v1",
            "description": "Classify a test intent.", "variables": ["categories"],
            "system": "Choose one of ${categories}.", "output_contract": "intent_v1",
            "examples": [{"user": "Allocate", "assistant": {"intent": "allocation"}}]})
        manifest = self.read("manifest.yaml")
        manifest["active"]["intent.classify"] = "intent_v1"
        self.write("manifest.yaml", manifest)
        bundle = PromptRegistry(self.root).render("intent.classify",
            variables={"categories": ["allocation", "history"]}, user_message="What happened?")
        self.assertEqual(bundle.as_messages()[-1]["content"], "What happened?")
        self.assertEqual(json.loads(bundle.as_messages()[2]["content"]), {"intent": "allocation"})

    def test_snapshot_is_pinned(self):
        snapshot = self.registry.snapshot("agent.intent")
        before = snapshot.metadata
        definition = self.read("agent/intent_v1.yaml")
        definition["system"] = "Changed locally: ${task} ${output_schema}"
        self.write("agent/intent_v1.yaml", definition)
        self.assertEqual(snapshot.metadata, before)
        self.assertNotEqual(PromptRegistry(self.root).snapshot("agent.intent").metadata, before)

    def test_active_fragment_switch_preserves_pinned_conversation(self):
        fragment = self.read("conversation/intent_v2.yaml")
        fragment.update(version="chat_v3", system="Updated intent guidance.")
        self.write("conversation/intent_v3.yaml", fragment)
        manifest = self.read("manifest.yaml")
        manifest["active"]["conversation.intent"] = "chat_v3"
        self.write("manifest.yaml", manifest)
        registry = PromptRegistry(self.root)
        self.assertEqual(registry.get("conversation.intent").version, "chat_v3")
        self.assertEqual(registry.snapshot("conversation.interpret").additions[0].version, "chat_v2")
        self.assertEqual(len(registry.list(active_only=True)), 6)

    def test_retry_fragment_is_pinned_to_snapshot(self):
        self.write("agent/retry_v1.yaml", {"id": "agent.retry", "version": "v1", "kind": "fragment",
            "description": "Retry a failed classification.", "variables": ["feedback"],
            "system": "Correct the previous output: ${feedback}"})
        definition = self.read("agent/intent_v1.yaml")
        definition["retry"] = {"id": "agent.retry", "version": "v1"}
        self.write("agent/intent_v1.yaml", definition)
        registry = PromptRegistry(self.root)
        snapshot = registry.snapshot("agent.intent")
        variables = {"task": {}, "output_schema": {"type": "object"}}
        original = snapshot.render(variables=variables)
        retry = snapshot.render(variables=variables, user_message="Allocate ORD-045.",
                                retry_feedback="invalid_json")
        self.assertEqual(original.metadata, retry.metadata)
        self.assertEqual(original.messages[0], retry.messages[0])
        self.assertIn("invalid_json", retry.messages[-2].content)

    def test_render_does_not_read_files_again(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected file access")):
            self.render()

    def test_bad_catalog_entries_are_rejected(self):
        self.write("agent/duplicate.yaml", self.read("agent/intent_v1.yaml"))
        with self.assertRaisesRegex(PromptCatalogError, "Duplicate"):
            PromptRegistry(self.root)
        (self.root / "agent/duplicate.yaml").unlink()
        for invalid in ("id: first\nid: second\n", "!!python/object/apply:os.system ['echo bad']", "system: ["):
            with self.subTest(invalid=invalid):
                (self.root / "invalid.yaml").write_text(invalid, encoding="utf-8")
                with self.assertRaises(PromptCatalogError):
                    PromptRegistry(self.root)
                (self.root / "invalid.yaml").unlink()

    def test_invalid_definitions_and_manifest_are_rejected(self):
        original = self.read("agent/intent_v1.yaml")
        for update in ({"variables": ["undeclared"]}, {"variables": ["task", "task"]},
                       {"system": "${value.__class__}"}, {"version": True},
                       {"profiles": {"default": [{"id": "agent.intent", "version": "v1"}]}}):
            with self.subTest(update=update):
                self.write("agent/intent_v1.yaml", {**original, **update})
                with self.assertRaises(PromptCatalogError):
                    PromptRegistry(self.root)
        self.write("agent/intent_v1.yaml", original)
        manifest = self.read("manifest.yaml")
        manifest["active"]["agent.intent"] = "missing"
        self.write("manifest.yaml", manifest)
        with self.assertRaises(PromptCatalogError):
            PromptRegistry(self.root)

    def test_unknown_and_oversized_files_are_rejected(self):
        with self.assertRaises(PromptCatalogError):
            self.registry.get("agent.intent", "missing")
        with self.assertRaises(PromptCatalogError):
            self.registry.snapshot("agent.intent", profile="missing")
        (self.root / "oversized.yaml").write_text("x" * 256001, encoding="utf-8")
        with self.assertRaisesRegex(PromptCatalogError, "too large"):
            PromptRegistry(self.root)


if __name__ == "__main__":
    unittest.main()
