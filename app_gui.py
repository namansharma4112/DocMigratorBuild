"""app_gui.py — desktop front-end (PyInstaller entry point)."""
from __future__ import annotations
import datetime as _dt
import os
import queue
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from legal_pipeline.config import Config
from legal_pipeline import runtime_paths
from legal_pipeline.pipeline import run as run_pipeline

APP_TITLE = "Legal Document Migration & Deduplication"
APP_SUBTITLE = "Sort, classify, and de-duplicate legal PDFs — ready for vendor upload."

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
COLOR_SUCCESS = "#16A34A"
COLOR_WARN = "#B45309"
COLOR_LOG_BG = "#0F1720"
COLOR_LOG_TEXT = "#D6E2EE"

STRICTEST_SIMILARITY = 0.98

PHASE_META = {
    "scan":     ("🔍", "Scanning folder"),
    "extract":  ("📄", "Reading documents"),
    "enrich":   ("🧠", "Analysing documents"),
    "dedupe":   ("🔗", "Finding duplicates"),
    "organise": ("🗂️", "Organising files"),
    "tracker":  ("📊", "Building the tracker"),
    "done":     ("✅", "Finished"),
}

PROGRESS_BANDS = {
    "scan":     (0, 3),
    "extract":  (3, 45),
    "enrich":   (45, 65),
    "dedupe":   (65, 90),
    "organise": (90, 97),
    "tracker":  (97, 99),
    "done":     (99, 100),
}


def compute_progress_percent(phase: str, current: int, total: int, last_pct: float = 0.0) -> float:
    if phase not in PROGRESS_BANDS:
        return last_pct
    lo, hi = PROGRESS_BANDS[phase]
    if phase == "done":
        return 100.0
    if total and total > 0:
        frac = max(0.0, min(1.0, current / total))
        return lo + (hi - lo) * frac
    return float(hi)


