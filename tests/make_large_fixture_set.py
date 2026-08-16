"""Generates a large synthetic corpus of native-text + a modest number of
scanned PDFs for scale/performance testing (e.g. the 6000-file stress test).

CROSS-PLATFORM NOTE: scanned-PDF generation uses the same reportlab
built-in-font + PyMuPDF-rasterize approach as make_test_pdfs.py. The
deliberate "near-duplicate" pairs in this generator are all NATIVE TEXT
(not OCR'd), so their similarity matching is fully deterministic across
platforms - see make_test_pdfs.py's module docstring for the full
rationale on why OCR text should never be relied on for a hard
near-duplicate-similarity assertion in a cross-platform test suite.
"""
from __future__ import annotations

import io
import random
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
import fitz  # PyMuPDF

_ENTITY_POOL = [
    "Ardent Advisory & Accounting LLC", "Talabat FZ-LLC", "Beta Holdings LLC",
    "Gamma Corp", "Delta Industries LLC", "Epsilon Trading Co", "Zeta Group Ltd",
    "Eta Financial Services LLC", "Theta Logistics FZE", "Iota Retail Group",
    "Kappa Construction LLC", "Lambda Energy Holdings", "Mu Healthcare Group",
    "Nu Technology Solutions LLC", "Xi Manufacturing Co", "Omicron Real Estate LLC",
    "Pi Aviation Holdings", "Rho Hospitality Group", "Sigma Media LLC",
    "Tau Education Trust", "Upsilon Insurance Co", "Phi Telecom LLC",
    "Chi Utilities Group", "Psi Transport LLC", "Omega Consulting Partners",
]
_SECTORS = ["Banking", "Technology", "Healthcare", "Retail", "Construction",
            "Energy", "Aviation", "Hospitality", "Media", "Education"]
_TEMPLATES = {
    "Contracts": [
        "SERVICES AGREEMENT",
        "This Agreement is made between {entity} and Client Co Ltd.",
        "Dated: {date}",
        "This master services agreement sets out the terms and conditions",
        "under which Consulting services will be provided.",
        "In witness whereof the parties have executed this agreement.",
        "The {sector} sector engagement reference is {ref}.",
    ],
    "Engagement Letters": [
        "ENGAGEMENT LETTER",
        "Client: {entity}",
        "Dated: {date}",
        "We are pleased to confirm the terms of our engagement with",
        "{entity} for the provision of advisory services.",
        "This letter sets out the scope of our services covering the",
        "{sector} sector. Ref {ref}.",
    ],
    "Addendums": [
        "ADDENDUM NO. {ref}",
        "This Amendment amends the original agreement between {entity}",
        "and Client Co Ltd, dated {date}.",
        "This deed of variation updates the scope of the supplemental",
        "agreement for the {sector} sector engagement.",
    ],
}


def make_native_pdf(path: Path, lines) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 60
    for line in lines:
        c.drawString(50, y, line[:110])
        y -= 16
        if y < 50:
            c.showPage()
            y = height - 60
    c.save()


def make_scanned_pdf(path: Path, lines, dpi: int = 200) -> None:
    """See make_test_pdfs.py's make_scanned_pdf() docstring for the full
    cross-platform rationale."""
    text_buf = io.BytesIO()
    c = canvas.Canvas(text_buf, pagesize=A4)
    c.setFont("Helvetica", 14)
    width, height = A4
    y = height - 60
    for line in lines:
        c.drawString(50, y, line[:110])
        y -= 20
        if y < 50:
            c.showPage()
            c.setFont("Helvetica", 14)
            y = height - 60
    c.save()
    text_buf.seek(0)

    src_doc = fitz.open(stream=text_buf.read(), filetype="pdf")
    page = src_doc.load_page(0)
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    src_doc.close()

    img = ImageReader(io.BytesIO(png_bytes))
    out_c = canvas.Canvas(str(path), pagesize=A4)
    out_c.drawImage(img, 0, 0, width=width, height=height)
    out_c.save()


def build_large_fixture_set(out_dir: Path, n_files: int, n_scanned: int = 30,
                              seed: int = 42) -> int:
    rng = random.Random(seed)
    out_dir.mkdir(parents=True, exist_ok=True)

    doc_types = list(_TEMPLATES.keys())
    n_exact_dups = max(1, n_files // 100)
    n_near_dups = max(1, n_files // 100)

    dup_source_lines = []
    created = 0
    idx = 0
    while created < n_files - n_exact_dups - n_near_dups - n_scanned - 1:
        idx += 1
        doc_type = doc_types[idx % len(doc_types)]
        entity = rng.choice(_ENTITY_POOL)
        sector = rng.choice(_SECTORS)
        year = rng.randint(2022, 2026)
        month = rng.randint(1, 12)
        day = rng.randint(1, 28)
        date_str = f"{day:02d}/{month:02d}/{year}"
        ref = rng.randint(1000, 9999)
        lines = [line.format(entity=entity, date=date_str, sector=sector, ref=ref)
                  for line in _TEMPLATES[doc_type]]
        fname = f"doc_{idx:05d}_{doc_type.replace(' ', '')}.pdf"
        make_native_pdf(out_dir / fname, lines)
        if len(dup_source_lines) < (n_exact_dups + n_near_dups) * 2:
            dup_source_lines.append(lines)
        created += 1

    for i in range(n_exact_dups):
        lines = dup_source_lines[i % len(dup_source_lines)]
        make_native_pdf(out_dir / f"dup_exact_{i:04d}.pdf", lines)
        created += 1

    for i in range(n_near_dups):
        lines = dup_source_lines[(i + n_exact_dups) % len(dup_source_lines)]
        # Native-text near-duplicate (deterministic across platforms, no OCR involved).
        modified = [
            line.replace("This Amendment", "This amendment", 1)
                .replace("under which", "whereby")
                .replace("We are pleased", "We are very pleased", 1)
                .replace("This master services agreement sets out",
                         "This master services agreement hereby sets out", 1)
            for line in lines
        ]
        if modified == lines:
            modified = list(lines)
            if modified:
                modified[0] = modified[0] + "."
        make_native_pdf(out_dir / f"dup_near_{i:04d}.pdf", modified)
        created += 1

    for i in range(n_scanned):
        entity = rng.choice(_ENTITY_POOL)
        sector = rng.choice(_SECTORS)
        lines = [line.format(entity=entity, date="10/05/2025", sector=sector, ref=5000 + i)
                  for line in _TEMPLATES["Engagement Letters"]]
        make_scanned_pdf(out_dir / f"scanned_{i:04d}.pdf", lines)
        created += 1

    (out_dir / "zzz_corrupt.pdf").write_bytes(b"not a real pdf, just garbage bytes")
    created += 1

    return created


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    out = Path(__file__).resolve().parent / "large_test_pdfs"
    count = build_large_fixture_set(out, n_files=n)
    print(f"Generated {count} files in {out}")
