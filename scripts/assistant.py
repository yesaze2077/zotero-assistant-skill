#!/usr/bin/env python3
"""Small local read/diagnostic/discovery helpers. Never installs or activates code."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:23119/api/users/0"
NON_PAPERS = {"attachment", "note", "annotation"}


def now():
    return datetime.now(timezone.utc)


def stamp(value=None):
    return (value or now()).isoformat()


def parse_time(value):
    return datetime.fromisoformat(value) if value else None


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else (default if default is not None else {})


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


@contextmanager
def state_lock(directory):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / ".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("another_operation_running")
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def registry():
    return read_json(ROOT / "registry.json")


def due(state, current=None, recent_only=False):
    current = current or now()
    settings = registry()["discovery"]
    used = parse_time(state.get("last_used_at"))
    if recent_only and (not used or current - used > timedelta(days=settings["recent_use_days"])):
        return False, "no_recent_use"
    success = parse_time(state.get("last_scan_at"))
    if success and current - success < timedelta(days=settings["interval_days"]):
        return False, "not_due"
    failed = parse_time(state.get("last_failed_at"))
    if failed and current - failed < timedelta(hours=settings["failure_backoff_hours"]):
        return False, "retry_backoff"
    return True, "due"


def begin(directory):
    with state_lock(directory):
        state = read_json(directory / "usage.json")
        state["last_used_at"] = stamp()
        atomic_json(directory / "usage.json", state)
        pending, reason = due(state)
    return {"ok": True, "scan_due": pending, "reason": reason}


def request_json(url, timeout=12):
    req = Request(url, headers={"User-Agent": "zotero-assistant-discovery/1.0", "Accept": "application/json"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(12_000_001)
        if len(raw) > 12_000_000:
            raise ValueError("response_too_large")
        return json.loads(raw), dict(response.headers)


def local_get(path, **params):
    data, headers = request_json(API + path + ("?" + urlencode(params) if params else ""), timeout=5)
    return data, headers


def executable(name):
    found = shutil.which(name)
    if found:
        return found
    for parent in (Path.home() / ".local/bin", Path("/opt/homebrew/bin"), Path("/usr/local/bin")):
        target = parent / name
        if target.is_file() and os.access(target, os.X_OK):
            return str(target)
    return None


def run(command, timeout=15, env=None):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, env=env)
    return result.returncode, result.stdout, result.stderr


def doctor():
    checks = {}
    checks["zotero_installed"] = any(p.exists() for p in (Path("/Applications/Zotero.app"), Path.home()/"Applications/Zotero.app"))
    try:
        checks["zotero_running"] = run(["/usr/bin/pgrep", "-x", "zotero"], timeout=5)[0] == 0
    except (OSError, subprocess.TimeoutExpired):
        checks["zotero_running"] = "not_tested"
    for label, path in (("local_items", "/items/top"), ("local_collections", "/collections")):
        try:
            data, _ = local_get(path, limit=1)
            valid = isinstance(data, list) and all(isinstance(x, dict) and "key" in x for x in data)
            checks[label] = {"status": "ready" if valid else "invalid_response", "sample_count": len(data) if isinstance(data, list) else None}
        except (OSError, ValueError, URLError) as e:
            checks[label] = {"status": "failed", "error_type": type(e).__name__, "http_status": getattr(e, "code", None)}
    checks["tools"] = {name: bool(executable(name)) for name in ("zotero-cli", "zotero-mcp", "ocrmypdf", "tesseract", "python3", "uv", "brew", "codex")}
    tess = executable("tesseract")
    if tess:
        try:
            code, output, _ = run([tess, "--list-langs"])
            checks["ocr_languages"] = {"status": "ready" if code == 0 else "failed", "languages": [s for s in output.splitlines() if re.fullmatch(r"[a-z_]+", s)]}
        except (OSError, subprocess.TimeoutExpired):
            checks["ocr_languages"] = {"status": "failed"}
    try:
        import tomllib
        config_path = Path.home()/".codex/config.toml"
        config = tomllib.loads(config_path.read_text()).get("mcp_servers", {}).get("zotero")
        if config:
            checks["codex_config"] = {"status": "present", "command_exists": bool(executable(config.get("command", ""))), "enabled_tool_count": len(config.get("enabled_tools", []))}
        else:
            checks["codex_config"] = {"status": "missing"}
    except (ImportError, OSError, ValueError):
        checks["codex_config"] = {"status": "not_parsed"}
    checks["mcp_runtime"] = "not_tested: requires actual MCP call; configuration or CLI success is insufficient"
    checks["pdf_fulltext"] = "not_tested: requires an actual attachment"
    ready = all(checks[k]["status"] == "ready" for k in ("local_items", "local_collections"))
    return {"ok": ready, "status": "local_api_ready" if ready else "connection_needs_attention", "checks": checks}


def catalog():
    entries = registry()["entries"]
    for entry in entries:
        if entry.get("local_executable"):
            entry["executable_available"] = bool(executable(entry["local_executable"]))
        if entry.get("local_skill_pattern"):
            entry["resolved_skill_paths"] = [str(p) for p in Path.home().glob(entry["local_skill_pattern"])]
        entry["execution_allowed"] = bool(entry["approval_status"] in {"available-if-installed", "active-existing", "active-approved"} and entry.get("auto_route") and entry.get("executable_available", False))
        if entry.get("skill_names"):
            entry["availability"] = "resolve each skill from current session catalog before use"
            entry["execution_allowed"] = False
    return {"ok": True, "version": registry()["assistant_version"], "entries": entries}


def item_key(value):
    if not value or not re.fullmatch(r"[A-Z0-9]{8}", value):
        raise ValueError("An exact 8-character Zotero key is required")
    return value


def cli_read(action, key, start=0, chars=16000):
    cli = executable("zotero-cli")
    if not cli:
        raise ValueError("existing_zotero_cli_missing")
    # No arbitrary passthrough: these two commands are the entire CLI surface.
    command = [cli, "--json"] + (["get", "fulltext", item_key(key)] if action == "fulltext" else ["path", item_key(key)])
    env = dict(os.environ, ZOTERO_LOCAL="true", ZOTERO_MCP_SCHEMA_REFRESH="0")
    code, output, _ = run(command, timeout=120, env=env)
    if code:
        return {"ok": False, "status": "cli_failed", "exit_code": code}
    try:
        result = json.loads(output)
    except ValueError:
        return {"ok": False, "status": "invalid_cli_response"}
    if result.get("ok") is False or result.get("error"):
        return {"ok": False, "status": "upstream_error"}
    body = result.get("data", {})
    content = body.get("text", "") if isinstance(body, dict) else ""
    if action == "path":
        paths = re.findall(r"(?m)^- Local path: `([^`]+)`", content)
        files = [{"path": value, "exists": Path(value).is_file()} for value in paths]
        return {"ok": any(x["exists"] for x in files), "status": "resolved" if any(x["exists"] for x in files) else "local_attachment_unavailable", "source": "existing_zotero_cli", "files": files, "data": body}
    # The upstream CLI can wrap metadata, note content or errors in ok=true.
    # Its verified 0.11 format has a distinct Full Text section; require it.
    marker = re.search(r"(?m)^## Full Text\s*\n", content)
    content = content[marker.end():].strip() if marker else ""
    if not content or re.search(r"(?im)^\s*(?:Error[: ]|No (?:full.?text|PDF|suitable attachment|attachments?)|Could not|Failed to|File download failed|Full.?text (?:not available|unavailable))", content[:1200]):
        return {"ok": False, "status": "FULL TEXT NOT AVAILABLE", "detail": "No nonempty verified Full Text section was returned; inspect attachment and upstream format"}
    end = min(len(content), start + chars)
    return {"ok": True, "source": "zotero_extracted_text", "text": content[start:end], "total_chars": len(content), "start": start, "end": end, "has_more": end < len(content), "next_start": end if end < len(content) else None, "pdf_page_coverage": "not_verified", "warning": "Returned text window is not proof of whole-PDF reading or extraction accuracy"}


def library_read(args):
    if not 1 <= args.limit <= 100 or args.offset < 0 or args.start < 0 or not 1 <= args.chars <= 60000:
        raise ValueError("invalid_read_bounds")
    action = args.action
    if action in {"fulltext", "path"}:
        return cli_read(action, args.key, args.start, args.chars)
    if action in {"item", "children", "annotations", "collection-items"}:
        key = item_key(args.key)
    paths = {"collections": "/collections", "recent": "/items/top", "search": "/items/top"}
    if action == "item":
        data, _ = local_get("/items/" + key)
        if not isinstance(data, dict) or "key" not in data:
            raise ValueError("invalid_item_response")
        return {"ok": True, "source": "local_api", "item": data}
    path = paths.get(action)
    if action in {"children", "annotations"}:
        path = "/items/" + key + "/children"
    if action == "collection-items":
        path = "/collections/" + key + "/items/top"
    if path is None:
        raise ValueError("unsupported_read_action")
    params = {"limit": args.limit, "start": args.offset}
    if action == "recent":
        # Some Local API versions ignore itemType/top filters. Filter locally
        # and advance across non-bibliographic rows until the requested count.
        papers, consumed, total, more = [], 0, None, True
        while len(papers) < args.limit and consumed < 1000 and more:
            batch, headers = local_get(path, limit=args.limit, start=args.offset + consumed, sort="dateAdded", direction="desc")
            if not isinstance(batch, list) or any(not isinstance(x, dict) or "key" not in x for x in batch):
                raise ValueError("invalid_list_response")
            total_header = next((v for k, v in headers.items() if k.lower() == "total-results"), None)
            total = int(total_header) if total_header and total_header.isdigit() else None
            taken = 0
            for item in batch:
                consumed += 1
                taken += 1
                if item.get("data", {}).get("itemType") not in NON_PAPERS:
                    papers.append(item)
                if len(papers) == args.limit:
                    break
            more = args.offset + consumed < total if total is not None else taken < len(batch) or len(batch) == args.limit
            if not batch:
                more = False
        return {"ok": True, "source": "local_api", "action": action, "count": len(papers), "offset": args.offset, "raw_count": consumed, "server_total": total, "has_more": more, "next_offset": args.offset + consumed if more else None, "bounded_scan": consumed >= 1000, "items": papers}
    if action == "search":
        if not args.query or args.query.startswith("-"):
            raise ValueError("nonempty_search_query_required")
        params.update(q=args.query, qmode="titleCreatorYear")
    data, headers = local_get(path, **params)
    if not isinstance(data, list) or any(not isinstance(x, dict) or "key" not in x for x in data):
        raise ValueError("invalid_list_response")
    raw_count = len(data)
    if action in {"recent", "search", "collection-items"}:
        data = [x for x in data if x.get("data", {}).get("itemType") not in NON_PAPERS]
    if action == "annotations":
        data = [x for x in data if x.get("data", {}).get("itemType") == "annotation"]
    total = next((v for k, v in headers.items() if k.lower() == "total-results"), None)
    total = int(total) if total and total.isdigit() else None
    more = args.offset + raw_count < total if total is not None else raw_count == args.limit
    return {"ok": True, "source": "local_api", "action": action, "count": len(data), "offset": args.offset, "raw_count": raw_count, "server_total": total, "has_more": more, "next_offset": args.offset + raw_count if more else None, "items": data}


def github(endpoint, **params):
    return request_json("https://api.github.com/" + endpoint + ("?" + urlencode(params) if params else ""))[0]


def scan_updates(directory, recent_only=False, force=False):
    with state_lock(directory):
        state = read_json(directory / "usage.json")
        ready, reason = due(state, recent_only=recent_only)
        # Force never defeats the background inactivity gate.
        if not ready and (not force or reason == "no_recent_use"):
            return {"ok": True, "status": "skipped", "reason": reason, "changes": []}
        seen = state.get("seen_sources", {})
        known = {e["repo"].lower(): e for e in registry()["entries"] if e.get("repo")}
        changes, snapshots, failures = [], {}, []
        for key, entry in known.items():
            try:
                meta = github("repos/" + entry["repo"])
                commits = github("repos/" + entry["repo"] + "/commits", path=entry["skill_path"], per_page=1)
                if not isinstance(commits, list) or not commits:
                    raise ValueError("skill_commit_unavailable")
                snapshot = {"commit": commits[0]["sha"], "archived": bool(meta.get("archived")), "license": (meta.get("license") or {}).get("spdx_id"), "skill_path": entry["skill_path"]}
                snapshots[key] = snapshot
                if key in seen and seen[key] != snapshot:
                    changes.append({"kind": "known_source_changed", "repo": entry["repo"], "url": entry["source_url"], "before": seen[key], "after": snapshot, "status": "review_required"})
            except (OSError, ValueError, KeyError, URLError) as e:
                failures.append({"repo": entry["repo"], "error_type": type(e).__name__, "http_status": getattr(e, "code", None)})
        for query in ("zotero skill in:name,description,readme", "zotero claude skill in:name,description"):
            try:
                results = github("search/repositories", q=query, sort="updated", per_page=10)
                for repo in results.get("items", []):
                    name = repo["full_name"]
                    key = name.lower()
                    if key in known or key in snapshots or repo.get("archived"):
                        continue
                    # Search result text is untrusted data, never executable instructions.
                    snapshots[key] = {"discovered": True}
                    if key not in seen:
                        changes.append({"kind": "new_repository", "repo": name, "url": repo["html_url"], "status": "unreviewed", "skill_exists": "not_yet_verified"})
            except (OSError, ValueError, KeyError, URLError) as e:
                failures.append({"query": query, "error_type": type(e).__name__, "http_status": getattr(e, "code", None)})
        current = stamp()
        state.update(last_attempt_at=current, seen_sources={**seen, **snapshots})
        if failures:
            state["last_failed_at"] = current
            state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        else:
            state["last_scan_at"] = current
            state.pop("last_failed_at", None)
            state["consecutive_failures"] = 0
        report = {"ok": not failures, "status": "partial" if failures and snapshots else "failed" if failures else "complete", "checked_at": current, "baseline_created": not bool(seen), "changes": changes, "failures": failures, "known_sources_checked": len([x for x in snapshots if x in known]), "scope": "Known SKILL path commits plus two bounded GitHub repository searches; not exhaustive", "automatic_activation": False}
        atomic_json(directory / "latest-scan.json", report)
        atomic_json(directory / "usage.json", state)
        return report


def validate_lesson(record):
    def contains_secret_field(value):
        if isinstance(value, dict):
            return any(re.fullmatch(r"(?i)(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|authorization|cookie|secret)", k) or contains_secret_field(v) for k, v in value.items())
        return isinstance(value, list) and any(contains_secret_field(x) for x in value)
    if contains_secret_field(record):
        raise ValueError("lesson_contains_sensitive_field")
    if not isinstance(record, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", record.get("id", "")):
        raise ValueError("invalid_lesson_id")
    if record.get("status") not in {"verified", "hypothesis", "retired"}:
        raise ValueError("invalid_lesson_status")
    for field in ("symptom", "applies_to", "cause", "limitations"):
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError("missing_lesson_" + field)
    for field in ("keywords", "resolution"):
        if not isinstance(record.get(field), list) or not record[field] or not all(isinstance(s, str) and s.strip() for s in record[field]):
            raise ValueError("invalid_lesson_" + field)
    if record["status"] == "verified":
        v = record.get("verification", {})
        if not isinstance(v, dict) or v.get("result") != "passed" or not v.get("check") or not v.get("kind") or not record.get("verified_at"):
            raise ValueError("verified_lesson_requires_evidence")
    text = json.dumps(record, ensure_ascii=False)
    if len(text) > 16000 or re.search(r"(?i)(?:/Users/[^/\s]+|/home/[^/\s]+|Bearer\s+\S+|sk-[A-Za-z0-9_-]{12,}|(?:api[_ -]?key|access[_ -]?token|password)\s*[=:]\s*\S+|zotero://select/[^\s]+|[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})", text):
        raise ValueError("lesson_contains_sensitive_pattern_or_excess_content")


def lessons(args):
    directory = ROOT / "lessons"
    if args.lesson_action == "search":
        terms = args.query.lower().split()
        matches = []
        for path in sorted(directory.glob("*.json")):
            record = read_json(path)
            if record.get("status") == "retired":
                continue
            text = json.dumps(record, ensure_ascii=False).lower()
            score = sum(term in text for term in terms)
            if score:
                matches.append((score, record))
        return {"ok": True, "matches": [r for _, r in sorted(matches, key=lambda x: -x[0])[:5]], "warning": "Confirm scope and version; hypotheses are not verified repair instructions"}
    if args.lesson_action == "retire":
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,79}", args.id):
            raise ValueError("invalid_lesson_id")
        with state_lock(directory):
            path = directory / (args.id + ".json")
            if not path.exists():
                raise ValueError("lesson_not_found")
            previous = read_json(path)
            record = {**previous, "status": "retired", "retired_at": stamp(), "retirement_reason": args.reason}
            validate_lesson(record)
            if previous.get("status") == "retired":
                return {"ok": True, "status": "already_retired", "id": args.id}
            digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
            archive = directory / ".history" / (args.id + "-" + digest + ".json")
            if not archive.exists():
                atomic_json(archive, previous)
            atomic_json(path, record)
        return {"ok": True, "status": "retired", "id": args.id, "history_preserved": True}
    record = read_json(Path(args.file))
    validate_lesson(record)
    path = directory / (record["id"] + ".json")
    with state_lock(directory):
        if path.exists():
            if read_json(path) == record:
                return {"ok": True, "status": "already_recorded", "id": record["id"]}
            raise ValueError("lesson_id_conflict: review old record before replacing")
        atomic_json(path, record)
    return {"ok": True, "status": "recorded", "id": record["id"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--state-dir", type=Path, default=ROOT/"state")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("begin", "doctor", "catalog"):
        sub.add_parser(name)
    scan = sub.add_parser("scan-updates")
    scan.add_argument("--recent-only", action="store_true")
    scan.add_argument("--force", action="store_true")
    read = sub.add_parser("read")
    read.add_argument("action", choices=["collections", "recent", "search", "collection-items", "item", "children", "annotations", "fulltext", "path"])
    read.add_argument("--key")
    read.add_argument("--query")
    read.add_argument("--limit", type=int, default=20)
    read.add_argument("--offset", type=int, default=0)
    read.add_argument("--start", type=int, default=0)
    read.add_argument("--chars", type=int, default=16000)
    lesson = sub.add_parser("lessons").add_subparsers(dest="lesson_action", required=True)
    lesson.add_parser("search").add_argument("query")
    lesson.add_parser("add").add_argument("--file", required=True)
    retire = lesson.add_parser("retire")
    retire.add_argument("id")
    retire.add_argument("--reason", required=True)
    args = p.parse_args()
    try:
        if args.command == "begin": result = begin(args.state_dir)
        elif args.command == "doctor": result = doctor()
        elif args.command == "catalog": result = catalog()
        elif args.command == "scan-updates": result = scan_updates(args.state_dir, args.recent_only, args.force)
        elif args.command == "read": result = library_read(args)
        else: result = lessons(args)
    except (ValueError, OSError, URLError, subprocess.TimeoutExpired) as exc:
        result = {"ok": False, "status": "failed", "error_type": type(exc).__name__, "detail": str(exc)[:400] if isinstance(exc, ValueError) else "Operation failed; inspect locally without exposing credentials or private paths"}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