def compute_eta_seconds(elapsed_seconds: float, pct: float) -> Optional[float]:
    if pct is None or pct < 2.0 or pct >= 100.0 or elapsed_seconds <= 0:
        return None
    total_estimated = elapsed_seconds * (100.0 / pct)
    remaining = total_estimated - elapsed_seconds
    return max(0.0, remaining)


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None:
        return "Estimating time remaining…"
    seconds = int(round(seconds))
    if seconds < 5:
        return "Almost done…"
    if seconds < 60:
        return f"~{seconds}s remaining"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"~{minutes}m {secs:02d}s remaining"
    hours, minutes = divmod(minutes, 60)
    return f"~{hours}h {minutes:02d}m remaining"


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
            os.startfile(str(path))  # type: ignore[attr-defined]
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
        self.geometry("820x640")
        self.minsize(720, 560)
        self.configure(background=COLOR_BG)

        self._log_q: "queue.Queue[str]" = queue.Queue()
        self._prog_q: "queue.Queue[tuple]" = queue.Queue()
        self._worker: "threading.Thread | None" = None
        self._out_dir: "Path | None" = None
        self._progress_pct: float = 0.0
        self._run_start_time: float = 0.0

        self._init_style()
        self._build_ui()
        self.after(100, self._drain_log)
        self.after(80, self._drain_progress)

    def _init_style(self):
        style = ttk.Style(self)
        available = style.theme_names()
        for candidate in ("vista", "clam", "default"):
            if candidate in available:
                try:
                    style.theme_use(candidate)
                    break
                except tk.TclError:
                    continue

        style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT, font=("Segoe UI", 10))
        style.configure("Card.TFrame", background=COLOR_CARD)
        style.configure("Header.TFrame", background=COLOR_HEADER_BG)
        style.configure("TLabelframe", background=COLOR_CARD, bordercolor=COLOR_BORDER)
        style.configure("TLabelframe.Label", background=COLOR_CARD, foreground=COLOR_MUTED, font=("Segoe UI", 9, "bold"))
        style.configure("TFrame", background=COLOR_BG)
        style.configure("TLabel", background=COLOR_BG, foreground=COLOR_TEXT)
        style.configure("Card.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("Muted.TLabel", background=COLOR_BG, foreground=COLOR_MUTED)
        style.configure("CardMuted.TLabel", background=COLOR_CARD, foreground=COLOR_MUTED)
        style.configure("HeaderTitle.TLabel", background=COLOR_HEADER_BG, foreground=COLOR_HEADER_TEXT, font=("Segoe UI", 17, "bold"))
        style.configure("HeaderSub.TLabel", background=COLOR_HEADER_BG, foreground=COLOR_HEADER_SUB, font=("Segoe UI", 10))
        style.configure("Phase.TLabel", background=COLOR_CARD, foreground=COLOR_TEXT, font=("Segoe UI", 11, "bold"))
        style.configure("Pct.TLabel", background=COLOR_CARD, foreground=COLOR_ACCENT, font=("Segoe UI", 11, "bold"))

        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), foreground="#FFFFFF",
                        background=COLOR_ACCENT, padding=(16, 8), borderwidth=0)
        style.map("Accent.TButton",
                  background=[("active", COLOR_ACCENT_DARK), ("disabled", "#93A5C4")],
                  foreground=[("disabled", "#E5E9F0")])
        style.configure("Secondary.TButton", font=("Segoe UI", 10), padding=(12, 7))

        style.configure("Accent.Horizontal.TProgressbar", troughcolor="#E7EBF1", background=COLOR_ACCENT,
                         bordercolor="#E7EBF1", lightcolor=COLOR_ACCENT, darkcolor=COLOR_ACCENT, thickness=16)

        style.configure("TCheckbutton", background=COLOR_CARD, foreground=COLOR_TEXT)
        style.configure("TEntry", padding=6)

    def _card(self, parent, title=None):
        outer = ttk.Frame(parent, style="TFrame")
        card = tk.Frame(outer, background=COLOR_CARD, highlightbackground=COLOR_BORDER, highlightthickness=1, bd=0)
        card.pack(fill="both", expand=True)
        if title:
            ttk.Label(card, text=title, style="CardMuted.TLabel", font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=14, pady=(10, 0))
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

        folder_outer, folder_card = self._card(body, "STEP 1 — SELECT FOLDER")
        folder_outer.pack(fill="x", pady=(0, 12))
        frm = ttk.Frame(folder_card, style="Card.TFrame")
        frm.pack(fill="x", padx=14, pady=(6, 14))
        ttk.Label(frm, text="PDF folder:", style="Card.TLabel").pack(side="left")
        self.src_var = tk.StringVar()
        entry = ttk.Entry(frm, textvariable=self.src_var)
        entry.pack(side="left", fill="x", expand=True, padx=8)
        ttk.Button(frm, text="Browse…", style="Secondary.TButton", command=self._browse).pack(side="left")

        opt_outer, opt_card = self._card(body, "STEP 2 — OPTIONS")
        opt_outer.pack(fill="x", pady=(0, 12))
        self.ocr_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(opt_card, text="Read scanned PDFs with OCR (slower, needed for scans)",
                        variable=self.ocr_var, style="TCheckbutton").pack(anchor="w", padx=14, pady=(6, 4))
        ttk.Label(opt_card, text="Duplicate detection: strictest — only near-identical copies "
                                 "are merged; exact duplicates are always removed.",
                  style="CardMuted.TLabel").pack(anchor="w", padx=14, pady=(0, 12))

        act = ttk.Frame(body, style="TFrame")
        act.pack(fill="x", pady=(0, 12))
        self.start_btn = ttk.Button(act, text="▶  Start", style="Accent.TButton", command=self._start)
        self.start_btn.pack(side="left")
        self.open_btn = ttk.Button(act, text="📂  Open results folder", style="Secondary.TButton",
                                   command=self._open_results, state="disabled")
        self.open_btn.pack(side="left", padx=10)

        prog_outer, prog_card = self._card(body, "PROGRESS")
        prog_outer.pack(fill="x", pady=(0, 12))
        prog_inner = ttk.Frame(prog_card, style="Card.TFrame")
        prog_inner.pack(fill="x", padx=14, pady=(6, 14))

        status_row = ttk.Frame(prog_inner, style="Card.TFrame")
        status_row.pack(fill="x")
        self.phase_icon_var = tk.StringVar(value="⏳")
        self.phase_var = tk.StringVar(value="Ready. Choose a folder and click Start.")
        ttk.Label(status_row, textvariable=self.phase_icon_var, style="Phase.TLabel", font=("Segoe UI", 13)).pack(side="left")
        ttk.Label(status_row, textvariable=self.phase_var, style="Phase.TLabel").pack(side="left", padx=(8, 0))
        self.pct_var = tk.StringVar(value="0%")
        ttk.Label(status_row, textvariable=self.pct_var, style="Pct.TLabel").pack(side="right")

        self.progress = ttk.Progressbar(prog_inner, mode="determinate", maximum=100, style="Accent.Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(8, 4))

        bottom_row = ttk.Frame(prog_inner, style="Card.TFrame")
        bottom_row.pack(fill="x")
        self.counter_var = tk.StringVar(value="")
        ttk.Label(bottom_row, textvariable=self.counter_var, style="CardMuted.TLabel").pack(side="left")
        self.eta_var = tk.StringVar(value="")
        ttk.Label(bottom_row, textvariable=self.eta_var, style="CardMuted.TLabel").pack(side="right")

        log_outer, log_card = self._card(body, "DETAILS")
        log_outer.pack(fill="both", expand=True)
        log_inner = ttk.Frame(log_card, style="Card.TFrame")
        log_inner.pack(fill="both", expand=True, padx=14, pady=(6, 14))
        self.log = tk.Text(log_inner, height=10, wrap="word", state="disabled", font=("Consolas", 9),
                           background=COLOR_LOG_BG, foreground=COLOR_LOG_TEXT, borderwidth=0, relief="flat")
        self.log.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_inner, command=self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=sb.set)

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
        icon, label = PHASE_META.get(phase, ("⏳", phase))
        self.phase_icon_var.set(icon)
        self.phase_var.set(label)

        pct = compute_progress_percent(phase, current, total, self._progress_pct)
        self._progress_pct = pct
        self.progress["value"] = pct
        self.pct_var.set(f"{int(pct)}%")

        if phase in ("extract", "enrich", "dedupe", "organise") and total and total > 0:
            what = {"extract": "Reading", "enrich": "Analysing", "dedupe": "Comparing", "organise": "Organising"}[phase]
            suffix = f" — {filename}" if filename else ""
            self.counter_var.set(f"{what} {current:,} of {total:,}{suffix}")
        elif phase == "done":
            self.counter_var.set("Done.")
        else:
            self.counter_var.set(filename or "")

        if phase == "done":
            self.eta_var.set("")
        else:
            elapsed = time.monotonic() - self._run_start_time
            eta_seconds = compute_eta_seconds(elapsed, pct)
            self.eta_var.set(format_eta(eta_seconds))

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
        self.phase_icon_var.set("⏳")
        self.phase_var.set("Starting…")
        self.counter_var.set("")
        self.eta_var.set("")
        self._run_start_time = time.monotonic()
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

            summary = run_pipeline(cfg, copy_files=True, log=log_fn, progress=self._progress)
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
        self.phase_icon_var.set("✅")
        self.phase_var.set("Finished")
        self.counter_var.set(f"Kept {summary['retained']:,} · Removed {summary['removed']:,} duplicates")
        self.eta_var.set("")
        self.start_btn.configure(state="normal")
        self.open_btn.configure(state="normal")
        scan = summary.get("scanned", 0)
        failed = summary.get("failed_extraction", 0)
        failed_line = f"Could not be read: {failed}\n" if failed else ""
        messagebox.showinfo(
            APP_TITLE,
            f"Finished!\n\n"
            f"Total documents : {summary['total']}\n"
            f"Kept (to migrate): {summary['retained']}\n"
            f"Removed duplicates: {summary['removed']}\n"
            f"Flagged for review: {summary['needs_review']}\n"
            f"Scanned (OCR): {scan}\n"
            f"{failed_line}\n"
            f"Results saved to your Desktop.")
        if self._out_dir:
            open_folder(self._out_dir)

    def _error(self, msg: str):
        self.phase_icon_var.set("⚠️")
        self.phase_var.set("Stopped — see Details")
        self.counter_var.set("")
        self.eta_var.set("")
        self.start_btn.configure(state="normal")
        messagebox.showerror(APP_TITLE, f"Something went wrong:\n\n{msg}\n\nSee run_log.txt in the output folder for details.")
        if self._out_dir:
            self.open_btn.configure(state="normal")

    def _open_results(self):
        if self._out_dir and self._out_dir.exists():
            open_folder(self._out_dir)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
