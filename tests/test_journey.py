"""Isolated onboarding behavior tests. No real Zotero/configuration is accessed."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/journey.py"
spec = importlib.util.spec_from_file_location("journey_under_test", SCRIPT)
journey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(journey)


def evidence(step, kind=None):
    kinds = {"zotero_desktop": "gui", "local_api": "api", "browser_connector": "gui",
             "mcp": "tool", "word_citations": "gui", "paper_selected": "tool",
             "paper_text": "file", "reader_practice": "user_report", "research_card": "file",
             "first_citation": "file"}
    return {"step": step, "status": "verified", "evidence": {
        "kind": kind or kinds[step], "summary": "已完成该步骤的实际检查并保留核验结论。",
        "checks": {check: True for check in journey.CHECKS[step]}}}


class JourneyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="journey-qa-")
        self.root = Path(self.temp.name)
        self.state = self.root / "isolated-state"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), *args,
                                 "--state-dir", str(self.state)], text=True,
                                capture_output=True, timeout=10)
        return result.returncode, json.loads(result.stdout)

    def test_status_defaults_are_pending_and_do_not_create_state(self):
        code, result = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(result["mode"], "onboarding")
        self.assertFalse(result["core_complete"])
        self.assertEqual(len(result["steps"]), 10)
        self.assertTrue(all(x["status"] == "pending" for x in result["steps"].values()))
        self.assertFalse(self.state.exists())

    def test_resume_across_processes_keeps_previous_steps_and_history(self):
        record_file = self.root / "record.json"
        record_file.write_text(json.dumps(evidence("local_api")))
        code, result = self.cli("record", "--file", str(record_file))
        self.assertEqual(code, 0)
        first = (self.state / "onboarding.json").read_bytes()
        code, resumed = self.cli("status")
        self.assertEqual(code, 0)
        self.assertEqual(resumed["steps"]["local_api"]["status"], "verified")
        self.assertEqual((self.state / "onboarding.json").read_bytes(), first)
        journey.record_step(self.state, evidence("zotero_desktop"))
        data = json.loads((self.state / "onboarding.json").read_text())
        self.assertEqual([e["step"] for e in data["history"]], ["local_api", "zotero_desktop"])

    def test_every_verified_step_requires_each_specific_check(self):
        for step, checks in journey.CHECKS.items():
            for missing in checks:
                with self.subTest(step=step, missing=missing):
                    record = evidence(step)
                    del record["evidence"]["checks"][missing]
                    with self.assertRaisesRegex(ValueError, "required_checks_not_verified"):
                        journey.record_step(self.state, record)
        self.assertFalse(self.state.exists())

    def test_verified_requires_summary_kind_and_boolean_true(self):
        for replacement in [False, 1, "true", None]:
            record = evidence("local_api")
            record["evidence"]["checks"]["items_get"] = replacement
            with self.subTest(value=replacement), self.assertRaises(ValueError):
                journey.record_step(self.state, record)
        for key in ["summary", "kind"]:
            record = evidence("local_api")
            del record["evidence"][key]
            with self.assertRaises(ValueError):
                journey.record_step(self.state, record)

    def test_card_artifact_cannot_impersonate_user_reading_practice(self):
        record = evidence("reader_practice", "file")
        record["evidence"]["artifact"] = "CARD-001"
        record["evidence"]["summary"] = "助手生成了研究卡片。"
        with self.assertRaisesRegex(ValueError, "evidence_kind_not_allowed_for_step"):
            journey.record_step(self.state, record)
        record = evidence("reader_practice", "user_report")
        record["evidence"]["summary"] = "用户用自己的话说明了该证据对研究问题的用途。"
        result = journey.record_step(self.state, record)
        self.assertEqual(result["steps"]["reader_practice"]["status"], "verified")

    def test_environment_verification_is_not_first_paper_completion(self):
        for step in ("zotero_desktop", "local_api", "browser_connector", "mcp", "word_citations"):
            result = journey.record_step(self.state, evidence(step))
        self.assertEqual(result["mode"], "onboarding")
        self.assertFalse(result["core_complete"])
        self.assertEqual(set(result["pending_core_steps"]), set(journey.CORE))

    def test_optional_components_do_not_block_verified_core(self):
        for step, status in [("browser_connector", "deferred"), ("word_citations", "not_applicable"),
                             ("mcp", "blocked")]:
            journey.record_step(self.state, {"step": step, "status": status,
                                            "reason": "本次采用已可用的本地阅读方式。"})
        for step in journey.CORE:
            result = journey.record_step(self.state, evidence(step))
        self.assertTrue(result["core_complete"])
        self.assertEqual(result["mode"], "daily")
        self.assertEqual(result["mode_context"]["source"], "auto_core_complete")
        self.assertEqual(result["steps"]["mcp"]["status"], "blocked")

    def test_deferred_and_not_applicable_never_satisfy_core(self):
        for status in ("deferred", "not_applicable", "blocked", "pending"):
            directory = self.root / status
            for step in journey.CORE[:-1]:
                journey.record_step(directory, evidence(step))
            result = journey.record_step(directory, {"step": "first_citation", "status": status,
                                                    "reason": "用户本次尚未完成引用练习。"})
            self.assertFalse(result["core_complete"])
            self.assertEqual(result["mode"], "onboarding")

    def test_explicit_skip_is_daily_but_not_complete(self):
        reason = "用户明确选择先处理现有文献问题，跳过入门引导。"
        result = journey.change_mode(self.state, "daily", reason)
        self.assertEqual(result["mode"], "daily")
        self.assertFalse(result["core_complete"])
        self.assertTrue(all(v["status"] == "pending" for v in result["steps"].values()))
        result = journey.record_step(self.state, evidence("local_api"))
        self.assertEqual(result["mode"], "daily")
        self.assertEqual(result["mode_context"]["reason"], reason)
        result = journey.change_mode(self.state, "onboarding")
        self.assertEqual(result["mode"], "onboarding")
        self.assertEqual(result["steps"]["local_api"]["status"], "verified")

    def test_daily_requires_explicit_reason(self):
        with self.assertRaisesRegex(ValueError, "invalid_explicit_user_reason"):
            journey.change_mode(self.state, "daily")
        self.assertFalse(self.state.exists())

    def test_invalid_record_leaves_existing_bytes_and_history_unchanged(self):
        journey.record_step(self.state, evidence("local_api"))
        path = self.state / "onboarding.json"
        before = path.read_bytes()
        bad = evidence("paper_text")
        bad["evidence"]["checks"]["all_pages_checked"] = False
        with self.assertRaises(ValueError):
            journey.record_step(self.state, bad)
        self.assertEqual(path.read_bytes(), before)

    def test_failed_write_leaves_existing_record_intact(self):
        journey.record_step(self.state, evidence("local_api"))
        path = self.state / "onboarding.json"
        before = path.read_bytes()
        with patch.object(journey, "atomic_json", side_effect=OSError("QA write failure")):
            with self.assertRaises(OSError):
                journey.record_step(self.state, evidence("zotero_desktop"))
        self.assertEqual(path.read_bytes(), before)

    def test_credentials_paths_keys_and_paper_fields_are_rejected(self):
        examples = [
            ("summary", "Bearer abcdefghijklmnopqrstuvwxyz"),
            ("summary", "ZOTERO_API_KEY=not-for-storage"),
            ("summary", "/Users/example/private/paper.pdf"),
            ("summary", "zotero://select/library/items/ABCD1234"),
            ("summary", "ABCD1234"),
            ("summary", "aB2cdEFGhIjkLmNOpQ3rsTuVWxYz1234"),
            ("title", "A private manuscript title"),
            ("full_text", "Private paper body"),
            ("api_key", "hidden"),
            ("artifact", "/tmp/card.md"),
        ]
        for field, value in examples:
            record = evidence("research_card")
            record["evidence"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                journey.record_step(self.state, record)
        self.assertFalse(self.state.exists())

    def test_legitimate_api_and_metadata_check_field_names_are_allowed(self):
        journey.record_step(self.state, evidence("local_api"))
        card = evidence("research_card")
        card["evidence"]["artifact"] = "CARD-001"
        journey.record_step(self.state, card)
        result = journey.record_step(self.state, evidence("first_citation"))
        self.assertTrue(result["steps"]["first_citation"]["evidence"]["checks"]["metadata_checked"])

    def test_usage_is_never_created_or_modified(self):
        journey.record_step(self.state, evidence("local_api"))
        usage = self.state / "usage.json"
        self.assertFalse(usage.exists())
        original = b'{"last_used_at":"2026-09-01T00:00:00Z","sentinel":true}\n'
        usage.write_bytes(original)
        journey.change_mode(self.state, "daily", "用户明确选择暂时跳过引导。")
        journey.record_step(self.state, evidence("reader_practice"))
        journey.summary(journey.load_state(self.state))
        self.assertEqual(usage.read_bytes(), original)

    def test_history_is_bounded_and_keeps_mode_reason_context(self):
        reason = "用户明确选择先处理日常任务。"
        journey.change_mode(self.state, "daily", reason)
        with patch.object(journey, "HISTORY_LIMIT", 4):
            for _ in range(8):
                journey.record_step(self.state, evidence("local_api"))
            state = journey.load_state(self.state)
            self.assertEqual(len(state["history"]), 4)
            self.assertEqual(state["history_events_total"], 9)
            self.assertEqual(state["mode_context"]["reason"], reason)
            self.assertEqual(state["steps"]["local_api"]["status"], "verified")

    def test_retracted_core_verification_reopens_only_automatic_daily_mode(self):
        for step in journey.CORE:
            journey.record_step(self.state, evidence(step))
        result = journey.record_step(self.state, {"step": "paper_text", "status": "blocked",
                                                "reason": "关键章节的读取证据需要重新核验。"})
        self.assertFalse(result["core_complete"])
        self.assertEqual(result["mode"], "onboarding")
        self.assertEqual(result["mode_context"]["source"], "auto_core_reopened")

    def test_corrupt_state_is_not_overwritten(self):
        self.state.mkdir()
        path = self.state / "onboarding.json"
        path.write_text("{invalid JSON}")
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            journey.record_step(self.state, evidence("local_api"))
        self.assertEqual(path.read_bytes(), before)

    def test_busy_state_lock_cannot_lose_existing_updates(self):
        journey.record_step(self.state, evidence("local_api"))
        before = (self.state / "onboarding.json").read_bytes()
        with journey.state_lock(self.state):
            with self.assertRaisesRegex(ValueError, "another_operation_running"):
                journey.record_step(self.state, evidence("zotero_desktop"))
        self.assertEqual((self.state / "onboarding.json").read_bytes(), before)

    def test_cli_error_never_echoes_secret(self):
        private = evidence("local_api")
        private["evidence"]["summary"] = "password=qa-credential-never-echo"
        record_file = self.root / "private-input.json"
        record_file.write_text(json.dumps(private))
        code, result = self.cli("record", "--file", str(record_file))
        self.assertEqual(code, 1)
        self.assertFalse(result["ok"])
        self.assertNotIn("qa-credential", json.dumps(result))
        self.assertFalse(self.state.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
