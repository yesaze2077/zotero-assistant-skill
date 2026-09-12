import argparse
from datetime import timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("zassistant", Path(__file__).resolve().parents[1]/"scripts/assistant.py")
a = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(a)


def read_args(action, **kwargs):
    return argparse.Namespace(action=action, key="ABCD1234", query=None, limit=5, offset=0, start=0, chars=100, **kwargs)


class AssistantTests(unittest.TestCase):
    def test_background_cannot_create_usage_or_ignore_inactivity(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a, "github") as net:
            result = a.scan_updates(Path(d), recent_only=True, force=True)
            self.assertEqual(result["reason"], "no_recent_use")
            self.assertFalse((Path(d)/"usage.json").exists())
            net.assert_not_called()

    def test_begin_preserves_scan_and_marks_only_user_use(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            a.atomic_json(p/"usage.json", {"last_scan_at": a.stamp()})
            self.assertFalse(a.begin(p)["scan_due"])
            self.assertIn("last_used_at", a.read_json(p/"usage.json"))

    def test_failed_scan_is_not_success_and_does_not_activate(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a, "github", side_effect=ValueError("offline")):
            before = (a.ROOT/"registry.json").read_bytes()
            result = a.scan_updates(Path(d))
            state = a.read_json(Path(d)/"usage.json")
            self.assertFalse(result["ok"])
            self.assertNotIn("last_scan_at", state)
            self.assertEqual(a.due(state)[1], "retry_backoff")
            self.assertEqual(before, (a.ROOT/"registry.json").read_bytes())

    def test_discovery_is_deduplicated_without_execution(self):
        def response(endpoint, **params):
            if endpoint == "search/repositories":
                return {"items": [{"full_name": "example/zotero-new", "html_url": "https://github.com/example/zotero-new", "archived": False}]}
            if endpoint.endswith("/commits"):
                return [{"sha": "abc"}]
            return {"archived": False, "license": {"spdx_id": "MIT"}}
        with tempfile.TemporaryDirectory() as d, patch.object(a, "github", side_effect=response), patch.object(a, "run") as execute:
            first = a.scan_updates(Path(d))
            second = a.scan_updates(Path(d), force=True)
            self.assertEqual(len(first["changes"]), 1)
            self.assertEqual(second["changes"], [])
            self.assertFalse(first["automatic_activation"])
            execute.assert_not_called()

    def test_remote_change_requires_review(self):
        call = {"sha": "old"}
        def response(endpoint, **params):
            if endpoint == "search/repositories": return {"items": []}
            if endpoint.endswith("/commits"): return [{"sha": call["sha"]}]
            return {"archived": False, "license": {"spdx_id": "MIT"}}
        with tempfile.TemporaryDirectory() as d, patch.object(a, "github", side_effect=response):
            a.scan_updates(Path(d))
            call["sha"] = "new"
            result = a.scan_updates(Path(d), force=True)
            self.assertTrue(result["changes"])
            self.assertTrue(all(x["status"] == "review_required" for x in result["changes"]))

    def test_candidates_never_become_routes(self):
        for entry in a.catalog()["entries"]:
            if entry["approval_status"] not in {"available-if-installed", "active-existing", "active-approved"}:
                self.assertFalse(entry["execution_allowed"])
                self.assertEqual(entry["enabled_capabilities"], [])

    def test_portable_catalog_requires_actual_local_capability(self):
        with patch.object(a, "executable", return_value=None):
            self.assertFalse(any(e["execution_allowed"] for e in a.catalog()["entries"]))
        with patch.object(a, "executable", return_value="/example/bin/tool"):
            entries = {e["id"]: e for e in a.catalog()["entries"]}
            self.assertTrue(entries["54yyyu-zotero-cli"]["execution_allowed"])
            self.assertFalse(entries["existing-document-skills"]["execution_allowed"])

    def test_recent_fills_papers_and_keeps_pagination(self):
        rows = [{"key": f"KEY0000{i}", "data": {"itemType": kind}} for i, kind in enumerate(["note", "attachment", "journalArticle", "note", "book", "report", "note", "book", "journalArticle", "book"])]
        def get(path, **kw):
            return rows[kw["start"]:kw["start"]+kw["limit"]], {"Total-Results": str(len(rows))}
        with patch.object(a, "local_get", side_effect=get):
            result = a.library_read(read_args("recent"))
        self.assertEqual(result["count"], 5)
        self.assertEqual(result["next_offset"], 9)
        self.assertTrue(result["has_more"])

    def test_bad_read_key_never_reaches_api(self):
        args = read_args("item")
        args.key = "../../config"
        with patch.object(a, "local_get") as get, self.assertRaises(ValueError):
            a.library_read(args)
        get.assert_not_called()

    def test_fulltext_upstream_success_with_no_text_is_failure(self):
        with patch.object(a, "executable", return_value="cli"), patch.object(a, "run", return_value=(0, json.dumps({"ok": True, "data": {"text": "No full text available for this item."}}), "")):
            self.assertFalse(a.cli_read("fulltext", "ABCD1234")["ok"])

    def test_text_windows_retain_coverage_and_continue(self):
        with patch.object(a, "executable", return_value="cli"), patch.object(a, "run", return_value=(0, json.dumps({"data": {"text": "# Metadata\n\n## Full Text\n\nabcdefghij"}}), "")):
            result = a.cli_read("fulltext", "ABCD1234", 2, 3)
        self.assertEqual(result["text"], "cde")
        self.assertEqual(result["next_start"], 5)
        self.assertEqual(result["pdf_page_coverage"], "not_verified")

    def test_metadata_and_note_body_never_count_as_fulltext(self):
        for text in ("# Title\nAbstract with plenty of interesting research words.\nNo suitable attachment found for this item.", "# A standalone note\nA long research note.", "# Metadata\n\n## Full Text\n\n"):
            with patch.object(a, "executable", return_value="cli"), patch.object(a, "run", return_value=(0, json.dumps({"ok": True, "data": {"text": text}}), "")):
                self.assertFalse(a.cli_read("fulltext", "ABCD1234")["ok"])

    def test_path_without_existing_file_is_not_success(self):
        with patch.object(a, "executable", return_value="cli"), patch.object(a, "run", return_value=(0, json.dumps({"data": {"text": "No attachments found for this item."}}), "")):
            self.assertFalse(a.cli_read("path", "ABCD1234")["ok"])

    def test_lesson_rejects_sensitive_and_unverified_assertions(self):
        record = a.read_json(a.ROOT/"lessons/connection-config-is-not-health.json")
        for field, value in [("symptom", "log /Users/privateperson/file.txt"), ("cause", "api_key=unsafe-value"), ("verification", {})]:
            bad = {**record, field: value}
            with self.assertRaises(ValueError):
                a.validate_lesson(bad)

    def test_lesson_add_dedupes_and_refuses_conflicting_overwrite(self):
        record = a.read_json(a.ROOT/"lessons/connection-config-is-not-health.json")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a.atomic_json(root/"input.json", record)
            args = argparse.Namespace(lesson_action="add", file=str(root/"input.json"))
            with patch.object(a, "ROOT", root):
                self.assertEqual(a.lessons(args)["status"], "recorded")
                self.assertEqual(a.lessons(args)["status"], "already_recorded")
                a.atomic_json(root/"input.json", {**record, "cause": "different diagnosis"})
                with self.assertRaises(ValueError): a.lessons(args)

    def test_nested_credential_fields_are_rejected(self):
        record = a.read_json(a.ROOT/"lessons/connection-config-is-not-health.json")
        for key in ("api_key", "password", "access_token"):
            with self.assertRaises(ValueError):
                a.validate_lesson({**record, "debug": [{key: "private-value"}]})

    def test_retire_preserves_history_and_excludes_old_advice(self):
        record = a.read_json(a.ROOT/"lessons/connection-config-is-not-health.json")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            a.atomic_json(root/"lessons"/(record["id"]+".json"), record)
            with patch.object(a, "ROOT", root):
                result = a.lessons(argparse.Namespace(lesson_action="retire", id=record["id"], reason="Verified incompatible with the new version"))
                self.assertTrue(result["history_preserved"])
                found = a.lessons(argparse.Namespace(lesson_action="search", query="config"))
                self.assertEqual(found["matches"], [])
            self.assertEqual(len(list((root/"lessons/.history").glob("*.json"))), 1)

    def test_health_separates_missing_ocr_from_local_api(self):
        with tempfile.TemporaryDirectory() as d, patch.object(a.Path, "home", return_value=Path(d)), patch.object(a, "local_get", return_value=([{"key": "ABCD1234"}], {})), patch.object(a, "executable", return_value=None), patch.object(a, "run", return_value=(1, "", "")):
            (Path(d)/".codex").mkdir()
            (Path(d)/".codex/config.toml").write_text('[mcp_servers.zotero]\ncommand="example-mcp"\n')
            result = a.doctor()
        self.assertTrue(result["ok"])
        self.assertFalse(result["checks"]["tools"]["ocrmypdf"])
        self.assertIn("not_tested", result["checks"]["mcp_runtime"])


if __name__ == "__main__":
    unittest.main()
