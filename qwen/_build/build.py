"""Assemble the course notebook from its sources, and fill prose numbers from experiment records.

Sources live in _build/src/NN_name.py. A source file is a list of cells; a cell starts with a
line that is exactly "#%% md" or "#%% code" and runs until the next such line. Markdown is written
as plain markdown (no comment prefixes). A markdown cell can show a diagram with
![alt](attachment:name.png); the PNG is read from _build/diagrams/ and stored inside the cell, so
the notebook carries its own pictures.

Prose numbers are written as placeholders, {{record.key.subkey|format}}, and filled after the
notebook has run, from artifacts/exp_<record>.json. A number in the prose can therefore never
disagree with the run that produced it.

    python _build/build.py build [--upto 03]      sources -> dynamic_workflows.ipynb (no outputs)
    python _build/build.py fill NOTEBOOK           placeholders -> numbers, in place
"""
import base64
import json
import re
import sys
from pathlib import Path

import nbformat

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "_build" / "src"
DIAGRAMS = ROOT / "_build" / "diagrams"
ART = ROOT / "artifacts"
OUT = ROOT / "dynamic_workflows.ipynb"

MARKER = re.compile(r"^#%% (md|code)\s*$")
ATTACH = re.compile(r"!\[[^\]]*\]\(attachment:([A-Za-z0-9_.-]+\.png)\)")
PLACEHOLDER = re.compile(r"\{\{([A-Za-z0-9_]+)((?:\.[A-Za-z0-9_\-]+)*)(?:\\?\|([^}]*))?\}\}")   # "\|" inside markdown tables


def read_cells(path):
    """Split one source file into (kind, text) pairs."""
    cells, kind, lines = [], None, []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = MARKER.match(line)
        if m:
            if kind is not None:
                cells.append((kind, "\n".join(lines).strip("\n")))
            kind, lines = m.group(1), []
        elif kind is not None:
            lines.append(line)
    if kind is not None:
        cells.append((kind, "\n".join(lines).strip("\n")))
    return [(k, t) for k, t in cells if t.strip()]


def build(upto=None, output=None):
    files = sorted(SRC.glob("[0-9][0-9]_*.py"))
    if upto:
        files = [f for f in files if f.name[:2] <= upto]
    nb = nbformat.v4.new_notebook()
    nb.metadata["kernelspec"] = {"display_name": "Python 3 (ipykernel)", "language": "python", "name": "python3"}
    nb.metadata["language_info"] = {"name": "python"}
    n = 0
    for f in files:
        for kind, text in read_cells(f):
            n += 1
            cid = f"c{n:04d}"
            if kind == "md":
                cell = nbformat.v4.new_markdown_cell(text, id=cid)
                names = ATTACH.findall(text)
                if names:
                    cell.attachments = {}
                    for name in names:
                        png = DIAGRAMS / name
                        if not png.is_file():
                            raise SystemExit(f"[build] missing diagram {name} (cell {cid}, {f.name})")
                        cell.attachments[name] = {"image/png": base64.b64encode(png.read_bytes()).decode()}
            else:
                cell = nbformat.v4.new_code_cell(text, id=cid)
            nb.cells.append(cell)
    target = Path(output) if output is not None else OUT
    target.parent.mkdir(parents=True, exist_ok=True)
    nbformat.write(nb, target)
    print(f"[build] {len(files)} source files -> {n} cells -> {target.name}")
    return target


def lookup(record, keys):
    path = ART / f"exp_{record}.json"
    if not path.is_file():
        raise KeyError(f"no record {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    for k in keys:
        if isinstance(value, list):
            value = value[int(k)]
        else:
            value = value[k]
    return value


def render(value, fmt):
    if fmt:
        return format(value, fmt)
    if isinstance(value, float):
        return f"{value:.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def fill(path):
    nb = nbformat.read(path, as_version=4)
    missing, filled = [], 0
    for cell in nb.cells:
        if cell.cell_type != "markdown" or "{{" not in cell.source:
            continue

        def sub(m):
            nonlocal filled
            record, keys, fmt = m.group(1), [k for k in m.group(2).split(".") if k], m.group(3)
            try:
                out = render(lookup(record, keys), fmt)
            except (KeyError, IndexError, ValueError, TypeError) as e:
                missing.append(f"{m.group(0)} ({e})")
                return m.group(0)
            filled += 1
            return out

        cell.source = PLACEHOLDER.sub(sub, cell.source)
    nbformat.write(nb, path)
    print(f"[fill] {filled} placeholders filled, {len(missing)} missing")
    for m in missing[:40]:
        print("   missing:", m)
    return not missing


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        upto = sys.argv[sys.argv.index("--upto") + 1] if "--upto" in sys.argv else None
        build(upto)
    elif cmd == "fill":
        ok = fill(Path(sys.argv[2]) if len(sys.argv) > 2 else OUT)
        sys.exit(0 if ok else 1)
    else:
        raise SystemExit(__doc__)
