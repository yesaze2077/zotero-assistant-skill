#!/usr/bin/env python3
"""Evidence-gated onboarding progress; no Zotero, configuration, or usage writes.

status is read-only. record accepts one step, status, optional reason and evidence
{kind, summary, checks, artifact?}. artifact is an opaque code, never a path/key.
The caller must verify the evidence; this recorder validates its declared shape.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("_zotero_journey_shared", Path(__file__).with_name("assistant.py"))
_shared = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_shared)
atomic_json, state_lock = _shared.atomic_json, _shared.state_lock

CHECKS = {
    "zotero_desktop": ("application_launch",),
    "local_api": ("items_get", "collections_get"),
    "browser_connector": ("enabled_in_chosen_browser", "saved_item_readback"),
    "mcp": ("protocol_connected", "collection_tool_called"),
    "word_citations": ("citation_inserted", "bibliography_inserted", "refresh_preserved_fields"),
    "paper_selected": ("library_item_resolved", "attachment_identified"),
    "paper_text": ("all_pages_checked", "required_sections_read", "critical_evidence_checked"),
    "reader_practice": ("user_completed_reading_action",),
    "research_card": ("sources_labeled", "page_evidence_linked", "unknowns_marked"),
    "first_citation": ("citation_traceable", "metadata_checked"),
}
KINDS = {
    "zotero_desktop": {"tool", "gui", "combined", "user_report"},
    "local_api": {"tool", "api", "combined"},
    "browser_connector": {"tool", "gui", "combined"},
    "mcp": {"tool", "combined"},
    "word_citations": {"tool", "gui", "combined", "user_report"},
    "paper_selected": {"tool", "api", "gui", "combined"},
    "paper_text": {"tool", "file", "gui", "combined"},
    "reader_practice": {"gui", "user_report", "combined"},
    "research_card": {"tool", "file", "gui", "combined"},
    "first_citation": {"tool", "file", "gui", "combined"},
}
CORE = ("paper_selected", "paper_text", "reader_practice", "research_card", "first_citation")
STATUSES = {"pending", "verified", "deferred", "not_applicable", "blocked"}
HISTORY_LIMIT = 200
PRIVATE_FIELDS = re.compile(
    r"(?i)^(?:api[_-]?key|access[_-]?token|refresh[_-]?token|token|password|authorization|"
    r"cookie|secret|credentials?|title|paper[_-]?title|item[_-]?key|paper[_-]?key|zotero[_-]?key|"
    r"full[_-]?text|content|(?:source|pdf|attachment)[_-]?path|path|doi|library[_-]?item[_-]?id)$")
PRIVATE_TEXT = re.compile(
    r"(?i)(?:/(?:Users|home|Volumes|private|tmp)/|(?:file|zotero)://|[A-Z]:[\\/]|"
    r"Bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|"
    r"(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|authorization|cookie|secret)\s*[=:]\s*\S+|"
    r"(?:item|paper|zotero)[_ -]?key\s*[=:]\s*\S+|"
    r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}|"
    r"https?://[^\s]+[?&](?:key|token|auth|code)=|"
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b)")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def reject_private(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or PRIVATE_FIELDS.fullmatch(key):
                raise ValueError("sensitive_or_paper_detail_field_not_allowed")
            reject_private(child)
    elif isinstance(value, list):
        for child in value:
            reject_private(child)
    elif isinstance(value, str):
        # Check values, not serialized field names: local_api/metadata_checked are valid.
        if PRIVATE_TEXT.search(value) or re.search(r"\b(?=[A-Z0-9]{8}\b)(?=[A-Z0-9]*[A-Z])(?=[A-Z0-9]*\d)[A-Z0-9]{8}\b", value):
            raise ValueError("sensitive_pattern_not_allowed")
        if re.search(r"\b[A-Za-z0-9_-]{40,}\b", value):
            raise ValueError("opaque_credential_or_excess_content_not_allowed")
        if re.search(r"\b(?=[A-Za-z0-9_-]{24,}\b)(?=[A-Za-z0-9_-]*[A-Za-z])(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9_-]+\b", value):
            raise ValueError("opaque_credential_or_excess_content_not_allowed")


def short_text(value, field, required=False, limit=400):
    if value is None and not required:
        return ""
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError("invalid_" + field)
    reject_private(value)
    return value.strip()


def validate_record(record):
    if not isinstance(record, dict):
        raise ValueError("record_must_be_an_object")
    reject_private(record)
    if set(record) - {"step", "status", "reason", "evidence"}:
        raise ValueError("unknown_record_field")
    step, status = record.get("step"), record.get("status")
    if not isinstance(step, str) or step not in CHECKS:
        raise ValueError("unknown_step")
    if not isinstance(status, str) or status not in STATUSES:
        raise ValueError("unknown_status")
    reason = short_text(record.get("reason"), "reason", status in {"deferred", "not_applicable", "blocked"})
    evidence = record.get("evidence")
    if status == "verified" and not isinstance(evidence, dict):
        raise ValueError("verified_requires_evidence")
    clean = {"step": step, "status": status, "reason": reason, "evidence": None}
    if evidence is not None:
        if not isinstance(evidence, dict) or set(evidence) - {"kind", "summary", "checks", "artifact"}:
            raise ValueError("invalid_evidence_fields")
        kind = evidence.get("kind")
        if not isinstance(kind, str) or kind not in KINDS[step]:
            raise ValueError("evidence_kind_not_allowed_for_step")
        summary = short_text(evidence.get("summary"), "evidence_summary", True)
        checks = evidence.get("checks", {})
        if not isinstance(checks, dict) or set(checks) - set(CHECKS[step]):
            raise ValueError("invalid_evidence_checks")
        if any(type(value) is not bool for value in checks.values()):
            raise ValueError("checks_must_be_boolean")
        if status == "verified" and any(checks.get(name) is not True for name in CHECKS[step]):
            raise ValueError("required_checks_not_verified")
        clean["evidence"] = {"kind": kind, "summary": summary, "checks": dict(checks)}
        if "artifact" in evidence:
            artifact = evidence["artifact"]
            if not isinstance(artifact, str) or not re.fullmatch(r"[A-Za-z]{2,12}-[A-Za-z0-9-]{1,32}", artifact):
                raise ValueError("artifact_must_be_an_opaque_code")
            clean["evidence"]["artifact"] = artifact
    return clean


def initial_state():
    return {"schema_version": 1, "mode": "onboarding",
            "mode_context": {"source": "default", "reason": "尚未完成首次论文体验。", "changed_at": None},
            "steps": {step: {"status": "pending", "reason": "", "evidence": None, "updated_at": None} for step in CHECKS},
            "history": [], "history_events_total": 0, "updated_at": None}


def load_state(directory):
    path = Path(directory) / "onboarding.json"
    if not path.exists():
        return initial_state()
    if not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError("invalid_onboarding_state")
    state = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise ValueError("unsupported_onboarding_schema")
    if set(state) != set(initial_state()) or not isinstance(state.get("steps"), dict):
        raise ValueError("invalid_onboarding_state")
    if state.get("mode") not in {"onboarding", "daily"} or set(state["steps"]) != set(CHECKS):
        raise ValueError("invalid_onboarding_state")
    if not isinstance(state.get("history"), list) or len(state["history"]) > HISTORY_LIMIT:
        raise ValueError("invalid_onboarding_history")
    if type(state.get("history_events_total")) is not int or state["history_events_total"] < len(state["history"]):
        raise ValueError("invalid_onboarding_history")
    if any(not isinstance(e, dict) or e.get("event") not in {"step_recorded", "mode_changed"} for e in state["history"]):
        raise ValueError("invalid_onboarding_history")
    context = state.get("mode_context", {})
    if not isinstance(context, dict) or context.get("source") not in {"default", "user_explicit", "auto_core_complete", "auto_core_reopened"}:
        raise ValueError("invalid_mode_context")
    reject_private(state)
    for step, entry in state["steps"].items():
        if not isinstance(entry, dict) or set(entry) - {"status", "reason", "evidence", "updated_at"}:
            raise ValueError("invalid_onboarding_step")
        validate_record({"step": step, **{k: entry[k] for k in ("status", "reason", "evidence") if k in entry}})
    return state


def core_complete(state):
    return all(state["steps"][step]["status"] == "verified" for step in CORE)


def summary(state):
    return {"ok": True, "mode": state["mode"], "mode_context": copy.deepcopy(state["mode_context"]),
            "core_complete": core_complete(state), "steps": copy.deepcopy(state["steps"]),
            "pending_core_steps": [step for step in CORE if state["steps"][step]["status"] != "verified"],
            "history_count": len(state["history"]), "history_events_total": state["history_events_total"],
            "updated_at": state["updated_at"]}


def append_event(state, event):
    state["history"].append(event)
    state["history"] = state["history"][-HISTORY_LIMIT:]
    state["history_events_total"] += 1
    state["updated_at"] = event["at"]


def set_mode(state, mode, reason, source, at):
    previous = state["mode"]
    state["mode"] = mode
    state["mode_context"] = {"source": source, "reason": reason, "changed_at": at}
    append_event(state, {"event": "mode_changed", "at": at, "from_mode": previous,
                         "to_mode": mode, "reason": reason, "source": source,
                         "core_complete": core_complete(state)})


def record_step(directory, record):
    clean = validate_record(record)  # Reject invalid input before creating a directory or lock.
    directory = Path(directory)
    with state_lock(directory):
        state = load_state(directory)
        step, at = clean["step"], stamp()
        previous = state["steps"][step]["status"]
        state["steps"][step] = {k: clean[k] for k in ("status", "reason", "evidence")}
        state["steps"][step]["updated_at"] = at
        append_event(state, {"event": "step_recorded", "at": at, "step": step,
                             "from_status": previous, "to_status": clean["status"],
                             "reason": clean["reason"], "evidence": copy.deepcopy(clean["evidence"]),
                             "mode_at_record": state["mode"]})
        if core_complete(state) and state["mode"] != "daily":
            set_mode(state, "daily", "第一篇论文的五项核心体验均已验证。", "auto_core_complete", at)
        elif not core_complete(state) and state["mode_context"]["source"] == "auto_core_complete":
            set_mode(state, "onboarding", "核心体验的验证状态已变更，需要继续上手。", "auto_core_reopened", at)
        atomic_json(directory / "onboarding.json", state)
    return {**summary(state), "recorded_step": step}


def change_mode(directory, mode, reason=None):
    if mode not in {"daily", "onboarding"}:
        raise ValueError("unknown_mode")
    reason = short_text(reason, "explicit_user_reason", mode == "daily")
    if not reason:
        reason = "用户选择重新进入首次上手引导。"
    directory = Path(directory)
    with state_lock(directory):
        state = load_state(directory)
        set_mode(state, mode, reason, "user_explicit", stamp())
        atomic_json(directory / "onboarding.json", state)
    return summary(state)


class JSONParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("invalid_arguments")


def main(argv=None):
    parser = JSONParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=ROOT / "state")
    sub = parser.add_subparsers(dest="action", required=True)
    read = sub.add_parser("status")
    record = sub.add_parser("record")
    record.add_argument("--file", type=Path, required=True)
    mode = sub.add_parser("mode")
    mode.add_argument("mode", choices=("daily", "onboarding"))
    mode.add_argument("--reason")
    for command in (read, record, mode):
        command.add_argument("--state-dir", type=Path, default=argparse.SUPPRESS)
    try:
        args = parser.parse_args(argv)
        if args.action == "status":
            result = summary(load_state(args.state_dir))
        elif args.action == "mode":
            result = change_mode(args.state_dir, args.mode, args.reason)
        else:
            if args.file.stat().st_size > 65536:
                raise ValueError("record_too_large")
            result = record_step(args.state_dir, json.loads(args.file.read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Never echo records, private paths, malformed JSON, or credential values.
        code = str(exc) if type(exc) is ValueError and re.fullmatch(r"[a-z_]+", str(exc)) else "invalid_or_unreadable_input"
        result = {"ok": False, "error": {"code": code}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
