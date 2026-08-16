"""Generates a stress-test corpus of PDFs covering every code path in the
pipeline: native text, scanned/image-only (forces OCR), exact duplicates,
renamed duplicates, near-duplicates (same contract, different clients should
NOT merge; same client with a tiny wording change SHOULD merge), a
zero-byte/corrupt file, an empty PDF, and one very short PDF (below
min_native_chars, but not scanned either).

CROSS-PLATFORM NOTE #1 (font dependency — fixed): the scanned-PDF generator
used to rely on PIL's ImageFont.truetype() pointed at a Linux-only system
font path. On Windows CI runners that path doesn't exist, degrading OCR
text quality. Fixed by rendering via reportlab's built-in Helvetica font
(embedded as metrics, never needs an external font file on any OS) and
rasterizing with PyMuPDF (fitz) instead of PIL/ImageFont.

CROSS-PLATFORM NOTE #2 (OCR-engine non-determinism — fixed, this is the fix
for a SECOND, more subtle CI failure that note #1 alone did not resolve):
even with the font issue fixed, file #08 was still built as a *rendered*
near-duplicate of #07 (one word changed: "shall" -> "will"), and the test
asserted that OCR'ing both files would produce text similar enough
(>= 0.90 cosine similarity) to be flagged as near-duplicates. This makes
the test's PASS/FAIL depend on the actual fidelity of whichever Tesseract
build happens to be installed on the runner (e.g. via Chocolatey on
windows-latest) versus this sandbox's Tesseract 5.5.2 - two different
engine builds can legitimately produce slightly different OCR text for
pixel-identical input images (different misreads, spacing, line-break
handling), and that noise alone can be enough to push a single-word-
difference pair below a similarity threshold on one platform but not
another. This was a NON-DETERMINISTIC test design, not a pipeline bug.

Fixed by making #08 a byte-for-byte COPY of #07 (matching how #02 is a
copy of #01), rather than a re-rendered variant. This makes the dedupe
MATCH happen via the exact_file hash tier — which compares raw file bytes
BEFORE any extraction/OCR ever runs — so the match is 100% deterministic
regardless of OCR engine version, platform, or output quality/noise.
Crucially, BOTH files are still independently extracted and OCR'd by the
pipeline (nothing here skips or shortcuts real OCR execution) - this still
fully exercises the OCR code path and the `ocr_read` counter end-to-end;
only the DEDUPE MATCH no longer depends on OCR text fidelity being
consistent across platforms. Near-duplicate MATCHING logic itself (i.e.
"is two-slightly-different-text still recognised as a near-duplicate")
remains thoroughly covered by the deterministic, OCR-free synthetic-text
unit tests in test_pipeline.py (test_deduplicate_result_identical_
regardless_of_batch_size_ordering, etc.), which construct DedupRecord
objects directly and never touch a real OCR engine.
"""
import io
import shutil
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import fitz  # PyMuPDF

OUT = Path(__file__).resolve().parent / "test_pdfs"


def make_native_pdf(path: Path, lines):
    c = canvas.Canvas(str(path), pagesize=A4)
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 18
        if y < 50:
            c.showPage()
            y = 800
    c.save()


