"""Golden message parity, catalog validation and extension without loader changes."""
import json
import shutil
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path
from unittest.mock import patch

import yaml

from app.prompts import PromptCatalogError, PromptRegistry, PromptRenderError, get_registry
from app.prompts.registry import CATALOG
from app.prompts.parser_v1 import messages, parser_snapshot
from app.services.responses import formatter

FIXTURES = Path(__file__).parent / "fixtures"


class PromptCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "catalog"
        shutil.copytree(CATALOG, self.root)
        self.registry = PromptRegistry(self.root)

    def write(self, filename, data):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    def read(self, filename):
        return yaml.safe_load((self.root / filename).read_text(encoding="utf-8"))

    def context(self):
        return {"reference_date": date(2026, 4, 1), "workshop_vocabulary": {"W1": "Sample"}}

    def test_original_provider_messages_are_identical(self):
        for case in json.loads((FIXTURES / "prompt_messages_v1.json").read_text(encoding="utf-8")):
            with self.subTest(profile=case["profile"], feedback=case["feedback"]):
                self.assertEqual(messages(case["message"], date.fromisoformat(case["reference_date"]),
                                          case["feedback"], profile=case["profile"]), case["expected"])

    def test_original_user_reply_templates_are_identical(self):
        cases = json.loads((FIXTURES / "response_messages_v1.json").read_text(encoding="utf-8"))
        for index, case in enumerate(cases):
            with self.subTest(index=index):
                self.assertEqual(getattr(formatter, case["function"])(**case["args"]), case["expected"])

    def test_prompt_version_and_reply_help_match_catalog(self):
        from app.prompts.parser_v1 import SYSTEM_PROMPT, PROMPT_VERSION
        from app.services.responses.templates import REPLY_HELP
        self.assertTrue(REPLY_HELP)
        self.assertEqual(PROMPT_VERSION, "parser_v1")
        self.assertEqual(SYSTEM_PROMPT, get_registry().get("parsing.request").system)

    def test_catalog_lists_versions_without_runtime_variables(self):
        entries = self.registry.list()
        self.assertEqual(len(entries), 9)
        self.assertEqual(len(self.registry.list(kind="prompt")), 6)
        self.assertTrue(all(item["active"] and len(item["content_hash"]) == 64 for item in entries))
        self.assertNotIn("system", entries[0])
        self.assertTrue({"agent.intent", "allocation.extract", "agent.reply"}.issubset(
            {item["id"] for item in entries}))

    def test_missing_and_unknown_variables_fail_without_echoing_values(self):
        for variables, expected in (({}, "Missing"), ({**self.context(), "extra": "private-value"}, "Unknown")):
            with self.subTest(expected=expected), self.assertRaisesRegex(PromptRenderError, expected) as error:
                self.registry.render("parsing.request", variables=variables)
            self.assertNotIn("private-value", str(error.exception))

    def test_variable_values_and_user_input_are_not_recursively_rendered(self):
        result = self.registry.render("parsing.request", variables={
            "reference_date": "${workshop_vocabulary}", "workshop_vocabulary": {"W1": "${reference_date}"}},
            user_message="${reference_date}")
        self.assertIn("Reference date: ${workshop_vocabulary}", result.messages[0].content)
        self.assertEqual(result.messages[-1].content, "${reference_date}")

    def test_returned_messages_cannot_mutate_cached_definitions(self):
        bundle = self.registry.render("parsing.request", variables=self.context(), user_message="Original")
        changed = bundle.as_messages()
        changed[0]["content"] = "changed"
        bundle.metadata["components"].clear()
        self.assertNotEqual(bundle.as_messages()[0]["content"], "changed")
        self.assertTrue(bundle.metadata["components"])
        with self.assertRaises(FrozenInstanceError):
            self.registry.get("parsing.request").system = "changed"

    def test_arbitrary_new_function_is_discovered_without_loader_changes(self):
        self.write("intent/classify_v1.yaml", {"id": "intent.classify", "version": "intent_v1",
            "description": "Classify a test intent.", "variables": ["categories"],
            "system": "Choose one of ${categories}.", "output_contract": "intent_v1",
            "examples": [{"user": "Allocate", "assistant": {"intent": "allocation"}}]})
        manifest = self.read("manifest.yaml")
        manifest["active"]["intent.classify"] = "intent_v1"
        self.write("manifest.yaml", manifest)
        registry = PromptRegistry(self.root)
        bundle = registry.render("intent.classify", variables={"categories": ["allocation", "history"]},
                                 user_message="What happened yesterday?")
        self.assertEqual(bundle.messages[-1].content, "What happened yesterday?")
        self.assertEqual(json.loads(bundle.messages[2].content), {"intent": "allocation"})
        self.assertEqual(bundle.metadata["output_contract"], "intent_v1")
        self.assertIn("intent.classify", [item["id"] for item in registry.list()])
        # Bundles stay transport-agnostic for ModelRegistry.invoke_task.
        self.assertEqual(bundle.as_messages()[-1]["content"], "What happened yesterday?")
        self.assertEqual(json.loads(bundle.as_messages()[2]["content"]), {"intent": "allocation"})

    def test_active_switch_keeps_old_versions_and_pinned_components(self):
        new_fragment = self.read("parsing/fragment_policy_v1.yaml")
        new_fragment.update(version="parser_v2", system="Different rule.", variables=[])
        self.write("parsing/fragment_policy_v2.yaml", new_fragment)
        manifest = self.read("manifest.yaml")
        manifest["active"]["parsing.fragment_policy"] = "parser_v2"
        self.write("manifest.yaml", manifest)
        registry = PromptRegistry(self.root)
        self.assertEqual(registry.get("parsing.fragment_policy").version, "parser_v2")
        self.assertEqual(registry.snapshot("parsing.request", profile="deepseek").additions[0].version, "parser_v1")
        self.assertEqual(registry.get("parsing.fragment_policy", "parser_v1").version, "parser_v1")
        self.assertEqual(len(registry.list()), 10)
        self.assertEqual(len(registry.list(active_only=True)), 9)

    def test_snapshot_and_retry_use_one_catalog_state(self):
        snapshot = self.registry.snapshot("parsing.request")
        original = snapshot.render(variables=self.context())
        revised = self.read("parsing/request_v1.yaml")
        revised["system"] = "Changed locally."
        self.write("parsing/request_v1.yaml", revised)
        retry = snapshot.render(variables=self.context(), retry_feedback="invalid_json")
        self.assertEqual(original.metadata, retry.metadata)
        self.assertEqual(original.messages[0], retry.messages[0])
        self.assertIn("invalid_json", retry.messages[-1].content)
        self.assertNotEqual(PromptRegistry(self.root).snapshot("parsing.request").metadata, snapshot.metadata)

    def test_render_does_not_read_files_again(self):
        with patch.object(Path, "read_text", side_effect=AssertionError("unexpected file access")):
            self.registry.render("parsing.request", variables=self.context())

    def test_duplicate_definition_is_rejected(self):
        self.write("parsing/duplicate.yaml", self.read("parsing/request_v1.yaml"))
        with self.assertRaisesRegex(PromptCatalogError, "Duplicate"):
            PromptRegistry(self.root)

    def test_duplicate_yaml_keys_and_unsafe_yaml_tags_are_rejected(self):
        for text in ("id: first\nid: second\n", "!!python/object/apply:os.system ['echo should-never-run']", "system: ["):
            with self.subTest(text=text):
                (self.root / "invalid.yaml").write_text(text, encoding="utf-8")
                with self.assertRaises(PromptCatalogError):
                    PromptRegistry(self.root)

    def test_invalid_definitions_are_rejected_at_load(self):
        original = self.read("parsing/request_v1.yaml")
        variants = [{"variables": ["undeclared"]}, {"variables": ["reference_date", "reference_date"]},
                    {"system": "${value.__class__}"}, {"version": True}, {"executable": "anything"},
                    {"kind": "fragment"}, {"profiles": {"default": [{"id": "parsing.request", "version": "parser_v1"}]}},
                    {"retry": {"id": "parsing.retry"}}, {"retry": {"id": "parsing.fragment_policy", "version": "parser_v1"}}]
        for update in variants:
            with self.subTest(update=update):
                self.write("parsing/request_v1.yaml", {**original, **update})
                with self.assertRaises(PromptCatalogError):
                    PromptRegistry(self.root)

    def test_unknown_ids_profiles_and_versions_fail_explicitly(self):
        for identifier, version in (("../outside", None), ("parsing.request", "missing")):
            with self.assertRaises(PromptCatalogError):
                self.registry.get(identifier, version)
        with self.assertRaisesRegex(PromptCatalogError, "profile"):
            self.registry.snapshot("parsing.request", profile="missing")
        with self.assertRaises(PromptCatalogError):
            self.registry.snapshot("parsing.retry")
        manifest = self.read("manifest.yaml")
        manifest["active"]["parsing.request"] = "missing"
        self.write("manifest.yaml", manifest)
        with self.assertRaises(PromptCatalogError):
            PromptRegistry(self.root)

    def test_oversized_and_outside_files_are_rejected(self):
        (self.root / "oversized.yaml").write_text("x" * 256001, encoding="utf-8")
        with self.assertRaisesRegex(PromptCatalogError, "too large"):
            PromptRegistry(self.root)
        with self.assertRaisesRegex(PromptCatalogError, "within"):
            self.registry._read(Path(self.temp.name) / "outside.yaml")

    def test_parser_messages_match_catalog_fixture(self):
        fixture = next(case for case in json.loads((FIXTURES / "prompt_messages_v1.json").read_text(encoding="utf-8"))
                       if case["profile"] == "deepseek" and case["feedback"] is None)
        self.assertEqual(
            messages(fixture["message"], date.fromisoformat(fixture["reference_date"]),
                     fixture["feedback"], profile=fixture["profile"]),
            fixture["expected"])

    def test_parser_snapshot_survives_another_catalog_becoming_active(self):
        with patch("app.prompts.parser_v1.get_registry", return_value=self.registry) as selected:
            snap = parser_snapshot("deepseek")
            before = snap.metadata
            revised = self.read("parsing/retry_v1.yaml")
            revised["system"] = "New retry: ${feedback}"
            self.write("parsing/retry_v1.yaml", revised)
            selected.return_value = PromptRegistry(self.root)
            rendered = messages("ORD-045", date(2026, 4, 1), "invalid_json",
                                profile="deepseek", snapshot=snap)
            self.assertTrue(rendered[-2]["content"].startswith("Previous attempt failed validation:"))
            self.assertEqual(snap.metadata, before)


if __name__ == "__main__":
    unittest.main()
