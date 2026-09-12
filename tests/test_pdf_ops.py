"""Local QA intermediates only: no library files or source PDFs are modified."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/pdf_ops.py"
spec = importlib.util.spec_from_file_location("pdf_ops", SCRIPT)
pdf_ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf_ops)


def make_pdf(path, texts, encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream.set_data(f"BT /F1 14 Tf 40 700 Td ({safe}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("QA-password")
    with path.open("wb") as f:
        writer.write(f)
    return path


class PDFOpsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zotero-pdf-qa-")
        self.root = Path(self.temp.name)
        self.text = make_pdf(self.root / "text.pdf", ["Research sample with a meaningful paragraph for PDF text extraction."])
        self.blank = make_pdf(self.root / "blank.pdf", [""])

    def tearDown(self):
        self.temp.cleanup()

    def stub(self, body):
        stub = self.root / "engine"
        stub.write_text(f"#!{sys.executable}\n" + body + "\n")
        stub.chmod(0o700)
        return str(stub)

    def test_missing_and_non_pdf(self):
        self.assertEqual(pdf_ops.inspect_pdf(self.root / "missing.pdf")["status"], "missing_file")
        wrong = self.root / "wrong.pdf"
        wrong.write_text("This filename is not evidence of PDF content.")
        self.assertEqual(pdf_ops.inspect_pdf(wrong)["status"], "not_pdf")

    def test_encrypted_is_not_silently_decrypted(self):
        source = make_pdf(self.root / "encrypted.pdf", ["Secret text"], encrypted=True)
        self.assertEqual(pdf_ops.inspect_pdf(source)["status"], "encrypted")
        result = pdf_ops.ocr_pdf(source, self.root / "encrypted-output")
        self.assertEqual(result["error"]["code"], "encrypted")
        self.assertFalse((self.root / "encrypted-output").exists())

    def test_text_blank_and_mixed_pdf_detection(self):
        self.assertEqual(pdf_ops.inspect_pdf(self.text)["status"], "has_text")
        self.assertEqual(pdf_ops.inspect_pdf(self.blank)["status"], "no_text_layer")
        mixed = make_pdf(self.root / "mixed.pdf", ["This page has plenty of existing digital text.", ""])
        result = pdf_ops.inspect_pdf(mixed, all_pages=True)
        self.assertEqual(result["status"], "partial_pages_need_review")
        self.assertEqual(result["pages_needing_review"], [2])

    def test_sampling_never_claims_complete_document(self):
        source = make_pdf(self.root / "long.pdf", ["Readable research sample with enough words."] * 20)
        result = pdf_ops.inspect_pdf(source, max_pages=3)
        self.assertEqual(result["status"], "partial_pages_unchecked")
        self.assertFalse(result["all_pages_checked"])
        self.assertEqual(result["checked_pages"], 3)
        self.assertEqual(result["page_count"], 20)

    def test_bad_font_mapping_is_flagged_as_heuristic(self):
        source = make_pdf(self.root / "garbled.pdf", ["/g13/g14/g15/g16/g17/g18/g19"])
        self.assertEqual(pdf_ops.inspect_pdf(source)["status"], "suspected_garbled_text")

    def test_same_path_preserves_source(self):
        before = self.text.read_bytes()
        result = pdf_ops.ocr_pdf(self.text, self.text)
        self.assertEqual(result["error"]["code"], "same_path")
        self.assertEqual(self.text.read_bytes(), before)

    def test_existing_output_preserves_sentinel(self):
        bundle = self.root / "output"
        bundle.mkdir()
        sentinel = bundle / "document.pdf"
        sentinel.write_bytes(b"existing user file")
        result = pdf_ops.ocr_pdf(self.text, bundle)
        self.assertEqual(result["error"]["code"], "output_exists")
        self.assertEqual(sentinel.read_bytes(), b"existing user file")

    def test_symlink_output_is_rejected(self):
        link = self.root / "output-link"
        link.symlink_to(self.root / "nonexistent-target")
        result = pdf_ops.ocr_pdf(self.text, link)
        self.assertEqual(result["error"]["code"], "symlink_output")
        self.assertFalse((self.root / "nonexistent-target").exists())

    def test_custom_zotero_storage_and_parent_alias_are_protected(self):
        data = self.root / "MyResearchData"
        data.mkdir()
        (data / "zotero.sqlite").touch()
        storage = data / "storage"
        storage.mkdir()
        alias = self.root / "safe-looking-alias"
        alias.symlink_to(storage, target_is_directory=True)
        for destination in [storage / "new-bundle", alias / "other-bundle"]:
            result = pdf_ops.ocr_pdf(self.text, destination)
            self.assertEqual(result["error"]["code"], "zotero_storage_output")
        self.assertEqual(list(storage.iterdir()), [])

    def test_named_zotero_storage_and_explicit_storage_are_protected(self):
        storage = self.root / "Zotero" / "storage"
        storage.mkdir(parents=True)
        result = pdf_ops.ocr_pdf(self.text, storage / "new-bundle")
        self.assertEqual(result["error"]["code"], "zotero_storage_output")
        extra = self.root / "custom-store"
        extra.mkdir()
        result = pdf_ops.ocr_pdf(self.text, extra / "new-bundle", storage_paths=[extra])
        self.assertEqual(result["error"]["code"], "zotero_storage_output")

    def test_failed_engine_keeps_original_and_never_publishes_success(self):
        before = pdf_ops.sha256(self.text)
        engine = self.stub("import sys; print('QA expected failure', file=sys.stderr); sys.exit(3)")
        bundle = self.root / "failed"
        result = pdf_ops.ocr_pdf(self.text, bundle, engine=engine)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "ocr_failed")
        self.assertEqual(pdf_ops.sha256(self.text), before)
        self.assertTrue(result["source_unchanged"])
        self.assertFalse((bundle / "document.pdf").exists())
        self.assertEqual(json.loads((bundle / "report.json").read_text())["status"], "failed")
        self.assertEqual(pdf_ops.ocr_pdf(self.text, bundle, engine=engine)["error"]["code"], "output_exists")

    def test_page_count_mismatch_is_not_accepted(self):
        wrong = make_pdf(self.root / "two-pages.pdf", ["Enough readable output text for validation."] * 2)
        engine = self.stub(f"import shutil,sys; shutil.copyfile({str(wrong)!r},sys.argv[-1])")
        result = pdf_ops.ocr_pdf(self.text, self.root / "wrong-count", engine=engine)
        self.assertEqual(result["error"]["code"], "output_validation_failed")
        self.assertFalse((self.root / "wrong-count/document.pdf").exists())
        self.assertTrue(result["source_unchanged"])

    def test_success_exit_without_readable_text_is_not_accepted(self):
        engine = self.stub(f"import shutil,sys; shutil.copyfile({str(self.blank)!r},sys.argv[-1])")
        result = pdf_ops.ocr_pdf(self.text, self.root / "empty-output", engine=engine)
        self.assertEqual(result["error"]["code"], "no_readable_output_text")
        self.assertFalse((self.root / "empty-output/document.pdf").exists())

    def test_default_skip_and_explicit_force_flags(self):
        engine = self.stub(f"import shutil,sys; shutil.copyfile({str(self.text)!r},sys.argv[-1]); print(' '.join(sys.argv[1:]))")
        result = pdf_ops.ocr_pdf(self.text, self.root / "skip", engine=engine)
        self.assertTrue(result["ok"])
        log = (self.root / "skip/ocr.log").read_text()
        self.assertIn("--skip-text", log)
        self.assertNotIn("--force-ocr", log)
        forced = pdf_ops.ocr_pdf(self.text, self.root / "force", mode="force", engine=engine)
        self.assertTrue(forced["ok"])
        self.assertIn("--force-ocr", (self.root / "force/ocr.log").read_text())

    def test_engine_without_new_no_overwrite_flag_still_uses_safe_bundle(self):
        engine = self.stub(f"import shutil,sys\nif '--no-overwrite' in sys.argv: sys.exit(2)\nshutil.copyfile({str(self.text)!r},sys.argv[-1])")
        before = self.text.read_bytes()
        destination = self.root / "legacy-engine"
        result = pdf_ops.ocr_pdf(self.text, destination, engine=engine)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.text.read_bytes(), before)
        output_before = (destination / "document.pdf").read_bytes()
        repeated = pdf_ops.ocr_pdf(self.text, destination, engine=engine)
        self.assertEqual(repeated["error"]["code"], "output_exists")
        self.assertEqual((destination / "document.pdf").read_bytes(), output_before)

    def test_timeout_is_structured_and_leaves_source_unchanged(self):
        engine = self.stub("import time; time.sleep(30)")
        result = pdf_ops.ocr_pdf(self.text, self.root / "timeout", engine=engine, timeout=0.1)
        self.assertEqual(result["error"]["code"], "ocr_timeout")
        self.assertTrue(result["source_unchanged"])
        self.assertFalse((self.root / "timeout/document.pdf").exists())

    def test_cli_argument_errors_are_json(self):
        run = subprocess.run([sys.executable, "-B", str(SCRIPT), "ocr", str(self.text)],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads(run.stdout)["error"]["code"], "invalid_arguments")

    def test_one_real_ocr_smoke_on_generated_scan(self):
        engine = shutil.which("ocrmypdf")
        if not engine and Path("/opt/homebrew/bin/ocrmypdf").is_file():
            engine = "/opt/homebrew/bin/ocrmypdf"
        if not engine:
            self.skipTest("Optional OCR executable unavailable; no installation attempted.")
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest("Optional Pillow unavailable; no installation attempted.")
        source = self.root / "qa-scan.pdf"
        # Generate our own image-only fixture; no library, downloaded paper or host file.
        pages = []
        for number in (1, 2):
            page = Image.new("RGB", (1700, 2200), "white")
            draw = ImageDraw.Draw(page)
            font = ImageFont.load_default(size=40)
            lines = ["RESEARCH READING TEST", f"Synthetic page {number}",
                     "This example checks local optical character recognition.",
                     "The original document should remain unchanged.",
                     "Searchable words do not prove perfect recognition.",
                     "Compare important numbers against the visible page."]
            for i, line in enumerate(lines):
                draw.text((100, 180 + i * 100), line, fill="black", font=font)
            pages.append(page)
        pages[0].save(source, "PDF", resolution=200, save_all=True, append_images=pages[1:])
        before = pdf_ops.sha256(source)
        self.assertEqual(pdf_ops.inspect_pdf(source, all_pages=True)["status"], "no_text_layer")
        result = pdf_ops.ocr_pdf(source, self.root / "real-ocr", engine=engine, languages="eng", timeout=180)
        self.assertTrue(result["ok"], result)
        self.assertEqual(pdf_ops.sha256(source), before)
        self.assertTrue(result["validation"]["page_count_matches"])
        self.assertTrue(result["validation"]["all_output_pages_checked"])
        text = Path(result["extracted_text"]).read_text()
        self.assertGreater(len(text), 100)
        self.assertIn("RESEARCH READING TEST", text)
        self.assertTrue(Path(result["ocr_sidecar"]).is_file())
        self.assertEqual(json.loads(Path(result["report"]).read_text())["status"], "complete")
        print(json.dumps({"real_ocr_smoke": "passed", "source_sha256": before,
                          "pages": result["source_page_count"], "text_chars": len(text),
                          "elapsed_seconds": result["elapsed_seconds"]}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
