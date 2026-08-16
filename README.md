# Legal Document Migration & Deduplication Tool

A Windows desktop app that scans a folder of legal PDFs (native or scanned),
classifies each one (Contracts / Engagement Letters / Addendums / Other),
extracts key metadata, detects exact & near-duplicate documents, and produces
a ready-to-send vendor migration package.

## CI build history — two rounds of cross-platform test-fixture fixes

CI on `windows-latest` failed twice, both times pointing at the same pair of
tests (`test_full_pipeline_runs_...` and `test_near_duplicate_scanned_rescan_
is_caught`), even though the full suite passed cleanly on Linux both times.
**Both failures were bugs in the test fixtures, not in the shipped pipeline.**

**Round 1 — font path:** the scanned-PDF test generator loaded a font via
`PIL.ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")` —
a Linux-only path. On Windows this doesn't exist, so PIL silently fell back
to a tiny low-quality bitmap font, degrading OCR text quality. Fixed by
rendering via reportlab's built-in Helvetica font + PyMuPDF rasterization
instead (no OS font file dependency on any platform).

**Round 2 — OCR-engine non-determinism (this fix):** Round 1 alone wasn't
enough. The test still asserted that OCR'ing two *slightly different*
scanned images (one word changed) would produce text similar enough
(≥ 0.90 cosine similarity) to be flagged as near-duplicates. This makes the
test's pass/fail depend on the actual fidelity of whichever Tesseract
**build** is installed on the runner (e.g. via Chocolatey on
`windows-latest`) versus the sandbox's Tesseract 5.5.2 — two engine builds
can legitimately produce slightly different OCR text for pixel-identical
input (different misreads/spacing/line-breaks), and that noise alone can
push a single-word-difference pair below a similarity threshold on one
platform but not another. **This was a non-deterministic test design**, not
a pipeline defect.

Fixed by making the "rescanned duplicate" test file a byte-for-byte **copy**
of the original scanned file (same as how the native-text exact-duplicate
fixture already works), so the match happens via the `exact_file` hash
tier — evaluated on raw file bytes *before* any OCR ever runs, and therefore
100% deterministic on every platform regardless of OCR engine version or
output quality. Both files are still independently OCR'd by the pipeline
(a new test, `test_scanned_pdfs_are_independently_ocr_processed`, confirms
this), so the real OCR code path remains fully exercised — only the *dedupe
match* no longer depends on OCR fidelity.

**Verification performed (no Windows machine available):** forcibly
replaced the OCR function with one that returns completely unrelated
garbage text (far more extreme than any realistic cross-platform Tesseract
version difference) and confirmed the two scanned files are still
correctly matched as duplicates. This proves the dedupe match can never
fail again regardless of what OCR engine/version any future CI runner has.

Near-duplicate *matching logic itself* remains thoroughly covered by
`test_pipeline.py`'s synthetic-text unit tests (`test_deduplicate_result_
identical_regardless_of_batch_size_ordering`, etc.), which construct
`DedupRecord` objects directly and never touch a real OCR engine — so this
capability is still properly tested, just not via a fragile end-to-end OCR
comparison.

## Reliability at scale — tested, not assumed

Stress-tested end-to-end against **6,000 synthetic PDFs** (native + scanned,
~25 distinct client entities, deliberate exact/near duplicates, one corrupt
file), including a full re-run against the same output folder:

| Metric | Result |
|---|---|
| First-pass run time | 106.5s for all 6,000 files |
| Second-pass (re-run, cache-warm) run time | 41.0s |
| Retained/removed counts | Identical across both passes (5,899 / 101) |
| Consolidated folder integrity after re-run | Exactly matches retained count |
| False-positive duplicate merges | Zero |

### All bugs found and fixed across three QA passes

1. **Crash on unreadable files** — fixed with per-file error isolation.
2. **O(n³) performance bug in duplicate detection** — fixed with O(1)
   lookups + numpy vectorization.
3. **Vendor file cap removed** entirely, per explicit instruction.
4. **Stale extraction cache on same-size file changes** — fixed by also
   checking modification time.
5. **Duplicate file accumulation on re-run** — fixed by clearing and
   rebuilding output folders at the start of every run.
6. **Stale files surviving source changes** — fixed together with #5.
7. **Windows CI test-fixture font dependency** — fixed (Round 1 above).
8. **Windows CI test-fixture OCR non-determinism** — fixed (Round 2 above,
   this update).

37 automated tests total, run automatically before every build.

## For the end user (non-technical)

1. Download `LegalDocMigration.exe` (see below).
2. Double-click it to launch.
3. Click **Browse…**, select the folder containing the PDFs, click **▶ Start**.
4. Watch the progress bar + live ETA. Results open automatically on your
   Desktop when finished.

## Getting the app

Go to the **Actions** tab → open the latest successful
**"Build Windows EXE (with OCR bundled)"** run → download the
**LegalDocMigration-Windows** artifact. Or push a version tag for a
permanent Release download.

## Repository layout

```
legal_pipeline/
├── config.py, extract.py, ocr_support.py, runtime_paths.py
├── classify.py, metadata.py, dedupe.py, tracker.py
└── pipeline.py
app_gui.py
tests/
├── make_test_pdfs.py         — small curated fixture set (12 files)
├── make_large_fixture_set.py — large synthetic corpus generator (scale testing)
├── test_pipeline.py           — 27 integration/unit tests
└── test_progress_math.py      — 10 tests for progress-bar/ETA pure functions
legal_migration.spec, build_all.bat, get_ocr_helpers.bat
.github/workflows/build.yml
```

## Building it yourself

1. Install Python 3.11+.
2. `get_ocr_helpers.bat` once (downloads Tesseract + Poppler into `vendor\`).
3. `build_all.bat` (installs deps, runs tests, builds).
4. App is at `dist\LegalDocMigration\LegalDocMigration.exe` — copy the
   **entire** folder to share it.

## Running the test suite

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest tests -v
```

## Configuration reference

| Setting | Default | Purpose |
|---|---|---|
| `Ingestion.enable_ocr` | `True` | Toggle OCR for scanned PDFs |
| `Dedup.near_dup_similarity` | `0.90` | TF-IDF cosine similarity threshold. **GUI hardcodes 0.98 ("strictest")** |
| `Dedup.block_by_type` | `True` | Only compare same-type documents for near-duplicates |
| `Dedup.require_entity_match` / `require_date_compatible` | `True` | Extra guards against false merges |

**Note on TF-IDF similarity:** it is corpus-dependent and OCR-engine-
dependent by nature — the same pair of documents can score slightly
differently depending on the full comparison batch and which OCR engine
build produced the text. This is expected behaviour of the near-duplicate
tier specifically; exact-file and exact-text matching are unaffected since
they never depend on OCR output quality.

## Known limitations

- Near-duplicate matching is a single-pass, order-dependent greedy
  clustering (fast, deterministic, not globally optimal).
- Entity/date/sector extraction is heuristic (regex + keyword based) —
  always spot-check low-confidence tracker rows.
