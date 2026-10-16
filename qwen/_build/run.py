"""Build and execute the notebook in one of three modes.

    .venv/bin/python _build/run.py smoke   [--upto NN]   scripted model, no key, no network
    .venv/bin/python _build/run.py collect [--upto NN]   live calls for anything the ledger lacks
    .venv/bin/python _build/run.py replay  [--upto NN]   every answer from the ledger, offline

Smoke runs write to _build/out/smoke.ipynb so they never overwrite the committed notebook.
Collect and replay write dynamic_workflows.ipynb and then fill the prose placeholders.
"""
import os
import sys
import time
from pathlib import Path

import nbformat
from nbclient import NotebookClient
from nbclient.exceptions import CellExecutionError

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402

ROOT = build.ROOT
OUTDIR = ROOT / "_build" / "out"


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("smoke", "collect", "replay"):
        raise SystemExit(__doc__)
    mode = sys.argv[1]
    upto = sys.argv[sys.argv.index("--upto") + 1] if "--upto" in sys.argv else None
    OUTDIR.mkdir(parents=True, exist_ok=True)
    src = build.build(upto, OUTDIR / "smoke_source.ipynb" if mode == "smoke" else None)
    nb = nbformat.read(src, as_version=4)
    os.environ["DW_MODE"] = mode
    os.environ["DW_HEADLESS"] = "1"
    target = OUTDIR / "smoke.ipynb" if mode == "smoke" else src
    start = time.perf_counter()
    last = [start]

    def on_cell_executed(cell, cell_index, execute_reply=None, **_):
        now = time.perf_counter()
        if cell.cell_type == "code":
            first = (cell.source.strip().splitlines() or [""])[0][:70]
            took = now - last[0]
            if took > 2 or cell_index % 50 == 0:
                print(f"[run] cell {cell_index:>4}  {took:7.1f}s  {first}", flush=True)
        last[0] = now

    client = NotebookClient(nb, timeout=None, kernel_name="python3",
                            resources={"metadata": {"path": str(ROOT)}},
                            on_cell_executed=on_cell_executed)
    ok = True
    try:
        client.execute()
    except CellExecutionError as e:
        ok = False
        print("[run] FAILED\n" + str(e)[-4000:], flush=True)
        target = OUTDIR / f"failed_{mode}.ipynb"
    nbformat.write(nb, target)
    print(f"[run] {mode}: {len(nb.cells)} cells in {time.perf_counter() - start:.0f}s -> {target.relative_to(ROOT)}")
    if ok and mode != "smoke":
        build.fill(target)
    elif ok and upto:
        print("[fill] skipped for a partial smoke run; later records do not exist yet")
    elif ok:                                    # smoke: prove every placeholder resolves, on a copy, from the smoke records
        test = OUTDIR / "smoke_filled.ipynb"
        test.write_bytes(target.read_bytes())
        build.ART = OUTDIR / "smoke_artifacts"
        ok = build.fill(test)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
