# PyInstaller runtime hook — enables multiprocessing in the frozen Windows .exe
# WITHOUT modifying app_gui.py (the GUI entry point).
#
# Why this file exists:
#   When a frozen exe spawns a multiprocessing child, the child re-launches the
#   SAME executable. Without freeze_support(), that child would re-run the GUI
#   entry point instead of the worker bootstrap — spawning runaway windows.
#   PyInstaller runs registered runtime hooks BEFORE the main script in EVERY
#   process (parent and child). Calling freeze_support() here makes each child
#   detect that it is a multiprocessing worker, run the worker bootstrap, and
#   exit — long before any GUI/Tk code is imported. The parent process returns
#   from freeze_support() immediately and continues to the GUI as normal.
#
# This is the officially recommended pattern and requires ZERO changes to the
# GUI source. It is registered via legal_migration.spec (runtime_hooks=[...]).
import multiprocessing

multiprocessing.freeze_support()
