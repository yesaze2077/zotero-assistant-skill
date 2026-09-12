#!/usr/bin/env python3
"""Local PDF inspection and OCR into a new, private output bundle.

No Zotero writes, network requests, installations, or in-place PDF changes.
CLI: pdf_ops.py inspect INPUT [--all-pages]
     pdf_ops.py ocr INPUT --output-bundle NEW_DIRECTORY [--mode skip|redo|force]
Only report.json with status=complete marks a successful OCR bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import unicodedata


class PDFError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class JSONParser(argparse.ArgumentParser):
    def error(self, message):
        raise PDFError("invalid_arguments", message)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backend_name():
    for module in ("fitz", "pypdf"):
        try:
            if importlib.util.find_spec(module):
                return module
        except (ImportError, ValueError):
            pass
    raise PDFError("runtime_unavailable", "Neither PyMuPDF nor pypdf is available in this Python runtime.")


def runtime_candidates():
    """Look only for existing runtimes; never install or activate environments."""
    candidates = [sys.executable]
    engine = shutil.which("ocrmypdf") or "/opt/homebrew/bin/ocrmypdf"
    try:
        line = Path(engine).read_text().splitlines()[0]
        if line.startswith("#!/") and " " not in line[2:]:
            candidates.append(line[2:])
    except (OSError, UnicodeError, IndexError):
        pass
    candidates += [str(p) for p in Path.home().glob(
        ".cache/codex-runtimes/*/dependencies/python/bin/python3")]
    candidates += [shutil.which("python3"), "/opt/homebrew/bin/python3", "/usr/local/bin/python3"]
    return list(dict.fromkeys(p for p in candidates if p and Path(p).is_file()))


def choose_runtime():
    """Return the current runtime when suitable, otherwise probe existing candidates."""
    try:
        backend_name()
        return sys.executable
    except PDFError:
        pass
    probe = "import importlib.util; raise SystemExit(0 if any(importlib.util.find_spec(x) for x in ('fitz','pypdf')) else 1)"
    for executable in runtime_candidates():
        try:
            if subprocess.run([executable, "-c", probe], capture_output=True, timeout=8).returncode == 0:
                return executable
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise PDFError("runtime_unavailable", "No existing Python runtime with PyMuPDF/pypdf was found; nothing was installed.")


def source_path(value):
    path = Path(value).expanduser()
    if not path.exists():
        raise PDFError("missing_file", "Input file does not exist.")
    if not path.is_file():
        raise PDFError("not_a_file", "Input is not a regular file.")
    path = path.resolve()
    with path.open("rb") as f:
        if b"%PDF-" not in f.read(1024):
            raise PDFError("not_pdf", "Input has no PDF signature.")
    return path


class Document:
    def __init__(self, path):
        self.backend = backend_name()
        self.doc = None
        if self.backend == "fitz":
            import fitz
            self.doc = fitz.open(path)
            self.encrypted = bool(self.doc.is_encrypted or self.doc.needs_pass)
            self.pages = self.doc.page_count
        else:
            from pypdf import PdfReader
            self.doc = PdfReader(str(path), strict=False)
            self.encrypted = self.doc.is_encrypted
            self.pages = None if self.encrypted else len(self.doc.pages)

    def text(self, index):
        if self.backend == "fitz":
            return self.doc[index].get_text() or ""
        return self.doc.pages[index].extract_text() or ""

    def close(self):
        close = getattr(self.doc, "close", None)
        if close:
            close()


def classify_text(text):
    compact = "".join(c for c in text if not c.isspace())
    meaningful = sum(c.isalnum() for c in compact)
    bad = sum(c == "\ufffd" or unicodedata.category(c) in ("Co", "Cs", "Cc") for c in compact)
    glyph_tokens = len(re.findall(r"/(?:g|gid)\d+", text))
    garbled = glyph_tokens >= 3 or (bad >= 3 and bad / max(len(compact), 1) > 0.08)
    status = ("no_text" if not compact else "suspected_garbled" if garbled else
              "sparse_text" if meaningful < 20 else "text")
    return {"status": status, "characters": len(text), "meaningful_characters": meaningful,
            "suspicious_characters": bad, "glyph_tokens": glyph_tokens}


def selected_pages(count, max_pages, all_pages):
    if all_pages or count <= max_pages:
        return list(range(count))
    if max_pages == 1:
        return [0]
    return sorted({round(i * (count - 1) / (max_pages - 1)) for i in range(max_pages)})


def inspect_pdf(value, max_pages=12, all_pages=False):
    result = {"ok": False, "operation": "inspect", "input": str(Path(value).expanduser()),
              "status": "error", "text_quality_is_heuristic": True}
    doc = None
    try:
        if max_pages < 1:
            raise PDFError("invalid_option", "max_pages must be positive.")
        path = source_path(value)
        result.update(input=str(path), sha256=sha256(path))
        doc = Document(path)
        result.update(backend=doc.backend, page_count=doc.pages)
        if doc.encrypted:
            raise PDFError("encrypted", "Encrypted PDF is not inspected or decrypted automatically.")
        if not doc.pages:
            raise PDFError("empty_pdf", "PDF has no pages.")
        pages = selected_pages(doc.pages, max_pages, all_pages)
        checks = []
        for index in pages:
            try:
                checks.append({"page": index + 1, **classify_text(doc.text(index))})
            except Exception:
                checks.append({"page": index + 1, "status": "extraction_failed", "characters": 0,
                               "meaningful_characters": 0})
        statuses = [x["status"] for x in checks]
        observed = ("suspected_garbled_text" if "suspected_garbled" in statuses else
                    "no_text_layer" if set(statuses) == {"no_text"} else
                    "has_text" if set(statuses) == {"text"} else "partial_pages_need_review")
        complete = len(pages) == doc.pages
        result.update(ok=True, status=observed if complete else "partial_pages_unchecked",
                      observed_status=observed, all_pages_checked=complete, checked_pages=len(pages),
                      checked_page_numbers=[i + 1 for i in pages], page_results=checks,
                      meaningful_characters_checked=sum(x["meaningful_characters"] for x in checks),
                      pages_needing_review=[x["page"] for x in checks if x["status"] != "text"],
                      limitations=["Text-layer checks do not verify words, reading order, formulas, tables, or citation accuracy.",
                                   "A page without extracted text may be blank, image-only, or unsupported; it is not proof that OCR is required."])
        if not complete:
            result["limitations"].append("Only sampled pages were inspected; no claim is made about the other pages.")
    except PDFError as exc:
        result.update(status=exc.code, error={"code": exc.code, "message": str(exc)})
    except Exception as exc:
        result.update(status="invalid_or_unreadable_pdf", error={"code": "invalid_or_unreadable_pdf",
                      "message": type(exc).__name__ + ": PDF could not be parsed."})
    finally:
        if doc:
            doc.close()
    return result


def safe_output_bundle(value, source, storage_paths=()):
    raw = Path(value).expanduser().absolute()
    if raw.is_symlink():
        raise PDFError("symlink_output", "Output bundle must not be a symbolic link.")
    if raw.resolve() == source.resolve():
        raise PDFError("same_path", "Input and output must be different paths.")
    if raw.exists():
        raise PDFError("output_exists", "Output bundle already exists; it will not be overwritten.")
    if not raw.parent.is_dir():
        raise PDFError("missing_output_parent", "Output parent directory must already exist.")
    # Resolve an existing parent before use, so a parent symlink cannot disguise a Zotero path.
    target = raw.parent.resolve(strict=True) / raw.name
    known = [Path.home() / "Zotero/storage", Path.home() / "Library/Application Support/Zotero/storage"]
    known += [Path(p).expanduser() for p in storage_paths]
    if any(target.is_relative_to(p.resolve()) for p in known):
        raise PDFError("zotero_storage_output", "Writing OCR output inside Zotero storage is forbidden.")
    for ancestor in (target, *target.parents):
        if ancestor.name.casefold() == "storage":
            names = [p.name.casefold() for p in ancestor.parents]
            if any("zotero" in n for n in names) or (ancestor.parent / "zotero.sqlite").exists():
                raise PDFError("zotero_storage_output", "Writing OCR output inside Zotero storage is forbidden.")
    return target


def atomic_json(path, data):
    temp = path.with_name(path.name + ".pending")
    with temp.open("x", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def run_engine(command, timeout):
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, stdout + stderr
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
        raise PDFError("ocr_timeout", "OCR process group was terminated after the configured timeout.")


def ocr_pdf(value, output_bundle, mode="skip", languages="chi_sim+eng", engine=None,
            timeout=600, storage_paths=()):
    result = {"ok": False, "operation": "ocr", "status": "failed", "mode": mode,
              "source": str(Path(value).expanduser()), "original_written_by_tool": False}
    bundle = None
    started = time.time()
    source = None
    try:
        if mode not in ("skip", "redo", "force") or timeout <= 0:
            raise PDFError("invalid_option", "Use mode skip, redo, or force and a positive timeout.")
        if not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", languages):
            raise PDFError("invalid_language", "Use OCR language names joined with +.")
        source = source_path(value)
        target = safe_output_bundle(output_bundle, source, storage_paths)
        before = inspect_pdf(source, all_pages=True)
        result.update(source=str(source), source_sha256=before.get("sha256"), source_page_count=before.get("page_count"))
        if not before["ok"]:
            raise PDFError(before["status"], before["error"]["message"])
        executable = engine or shutil.which("ocrmypdf") or "/opt/homebrew/bin/ocrmypdf"
        if not Path(executable).is_file() or not os.access(executable, os.X_OK):
            raise PDFError("ocr_unavailable", "No existing OCRmyPDF executable was found; nothing was installed.")
        # Atomic mkdir is the concurrency lock. Never re-use an existing/partial bundle.
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            raise PDFError("output_exists", "Another operation already created the output bundle.")
        bundle = target
        result["output_bundle"] = str(bundle)
        atomic_json(bundle / "status.json", {"status": "running", "source_sha256": before["sha256"]})
        stage = bundle / ".working"
        stage.mkdir(mode=0o700)
        snapshot = stage / "source.pdf"
        shutil.copyfile(source, snapshot)
        if sha256(snapshot) != before["sha256"]:
            raise PDFError("source_changed", "Input changed while creating the private OCR snapshot.")
        staged_pdf, staged_sidecar = stage / "document.pdf", stage / "ocr-sidecar.txt"
        flag = {"skip": "--skip-text", "redo": "--redo-ocr", "force": "--force-ocr"}[mode]
        # Both destinations are new inside our atomically created private directory.
        # Do not require the --no-overwrite option added only in OCRmyPDF 17.4.
        command = [str(executable), "--output-type", "pdf", "--optimize", "0",
                   "--jobs", "1", flag, "--language", languages, "--sidecar", str(staged_sidecar),
                   str(snapshot), str(staged_pdf)]
        code, log = run_engine(command, timeout)
        (bundle / "ocr.log").write_text(log, encoding="utf-8")
        result.update(engine_exit_code=code, languages=languages)
        if code != 0:
            raise PDFError("ocr_failed", "OCRmyPDF failed; inspect ocr.log in the failed bundle.")
        checked = inspect_pdf(staged_pdf, all_pages=True)
        result["output_inspection"] = checked
        if not checked["ok"] or checked.get("page_count") != before["page_count"]:
            raise PDFError("output_validation_failed", "OCR output is unreadable or its page count changed.")
        if not any(p["status"] == "text" for p in checked["page_results"]):
            raise PDFError("no_readable_output_text", "No output page contains a usable amount of extractable text.")
        if any(p["status"] == "extraction_failed" for p in checked["page_results"]):
            raise PDFError("output_validation_failed", "Some output pages could not be text-checked.")
        if sha256(source) != before["sha256"]:
            raise PDFError("source_changed", "Original source changed externally during OCR; bundle is not marked complete.")
        doc = Document(staged_pdf)
        try:
            with (stage / "document-text.txt").open("x", encoding="utf-8") as f:
                for index in range(doc.pages):
                    f.write(f"\n--- PDF page {index + 1} ---\n" + doc.text(index) + "\n")
        finally:
            doc.close()
        if not staged_sidecar.is_file():
            staged_sidecar.write_text("[OCRmyPDF generated no sidecar; see document-text.txt for extracted text.]\n")
        for name in ("document.pdf", "document-text.txt", "ocr-sidecar.txt"):
            os.replace(stage / name, bundle / name)
        snapshot.unlink()
        stage.rmdir()
        result.update(ok=True, status="complete", source_unchanged=True,
                      output_pdf=str(bundle / "document.pdf"), output_sha256=sha256(bundle / "document.pdf"),
                      extracted_text=str(bundle / "document-text.txt"), ocr_sidecar=str(bundle / "ocr-sidecar.txt"),
                      validation={"page_count_matches": True, "all_output_pages_checked": True,
                                  "extractable_text_present": True, "words_manually_verified": False,
                                  "every_page_ocr_completed": "not_guaranteed"},
                      limitations=["Words, formulas, tables, and reading order have not been manually verified.",
                                   "Blank or sparse pages do not prove that every page was OCRed successfully.",
                                   "Default skip mode preserves existing text, including potentially bad OCR; force/redo are never automatic.",
                                   "ocr-sidecar.txt contains newly recognized text only; document-text.txt includes all extractable output text."])
        if checked["pages_needing_review"]:
            result["needs_review"] = True
        checked["input"] = str(bundle / "document.pdf")
    except PDFError as exc:
        result.update(error={"code": exc.code, "message": str(exc)})
    except Exception as exc:
        result.update(error={"code": "operation_failed", "message": type(exc).__name__ + ": local PDF operation failed."})
    finally:
        if source and result.get("source_sha256"):
            try:
                result["source_unchanged"] = sha256(source) == result["source_sha256"]
            except OSError:
                result["source_unchanged"] = False
            if not result["source_unchanged"]:
                result.update(ok=False, status="failed", error={"code": "source_changed",
                              "message": "Original source changed externally; OCR is not marked complete."})
        result["elapsed_seconds"] = round(time.time() - started, 3)
        if bundle:
            result["report"] = str(bundle / "report.json")
            try:
                atomic_json(bundle / "report.json", result)
                (bundle / "status.json").unlink(missing_ok=True)
            except OSError:
                result.update(ok=False, status="failed", error={"code": "report_write_failed",
                              "message": "Cannot publish final report; bundle must not be treated as complete."})
    return result


def main(argv=None):
    parser = JSONParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    inspect = sub.add_parser("inspect")
    inspect.add_argument("input")
    inspect.add_argument("--max-pages", type=int, default=12)
    inspect.add_argument("--all-pages", action="store_true")
    ocr = sub.add_parser("ocr")
    ocr.add_argument("input")
    ocr.add_argument("--output-bundle", required=True)
    ocr.add_argument("--mode", choices=("skip", "redo", "force"), default="skip")
    ocr.add_argument("--languages", default="chi_sim+eng")
    ocr.add_argument("--ocrmypdf", default=None)
    ocr.add_argument("--timeout", type=float, default=600)
    ocr.add_argument("--zotero-storage-path", action="append", default=[])
    try:
        args = parser.parse_args(argv)
        runtime = choose_runtime()
        if Path(runtime).resolve() != Path(sys.executable).resolve():
            os.execv(runtime, [runtime, str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])])
        result = (inspect_pdf(args.input, args.max_pages, args.all_pages) if args.operation == "inspect" else
                  ocr_pdf(args.input, args.output_bundle, args.mode, args.languages,
                          args.ocrmypdf, args.timeout, args.zotero_storage_path))
    except PDFError as exc:
        result = {"ok": False, "status": "error", "error": {"code": exc.code, "message": str(exc)}}
    except OSError as exc:
        result = {"ok": False, "status": "error", "error": {"code": "runtime_error",
                  "message": type(exc).__name__ + ": unable to launch an existing runtime."}}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