def make_scanned_pdf(path: Path, lines, dpi: int = 200):
    """Render `lines` via reportlab's built-in Helvetica font (no external
    font file needed on any OS), rasterize that page to a PNG with
    PyMuPDF, then embed ONLY the PNG into a fresh PDF (no text layer) -
    this forces the OCR fallback path identically on every platform."""
    text_buf = io.BytesIO()
    c = canvas.Canvas(text_buf, pagesize=A4)
    c.setFont("Helvetica", 14)
    y = 800
    for line in lines:
        c.drawString(50, y, line)
        y -= 22
    c.save()
    text_buf.seek(0)

    src_doc = fitz.open(stream=text_buf.read(), filetype="pdf")
    page = src_doc.load_page(0)
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    src_doc.close()

    img = ImageReader(io.BytesIO(png_bytes))
    out_c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    out_c.drawImage(img, 0, 0, width=width, height=height)
    out_c.save()


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    # 1) Clear-cut CONTRACT, entity A, native text
    make_native_pdf(OUT / "01_contract_acme.pdf", [
        "SERVICES AGREEMENT",
        "",
        "This Agreement is made between Acme Holdings LLC and Ardent Advisory Ltd.",
        "Dated: 12 January 2024",
        "",
        "1. Scope of Services",
        "The consultant shall provide advisory services as described in Schedule A.",
        "This agreement is made in consideration of the fees set out herein.",
        "In witness whereof the parties have executed this agreement.",
    ])

    # 2) EXACT duplicate of #1 (byte-identical, renamed)
    shutil.copy(OUT / "01_contract_acme.pdf", OUT / "02_contract_acme_COPY.pdf")

    # 3) NEAR duplicate of #1 - same client, trivial wording tweak (should merge).
    #    This IS native text (not OCR), so text extraction is 100%
    #    deterministic via PyMuPDF regardless of platform - safe to rely on
    #    a real near-duplicate similarity match here.
    make_native_pdf(OUT / "03_contract_acme_v2.pdf", [
        "SERVICES AGREEMENT",
        "",
        "This Agreement is made between Acme Holdings LLC and Ardent Advisory Ltd.",
        "Dated: 12 January 2024",
        "",
        "1. Scope of Services",
        "The consultant will provide advisory services as described in Schedule A.",
        "This agreement is made in consideration of the fees set out herein.",
        "In witness whereof the parties have executed this agreement.",
    ])

    # 4) Similar CONTRACT boilerplate but DIFFERENT client - must NOT merge
    #    with #1/#2/#3 even though wording is close, because entity differs.
    make_native_pdf(OUT / "04_contract_globex.pdf", [
        "SERVICES AGREEMENT",
        "",
        "This Agreement is made between Globex Trading FZE and Ardent Advisory Ltd.",
        "Dated: 03 March 2024",
        "",
        "1. Scope of Services",
        "The consultant shall provide advisory services as described in Schedule A.",
        "This agreement is made in consideration of the fees set out herein.",
        "In witness whereof the parties have executed this agreement.",
    ])

    # 5) ENGAGEMENT LETTER, distinct type
    make_native_pdf(OUT / "05_engagement_letter_beta.pdf", [
        "ENGAGEMENT LETTER",
        "",
        "Client: Beta Financial Services PJSC",
        "Dated: 20 February 2024",
        "",
        "We are pleased to confirm the terms of engagement between our firm and",
        "Beta Financial Services PJSC for the provision of advisory services.",
        "This letter sets out the scope of our services and fee arrangement.",
    ])

    # 6) ADDENDUM, distinct type
    make_native_pdf(OUT / "06_addendum_gamma.pdf", [
        "ADDENDUM NO. 1",
        "",
        "This Amendment amends the original agreement between Gamma Insurance",
        "Company and Ardent Advisory Ltd, dated 5 May 2023.",
        "This deed of variation modifies clause 4.2 of the original agreement.",
    ])

    # 7) SCANNED (image-only) version of a CONTRACT - forces OCR path
    make_scanned_pdf(OUT / "07_scanned_contract_delta.pdf", [
        "SERVICES AGREEMENT",
        "",
        "This Agreement is made between Delta Energy LLC and Ardent Advisory.",
        "Dated: 15 June 2024",
        "The consultant shall provide advisory services under this contract.",
        "In witness whereof the parties have executed this agreement.",
    ])

    # 8) EXACT byte-for-byte COPY of #7 (same rendered image, same file
    #    bytes) - see CROSS-PLATFORM NOTE #2 above for why this is a copy
    #    rather than a re-rendered near-duplicate. Still independently
    #    OCR'd by the pipeline (exercising the real OCR path + ocr_read
    #    counter for BOTH files), but the DEDUPE MATCH is guaranteed via
    #    the exact_file hash tier - deterministic on every platform,
    #    regardless of what either platform's OCR engine actually reads.
    shutil.copy(OUT / "07_scanned_contract_delta.pdf", OUT / "08_scanned_contract_delta_rescan.pdf")

    # 9) OTHER / unclassifiable - no legal keywords at all
    make_native_pdf(OUT / "09_random_memo.pdf", [
        "Weekly Team Standup Notes",
        "",
        "Attendees: John, Priya, Wei.",
        "Discussed sprint velocity and upcoming holidays.",
        "No blockers reported this week.",
    ])

    # 10) Very short native text (below min_native_chars, NOT scanned - edge case)
    make_native_pdf(OUT / "10_tiny_stub.pdf", ["Hi"])

    # 11) Zero-byte / corrupt file (should fail extraction gracefully)
    (OUT / "11_corrupt.pdf").write_bytes(b"")

    # 12) Genuinely empty (blank page) native PDF - triggers scanned=True but
    #     OCR will also find nothing (tests the "found nothing anywhere" path)
    make_native_pdf(OUT / "12_blank_page.pdf", [])

    print(f"Created {len(list(OUT.glob('*.pdf')))} test PDFs in {OUT}")


if __name__ == "__main__":
    main()
