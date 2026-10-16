"""Checks the deliverable must pass before it is committed.

    .venv/bin/python _build/checks.py [NOTEBOOK] [--sources-only]

Rules (each prints PASSED or FAILED with the offending places):
  1. no em or en dashes anywhere, in prose, code or outputs
  2. no spaced hyphen used as a dash in prose (section headings "S12 - Title" are allowed)
  3. none of the banned phrases in prose
  4. the API key's bytes appear in no file of the repository
  5. no unfilled {{placeholders}} in the executed notebook
  6. every code cell has at least one output
  7. every figure reading is unique, and its number matches a figure the code printed
  8. every function or class a cell defines is passed to show_def(...) in that cell
  9. no absolute paths in outputs
 10. the notebook is under 12 MB and every figure PNG is under 300 KB
"""
import ast
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NB = ROOT / "dynamic_workflows.ipynb"
SRC = ROOT / "_build" / "src"

BANNED = [
    "delve", "tapestry", "testament", "leverage", "seamless", "crucial", "pivotal", "intricate",
    "comprehensive", "holistic", "cutting-edge", "state-of-the-art", "game-changer", "game changer",
    "unlock", "harness", "embark", "realm", "landscape", "navigate", "elevate", "foster", "empower",
    "streamline", "paramount", "meticulous", "furthermore", "moreover", "additionally", "notably",
    "in conclusion", "in summary", "it's worth noting", "it is worth noting", "it is important to note",
    "dive into", "deep dive", "journey", "revolutionize", "synergy", "plethora", "myriad", "vibrant",
    "underscore", "certainly", "robust",
]
DASHES = re.compile("[—–]")
SPACED_HYPHEN = re.compile(r"[A-Za-z0-9,)] - [A-Za-z0-9(]")
HEADING_OK = re.compile(r"^#+ .*\b(S\d+[a-z]?|Part [IVX]+|FIG \d+)\b")
ABS_PATH = re.compile(r"(/home/user|/root/|/tmp/claude)")


def prose_lines(text):
    """Markdown lines outside code fences and inline code."""
    inside = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if not inside:
            yield re.sub(r"`[^`]*`", "", line)


def report(name, problems, limit=12):
    print(f"  {'PASSED' if not problems else 'FAILED'}  {name}" + (f"  ({len(problems)})" if problems else ""))
    for p in problems[:limit]:
        print(f"      {p}")
    return not problems


def cells_of(path):
    nb = json.loads(path.read_text(encoding="utf-8"))
    return nb["cells"]


def text_of(cell):
    src = cell["source"]
    return "".join(src) if isinstance(src, list) else src


def outputs_text(cell):
    parts = []
    for o in cell.get("outputs", []):
        if "text" in o:
            parts.append("".join(o["text"]) if isinstance(o["text"], list) else o["text"])
        for k, v in o.get("data", {}).items():
            if k.startswith("text/"):
                parts.append("".join(v) if isinstance(v, list) else v)
    return "\n".join(parts)


