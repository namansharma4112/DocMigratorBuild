"""
app_gui.py - desktop front-end (PyInstaller entry point).

v2.1 fix (2026-08-16): Two issues could make the "Start" button (or other
widgets) appear missing on some Windows PCs:

  1. DPI SCALING: Tkinter does not automatically adapt to Windows display
     scaling (125%/150%/175%, common on laptops and high-res monitors).
     Without declaring DPI awareness, Windows can rescale the rendered
     window while Tkinter still thinks it's the original logical size,
     which can push bottom-of-layout widgets (like the Start button, if a
     window opens smaller than its content) out of the visible area.
     FIX: call SetProcessDpiAwareness via ctypes before creating the Tk
     root - the standard fix for this class of problem.

  2. EMOJI/UNICODE BUTTON LABELS: previous version used glyphs like
     "[play] Start", "[folder] Open results folder", etc. directly in widget text.
     On some Windows locale/codepage configurations - especially inside a
     frozen PyInstaller .exe without explicit UTF-8 setup - these can fail
     to render, leaving a widget with blank/invisible text that looks like
     it "isn't there" even though the button itself still exists.
     FIX: replaced all emoji glyphs with plain ASCII-safe labels. Visual
     interest is now carried entirely by color/weight/layout instead of
     unicode symbols, which is guaranteed to render on any Windows setup.

v2.0 - modernised UI (card-based layout, 7-phase accurate progress bar,
threaded pipeline run). See PROGRESS_BANDS / compute_progress_percent for
the pure, unit-tested progress math (tests/test_progress_math.py).

v1.3 fix (kept): pipeline.run() is called with the CORRECT keyword names
(log=, progress=) matching pipeline.py's real signature; _progress() and
_apply_progress() accept the 4th positional argument (filename) that
pipeline.py's stage_extract()/stage_enrich()/stage_organise() pass on
every call: progress(phase, i, total, name).
"""
from __future__ import annotations
import datetime as _dt
import os
import queue
import sys
import threading
import traceback
from pathlib import Path

# --------------------------------------------------------------------
# DPI awareness MUST be set before any Tk window is created. Without
# this, Windows display scaling can silently shrink/clip the rendered
# window relative to what Tkinter thinks its size is, hiding bottom
# widgets (e.g. the Start button) even though the layout code is correct.
# This is a no-op (silently ignored) on non-Windows platforms.
# --------------------------------------------------------------------
if sys.platform == "win32":
    try:
        import ctypes
        try:
            # Per-monitor DPI aware (most accurate, Windows 8.1+)
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                # System DPI aware fallback (Vista+)
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from legal_pipeline.config import Config
from legal_pipeline import runtime_paths
from legal_pipeline.pipeline import run as run_pipeline

APP_TITLE = "Legal Document Migration & Deduplication"
APP_SUBTITLE = "Sort, classify, and de-duplicate legal PDFs - ready for vendor upload."

# ---------------------------------------------------------------- Palette --
COLOR_BG = "#F4F6F9"
COLOR_CARD = "#FFFFFF"
COLOR_BORDER = "#E2E6EC"
COLOR_HEADER_BG = "#12233F"
COLOR_HEADER_TEXT = "#FFFFFF"
COLOR_HEADER_SUB = "#B7C4D9"
COLOR_ACCENT = "#2563EB"
COLOR_ACCENT_DARK = "#1D4ED8"
COLOR_TEXT = "#1F2937"
COLOR_MUTED = "#5B6472"
COLOR_LOG_BG = "#0F1720"
COLOR_LOG_TEXT = "#D6E2EE"

STRICTEST_SIMILARITY = 0.98

# Plain ASCII-safe labels only - no emoji/unicode glyphs (see v2.1 fix note
# above for why). Visual distinction comes from bold text + colour instead.
PHASE_META = {
    "scan":     "Scanning folder",
    "extract":  "Reading documents",
    "enrich":   "Analysing documents",
    "dedupe":   "Finding duplicates",
    "organise": "Organising files",
    "tracker":  "Building the tracker",
    "done":     "Finished",
}

PROGRESS_BANDS = {
    "scan":     (0, 3),
    "extract":  (3, 45),
    "enrich":   (45, 80),
    "dedupe":   (80, 83),
    "organise": (83, 97),
    "tracker":  (97, 99),
    "done":     (99, 100),
}


def compute_progress_percent(phase: str, current: int, total: int, last_pct: float = 0.0) -> float:
    """Pure function: maps a (phase, current, total) progress event to an
    overall 0-100 percentage. No Tk/UI dependency - unit tested separately
    in tests/test_progress_math.py."""
    if phase not in PROGRESS_BANDS:
        return last_pct
    lo, hi = PROGRESS_BANDS[phase]
    if phase == "done":
        return 100.0
    if total and total > 0:
        frac = max(0.0, min(1.0, current / total))
        return lo + (hi - lo) * frac
    return float(hi)