def main():
    sources_only = "--sources-only" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else NB
    ok = True
    if sources_only:
        cells = []
        sys.path.insert(0, str(ROOT / "_build"))
        import build
        for f in sorted(SRC.glob("[0-9][0-9]_*.py")):
            for kind, t in build.read_cells(f):
                cells.append({"cell_type": "markdown" if kind == "md" else "code", "source": t, "outputs": []})
    else:
        cells = cells_of(path)
    md = [(i, text_of(c)) for i, c in enumerate(cells) if c["cell_type"] == "markdown"]
    code = [(i, c) for i, c in enumerate(cells) if c["cell_type"] == "code"]
    print(f"[checks] {path.name if not sources_only else 'sources'}: {len(cells)} cells ({len(md)} markdown, {len(code)} code)")

    # 1 dashes anywhere
    probs = []
    for i, c in enumerate(cells):
        blob = text_of(c) + "\n" + outputs_text(c)
        for m in DASHES.finditer(blob):
            probs.append(f"cell {i}: ...{blob[max(0, m.start() - 30):m.end() + 30]!r}")
    ok &= report("no em or en dashes", probs)

    # 2 spaced hyphen used as a dash in prose
    probs = []
    for i, t in md:
        for line in prose_lines(t):
            if HEADING_OK.match(line) or line.lstrip().startswith(("|", "- ", "* ")):
                continue
            for m in SPACED_HYPHEN.finditer(line):
                probs.append(f"cell {i}: {line.strip()[:110]!r}")
                break
    ok &= report("no spaced hyphen used as a dash in prose", probs)

    # 3 banned phrases
    probs = []
    for i, t in md:
        low = " ".join(prose_lines(t)).lower()
        for w in BANNED:
            if re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low):
                probs.append(f"cell {i}: '{w}'")
    ok &= report("no banned phrases", probs)

    # 4 key bytes anywhere in the repository
    key = os.environ.get("MODELSCOPE_API_KEY", "").strip()
    probs = []
    if key:
        kb = key.encode()
        for p in ROOT.rglob("*"):
            if p.is_file() and ".venv" not in p.parts and ".uv-cache" not in p.parts and ".git" not in p.parts:
                try:
                    if kb in p.read_bytes():
                        probs.append(str(p.relative_to(ROOT)))
                except OSError:
                    pass
    ok &= report("the API key appears in no file" + ("" if key else " (no key in env, skipped)"), probs)

    if not sources_only:
        # 5 unfilled placeholders
        probs = [f"cell {i}: {m}" for i, t in md for m in re.findall(r"\{\{[^}]*\}\}", t)]
        ok &= report("no unfilled placeholders", probs)

        # 6 every code cell has output
        probs = [f"cell {i}: {text_of(c).strip().splitlines()[0][:80] if text_of(c).strip() else ''}"
                 for i, c in code if not c.get("outputs")]
        ok &= report("every code cell has output", probs)

        # 7 figure readings unique and matching printed figures
        printed = set()
        for i, c in code:
            printed |= {int(n) for n in re.findall(r"\[fig (\d+)\]", outputs_text(c))}
        readings, probs = {}, []
        for i, t in md:
            for n in re.findall(r"\*\*Reading FIG (\d+)", t):
                n = int(n)
                if n in readings:
                    probs.append(f"FIG {n} read twice (cells {readings[n]} and {i})")
                readings[n] = i
                if n not in printed:
                    probs.append(f"FIG {n} is read in cell {i} but no code printed [fig {n}]")
        body = {}
        for i, t in md:
            m = re.search(r"\*\*Reading FIG \d+[^*]*\*\*(.*)", t, re.S)
            if m:
                key_ = m.group(1).strip()[:200]
                if key_ in body:
                    probs.append(f"cells {body[key_]} and {i} have the same reading text")
                body[key_] = i
        ok &= report("figure readings unique and matched", probs)

        # 9 absolute paths in outputs
        probs = [f"cell {i}" for i, c in code if ABS_PATH.search(outputs_text(c))]
        ok &= report("no absolute paths in outputs", probs)

        # 10 sizes
        probs = []
        size = path.stat().st_size / 1e6
        if size > 12:
            probs.append(f"notebook is {size:.1f} MB")
        for p in (ROOT / "artifacts" / "figures").glob("*.png"):
            if p.stat().st_size > 300_000:
                probs.append(f"{p.name} is {p.stat().st_size // 1000} KB")
        ok &= report(f"sizes (notebook {size:.1f} MB)", probs)

    # 8 every function or class a cell defines is passed to show_def in that cell
    probs = []
    for i, c in code:
        t = text_of(c)
        if "# no-show-def" in t:
            continue
        try:
            tree = ast.parse(t)
        except SyntaxError:
            continue
        shown = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "show_def":
                for a in n.args:
                    shown.add(ast.unparse(a).split(".")[-1])
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not n.name.startswith("_draw"):
                if n.name not in shown:
                    probs.append(f"cell {i}: {n.name} is defined but not shown")
    ok &= report("every definition is passed to show_def", probs)

    print("[checks] " + ("ALL PASSED" if ok else "SOME CHECKS FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