def desktop_dir() -> Path:
    home = Path(os.path.expanduser("~"))
    for c in [home / "Desktop", home / "OneDrive" / "Desktop"]:
        if c.exists():
            return c
    if os.name == "nt":
        for p in home.glob("OneDrive*/Desktop"):
            return p
    return home


def open_folder(path: Path):
    try:
        if os.name == "nt":
            os.startfile(str(path))                      # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        # Slightly taller default + a larger minsize floor than before, so
        # that even if a user's screen is smaller/scaled, the window still
        # requests enough room for every widget - including the Start
        # button - to be visible without needing to resize manually.
        self.geometry("860x700")
        self.minsize(760, 620)
        self.configure(background=COLOR_BG)

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._prog_q: "queue.Queue[tuple]" = queue.Queue()
        self._worker: "threading.Thread | None" = None
        self._out_dir: "Path | None" = None
        self._progress_pct: float = 0.0

        self._init_style()
        self._build_ui()
        self.after(100, self._drain_log)
        self.after(80, self._drain_progress)

        # Centre the window on screen and ensure it is raised above other
        # windows on first launch - guards against it opening off-screen or
        # behind other apps, which can look identical to "missing" widgets.
        self.update_idletasks()
        self._center_on_screen()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))

    def _center_on_screen(self):
        w = self.winfo_width()
        h = self.winfo_height()
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    # ------------------------------------------------------------- style --
    def _init_style(self):
        style = ttk.Style(self)
        # v2.2 fix (2026-08-16): FORCE "clam" - do NOT use "vista".
        #
        # Root cause of the invisible Start button (confirmed from user
        # screenshot): Windows' native "vista" ttk theme silently IGNORES
        # custom `background` colour on TButton (it draws its own native
        # button chrome regardless of style.configure), while it STILL
        # applies a custom `foreground` colour. Accent.TButton below sets
        # foreground="#FFFFFF" (white) assuming the background would also
        # become the blue accent colour - under "vista" the background
        # silently stays the native light-grey, producing white text on a
        # near-white/light-grey button = invisible text. This is not a
        # timing/rendering glitch, it is deterministic "vista" behaviour.
        # "clam" fully honours both background and foreground for TButton,
        # so it is used unconditionally (no more theme-preference loop)
        # to guarantee the Start button is always visible, on every
        # Windows machine, regardless of OS theme/version.
        available = style.theme_names()
        if "clam" in available:
            style.theme_use("clam")
        else:
            # Extremely unlikely (clam ships with every standard Tk/ttk
            # install), but fall back gracefully rather than crash.
            for candidate in ("default", "alt"):
                if candidate in available:
                    try:
                        style.theme_use(candidate)
                        break
                    except tk.TclError:
                        continue

        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT,
                        font=("Segoe UI", 10))
        style.configure("Card.TFrame", background=COLOR_CARD)
        style.configure("Header.TFrame", background=COLOR_HEADER_BG)
        style.configure("TLabelframe", background=COLOR_CARD, bordercolor=COLOR_BORDER)
        style.configure("TLabelframe.Label", background=COLOR_CARD,
                        foreground=COLOR_MUTED, font=("Segoe UI", 9, "bold"))
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Card.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("Muted.TLabel", background=COLOR_BG, foreground=COLOR_MUTED)
        style.configure("CardMuted.TLabel", background=COLOR_CARD, foreground=COLOR_MUTED)
        style.configure("HeaderTitle.TLabel", background=COLOR_HEADER_BG,
                        foreground=COLOR_HEADER_TEXT, font=("Segoe UI", 17, "bold"))
        style.configure("HeaderSub.TLabel", background=COLOR_HEADER_BG,
                        foreground=COLOR_HEADER_SUB, font=("Segoe UI", 10))
        style.configure("Phase.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT,
                        font=("Segoe UI", 11, "bold"))
        style.configure("Pct.TLabel", background=COLOR_CARD, foreground=COLOR_ACCENT,
                         font=("Segoe UI", 11, "bold"))

        # NOTE: "clam" (forced above) fully honours both background and
        # foreground style options for TButton, so this reliably renders
        # as a solid blue button with white text on every Windows machine.
        style.configure("Accent.TButton", font=("Segoe UI", 11, "bold"),
                        foreground="#FFFFFF", background=COLOR_ACCENT,
                        padding=(18, 10), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", COLOR_ACCENT_DARK), ("disabled", "#93A5C4")],
                  foreground=[("disabled", "#E5E9F0")])
        style.configure("Secondary.TButton", font=("Segoe UI", 10),
                        padding=(12, 7))

        style.configure("Accent.Horizontal.TProgressbar",
                         troughcolor="#E7EBF1", background=COLOR_ACCENT,
                         bordercolor="#E7EBF1", lightcolor=COLOR_ACCENT,
                         darkcolor=COLOR_ACCENT, thickness=16)

        style.configure("TCheckbutton", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("TEntry", padding=6)

    # ---------------------------------------------------------------- UI --
    def _card(self, parent, title=None):
        outer = ttk.Frame(parent, style="TFrame")
        card = tk.Frame(outer, background=COLOR_CARD, highlightbackground=COLOR_BORDER,
                        highlightthickness=1, bd=0)
        card.pack(fill="both", expand=True)
        if title:
            ttk.Label(card, text=title, style="CardMuted.TLabel",
                      font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
        return outer, card

    def _build_ui(self):
        header = tk.Frame(self, background=COLOR_HEADER_BG)
        header.pack(fill="x")
        inner = ttk.Frame(header, style="Header.TFrame")
        inner.pack(fill="x", padx=24, pady=(18, 16))
        ttk.Label(inner, text=APP_TITLE, style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(inner, text=APP_SUBTITLE, style="HeaderSub.TLabel").pack(anchor="w", pady=(4, 0))

        body = ttk.Frame(self, style="TFrame")
        body.pack(fill="both", expand=True, padx=18, pady=16)

        folder_outer, folder_card = self._card(body, "STEP 1 - SELECT FOLDER")
        folder_outer.pack(fill="x", pady=(0, 12))
        frm = ttk.Frame(folder_card, style="Card.TFrame")
        frm.pack(fill="x", padx=14, pady=(6, 14))
        ttk.Label(frm, text="PDF folder:", style="Card.TLabel").pack(side="left")
        self.src_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.src_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(frm, text="Browse...", style="Secondary.TButton",
                   command=self._browse).pack(side="left")

        opt_outer, opt_card = self._card(body, "STEP 2 - OPTIONS")
        opt_outer.pack(fill="x", pady=(0, 12))
        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_card, text="Read scanned PDFs with OCR (slower, needed for scans)",
                        variable=self.ocr_var, style="TCheckbutton").pack(anchor="w", padx=14, pady=(6, 4))
        ttk.Label(opt_card, text="Duplicate detection: strictest - only near-identical copies "
                                 "are merged; exact duplicates are always removed.",
                  style="CardMuted.TLabel").pack(anchor="w", padx=14, pady=(0, 12))

        # --- Action row: Start / Open results folder ---
        # Given its own clearly-separated frame with generous padding so it
        # cannot be visually confused with any other section, and packed
        # BEFORE the progress/log cards so it is never pushed out of view
        # first if the window is short on vertical space.
        act = ttk.Frame(body, style="TFrame")
        act.pack(fill="x", pady=(0, 14))
        self.start_btn = ttk.Button(act, text="Start", style="Accent.TButton",
                                    command=self._start)
        self.start_btn.pack(side="left", ipadx=6, ipady=2)
        self.open_btn = ttk.Button(act, text="Open results folder", style="Secondary.TButton",
                                   command=self._open_results, state="disabled")
        self.open_btn.pack(side="left", padx=10)

        prog_outer, prog_card = self._card(body, "PROGRESS")
        prog_outer.pack(fill="x", pady=(0, 12))
        prog_inner = ttk.Frame(prog_card, style="Card.TFrame")
        prog_inner.pack(fill="x", padx=14, pady=(6, 14))

        status_row = ttk.Frame(prog_inner, style="Card.TFrame")
        status_row.pack(fill="x")
        self.phase_var = tk.StringVar(value="Ready. Choose a folder and click Start.")
        ttk.Label(status_row, textvariable=self.phase_var, style="Phase.TLabel").pack(
            side="left")
        self.pct_var = tk.StringVar(value="0%")
        ttk.Label(status_row, textvariable=self.pct_var, style="Pct.TLabel").pack(side="right")

        self.progress = ttk.Progressbar(prog_inner, mode="determinate", maximum=100,
                                        style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(8, 4))
        self.counter_var = tk.StringVar(value="")
        ttk.Label(prog_inner, textvariable=self.counter_var, style="CardMuted.TLabel").pack(anchor="w")

        log_outer, log_card = self._card(body, "DETAILS")
        log_outer.pack(fill="both", expand=True)
        log_inner = ttk.Frame(log_card, style="Card.TFrame")
        log_inner.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        self.log = tk.Text(log_inner, height=8, wrap="word", state="disabled",
                           font=("Consolas", 9), background=COLOR_LOG_BG,
                           foreground=COLOR_LOG_TEXT, borderwidth=0, relief="flat")
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_inner, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

    # ----------------------------------------------------------- actions --
    def _browse(self):
        d = filedialog.askdirectory(title="Select the folder containing your PDFs")
        if d:
            self.src_var.set(d)

    def _log(self, msg: str):
        self._log_q.put(msg)

    def _drain_log(self):
        try:
            while True:
                msg = self._log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _progress(self, phase: str, current: int, total: int, filename: str = ""):
        self._prog_q.put((phase, current, total, filename))

    def _drain_progress(self):
        latest = None
        try:
            while True:
                latest = self._prog_q.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            self._apply_progress(*latest)
        self.after(80, self._drain_progress)

    def _apply_progress(self, phase: str, current: int, total: int, filename: str = ""):
        label = PHASE_META.get(phase, phase)
        self.phase_var.set(label)

        pct = compute_progress_percent(phase, current, total, self._progress_pct)
        self._progress_pct = pct
        self.progress["value"] = pct
        self.pct_var.set(f"{int(pct)}%")

        if phase in ("extract", "enrich", "organise") and total and total > 0:
            what = {"extract": "Reading", "enrich": "Analysing", "organise": "Organising"}[phase]
            suffix = f" - {filename}" if filename else ""
            self.counter_var.set(f"{what} {current:,} of {total:,}{suffix}")
        elif phase == "done":
            self.counter_var.set("Done.")
        else:
            self.counter_var.set(filename or "")

    def _start(self):
        src = self.src_var.get().strip()
        if not src or not Path(src).is_dir():
            messagebox.showwarning(APP_TITLE, "Please choose a valid folder that contains your PDFs.")
            return
        if self._worker and self._worker.is_alive():
            return
        self.start_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0
        self._progress_pct = 0.0
        self.pct_var.set("0%")
        self.phase_var.set("Starting...")
        self.counter_var.set("")
        self._worker = threading.Thread(target=self._run, args=(src,), daemon=True)
        self._worker.start()

    def _run(self, src: str):
        try:
            stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H%M")
            out_dir = desktop_dir() / f"Legal_Migration_Output_{stamp}"
            out_dir.mkdir(parents=True, exist_ok=True)
            self._out_dir = out_dir
            log_file = (out_dir / "run_log.txt").open("w", encoding="utf-8")

            def log_fn(m: str):
                self._log(m)
                try:
                    log_file.write(m + "\n")
                    log_file.flush()
                except Exception:
                    pass

            cfg = Config()
            cfg.paths.source_dir = Path(src)
            cfg.paths.output_dir = out_dir
            cfg.dedup.near_dup_similarity = STRICTEST_SIMILARITY
            cfg.ingestion.enable_ocr = bool(self.ocr_var.get())
            tcmd, _ = runtime_paths.apply_to_config(cfg)
            log_fn(f"OCR engine: {'ready' if tcmd else 'NOT found (scanned files will be flagged)'}")
            log_fn(f"Output folder: {out_dir}\n")

            summary = run_pipeline(cfg, copy_files=True, log=log_fn,
                                   progress=self._progress)
            log_file.close()
            self.after(0, lambda: self._finish(summary))
        except Exception as e:
            self._log("\nERROR: " + str(e))
            self._log(traceback.format_exc())
            self.after(0, lambda: self._error(str(e)))

    def _finish(self, summary: dict):
        self.progress["value"] = 100
        self._progress_pct = 100.0
        self.pct_var.set("100%")
        self.phase_var.set("Finished")
        self.counter_var.set(f"Kept {summary['retained']:,} - Removed {summary['removed']:,} duplicates")
        self.start_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        scan = summary.get("scanned", 0)
        messagebox.showinfo(
            APP_TITLE,
            f"Finished!\n\n"
            f"Total documents : {summary['total']}\n"
            f"Kept (to migrate): {summary['retained']}\n"
            f"Removed duplicates: {summary['removed']}\n"
            f"Flagged for review: {summary['needs_review']}\n"
            f"Scanned (OCR): {scan}\n\n"
            f"Results saved to your Desktop.")
        if self._out_dir:
            open_folder(self._out_dir)

    def _error(self, msg: str):
        self.phase_var.set("Stopped - see Details")
        self.counter_var.set("")
        self.start_btn.configure(state="normal")
        messagebox.showerror(APP_TITLE, f"Something went wrong:\n\n{msg}\n\n"
                                        f"See run_log.txt in the output folder for details.")
        if self._out_dir:
            self.open_btn.configure(state="normal")

    def _open_results(self):
        if self._out_dir and self._out_dir.exists():
            open_folder(self._out_dir)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
