#%% md
# Part I. The problem, measured before anything is built

A team is only worth organising when the job is too big for one person. This Part builds the job.

**Where this sits.** Nothing in Part I calls a model. We build the thing every later number is measured against: a real library of about 100,000 lines of Python with bugs we planted ourselves, an answer key the agents never see, and a scorer that turns a list of reported bugs into recall and precision. If any of these three is wrong, every result after it is wrong too, so each one gets its own tests before we move on.

**By the end of this Part you can**

- run the notebook in one of three modes and read its house style;
- explain why a planted bug needs a failing test before it counts as a bug;
- hide an answer key so that the hiding itself gives nothing away;
- score a list of findings against the key and say exactly what counts as a match.

![part1_map](attachment:part1_map.png)

#%% md
## S0 - Setup, parameters and the house style

**Theory.** A notebook that calls paid models has to answer three questions before its first call. What may it spend? Where does each answer go? Can somebody else reproduce the numbers without paying again? We answer them with **three modes**. In `smoke` mode a scripted stand-in plays every model: it is free, deterministic and wrong in exactly the ways a test needs, so the whole notebook can run in a few minutes with no key. In `collect` mode the notebook makes real calls, and every answer is written to a local database we call the **ledger** before it is used. In `replay` mode every answer comes from the ledger and the network is never touched, so a reader gets the same numbers we got, for free.

**In plain terms.** Every answer a model gives us is saved. Running the notebook again reads the saved answers instead of asking again.

**For teams.** Keep the paid run and the analysis apart. An argument about a result can then be settled by reading what the model actually said, instead of by running the experiment again and getting a slightly different answer.

#%% md
**The parameters cell.** Every knob in the notebook lives in the next cell, in capital letters. Later sections read these names and never hard-code a number of their own, and the manifest at the end (S76) records all of them, so a run can always be traced back to its settings. The model table maps a **role** (lead, worker, judge and so on) to a model id; the code always asks for a role, which is how the same engine can be pointed at different models without edits. Prices are **dollars per million tokens**, one figure for the tokens a call sends and one for the tokens it gets back, because that is how the provider bills. The notebook keeps its accounts in **cents**, so a typical worker call costs a fraction of one. The whole notebook is held to a hard cap of 2,500 cents, which is 25 dollars.

#%% code
# ---- parameters: every knob in the notebook ---------------------------------------------
import os

DW_MODE = os.environ.get("DW_MODE", "")         # smoke, collect or replay; resolved two cells below
SEED = 42                                        # the one seed every random choice starts from
RUNS = 3                                         # runs per arm in the main comparison (S52)
CAP_CENTS = 2500.0                               # the session budget, 25 dollars: the notebook can never spend more

ENDPOINT = "https://api.anthropic.com/v1"        # one endpoint serves every model
MODELS = {                                       # the code asks for a role; this table says which model plays it
    "lead":     "claude-sonnet-5-5",             # writes plans and the final memo
    "lead_alt": "claude-sonnet-5",               # a second lead from the previous generation
    "worker":   "claude-haiku-5-5",              # reads code and reports bugs: almost every token goes here
    "fast":     "claude-haiku-5-5",              # quick jobs such as tagging, with thinking switched off
    "judge":    "claude-haiku-4-5",              # skeptics and graders, a different generation from the worker
    "omni":     "claude-haiku-4-5",              # probed in S11 alongside the others
}
PRICE = {                                        # dollars per million tokens: (sent, received)
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5":   (2.00, 10.00),
    "claude-haiku-5-5":  (0.10, 0.50),
    "claude-haiku-4-5":  (1.00, 5.00),
}
LONG_PROMPT = {"claude-haiku-5-5": (100_000, (0.50, 2.50))}   # above this many tokens sent, a call is billed at the second pair
CONTEXT_TOKENS = {"claude-sonnet-5-5": 1_000_000, "claude-sonnet-5": 1_000_000,   # the published context windows
                  "claude-haiku-5-5": 1_000_000, "claude-haiku-4-5": 200_000}
CALL_DEADLINE_S = {"default": 300, MODELS["lead"]: 600, MODELS["worker"]: 420}   # whole call, not per chunk
TEMPERATURE, TOP_P = 0.6, 0.95                   # sent only to models that accept them; the newest sample at their own default
START_IN_FLIGHT = 2                              # calls in flight per model when a run starts (S10)
MAX_IN_FLIGHT = 10                               # the most the rate gate will ever allow per model
MAX_AGENTS_PER_RUN = 1000                        # a backstop against a plan that loops forever (S29)
MAX_ITEMS_PER_CALL = 4096                        # items one parallel() or pipeline() call accepts
DAILY_CALL_CAP = 8000                            # a guard against a runaway loop, not a budget

N_BUGS_PER_OPERATOR = 6                          # planted bugs per mutation operator (S2)
MAX_LOUDNESS = 0.40                              # a planted bug may break at most this share of its file's examples
SHARD_TOKENS = 40_000                            # provisional; the decision measurement in S13 sets it

print(f"[params] seed {SEED}, {RUNS} runs per arm, cap {CAP_CENTS:,.0f} cents (${CAP_CENTS / 100:.2f})")
print(f"[params] {len(MODELS)} roles on {len(set(MODELS.values()))} models; worker {MODELS['worker'].split('/')[-1]}, "
      f"lead {MODELS['lead'].split('/')[-1]}")
print(f"[params] planting {N_BUGS_PER_OPERATOR} bugs per operator; a bug may break at most {MAX_LOUDNESS:.0%} of its file's examples")

#%% md
The imports, all in one place. Everything except `numpy`, `scipy` and `matplotlib` is the standard library, and the model client in Part II needs nothing beyond it.

#%% code
import ast
import base64
import collections
import concurrent.futures as cf
import contextlib
import copy
import dataclasses
import difflib
import doctest
import fnmatch
import hashlib
import html
import inspect
import io
import itertools
import json
import linecache
import math
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import urllib.error
import urllib.request
import warnings
import zlib
from dataclasses import dataclass, field, asdict
from pathlib import Path

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from IPython.display import display, HTML

print(f"[setup] python {sys.version.split()[0]}, numpy {np.__version__}, matplotlib {matplotlib.__version__}")

#%% md
**Where things live, and which mode we are in.** The notebook finds the project root by walking up to `pyproject.toml`, so it runs the same from any folder. The mode comes from the `DW_MODE` environment variable. If nobody set it, the notebook replays when a ledger exists and falls back to the free smoke mode when it does not. A smoke run writes its records and figures to a scratch folder, so it can never overwrite the committed results.

#%% code
ROOT = Path.cwd()
while not (ROOT / "pyproject.toml").is_file() and ROOT != ROOT.parent:   # walk up to the project root
    ROOT = ROOT.parent

LEDGER_PATH = ROOT / "artifacts" / "cache" / "ledger.sqlite"            # where every model answer is kept
if DW_MODE not in ("smoke", "collect", "replay"):
    DW_MODE = "replay" if LEDGER_PATH.is_file() else "smoke"          # free by default

DATA = ROOT / "data"                                                   # corpora and answer keys, the same in every mode
ART = ROOT / "artifacts" if DW_MODE != "smoke" else ROOT / "_build" / "out" / "smoke_artifacts"
FIG = ART / "figures"                                                  # every figure, as PNG
RUNS_DIR = ART / "runs"                                                # events and threads of every workflow run
for d in (DATA, ART, FIG, RUNS_DIR, ROOT / "artifacts" / "cache"):
    d.mkdir(parents=True, exist_ok=True)
HEADLESS = os.environ.get("DW_HEADLESS") == "1"                        # set by the build script, where nobody can click

print(f"[setup] mode       : {DW_MODE}")
print(f"[setup] records    : {ART.relative_to(ROOT)}")
print(f"[setup] headless   : {HEADLESS}")

#%% md
**Determinism.** One seed, set once, for every source of randomness the notebook touches. Model answers are not covered by it (a sampling model answers differently each time), which is exactly why the ledger exists.

#%% code
# no-show-def: shown below, once show_def exists
def set_seed(seed):
    """Seed Python's and numpy's generators, and fix string hashing for any child process."""
    random.seed(seed)
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)   # inherited by subprocesses such as the doctest runner


set_seed(SEED)
print(f"[setup] seeded with {SEED}")   # show_def comes later in S0; set_seed is shown there with the other helpers

#%% md
### The house style

The rest of S0 builds the small helpers the whole notebook leans on. Each one is defined in its own cell, followed by a line that prints its name, its signature and its size. That line comes from `show_def`, which is itself defined a few cells below; until then the first helpers are simply checked by the test cell at the end of S0.

**`rel(path)`** prints a path relative to the project root, so an output never shows where the notebook happened to run.

#%% code
# no-show-def: shown below, once show_def exists
def rel(path):
    """A path as the reader would type it from the project root."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:              # outside the project: show only the name
        return Path(path).name

print(f"[rel] {rel(ART / 'figures')}")

#%% md
**`scrub(text)`** removes secrets and machine paths from any text before it is printed or stored. The list of secrets starts empty; S5 adds the API key to it, and from then on nothing the notebook prints or saves can contain the key.

#%% code
# no-show-def: shown below, once show_def exists
SECRETS = []   # filled in S5 with the API key, and with nothing else


def scrub(text):
    """The same text with every secret replaced and every absolute path made relative."""
    text = str(text)
    for s in SECRETS:
        if s:
            text = text.replace(s, "[key]")
    text = text.replace(str(ROOT) + "/", "").replace(str(ROOT), ".")
    return re.sub(r"/(home|root|tmp)/[^\s'\"]+", "<path>", text)

print(f"[scrub] {scrub(str(ROOT / 'data' / 'x.py'))!r}")

#%% md
**`table(rows, cols)`** prints a list of dicts as an aligned table. Numbers are right-aligned and text is left-aligned, and a missing value prints as `-`. Nearly every result in the notebook is printed through it, so the numbers in a figure can always be checked against a printed row.

#%% code
# no-show-def: shown below, once show_def exists
def _cell(value, fmt):
    if value is None:
        return "-"
    if fmt and isinstance(value, (int, float, np.integer, np.floating)):
        return format(value, fmt)
    return str(value)


def table(rows, cols, indent=2):
    """Print rows (dicts) under cols, a list of (key, header, format) tuples."""
    cells = [[_cell(r.get(k), f) for k, _, f in cols] for r in rows]
    widths = [max([len(h)] + [len(c[j]) for c in cells]) for j, (_, h, _) in enumerate(cols)]
    numeric = [all(isinstance(r.get(k), (int, float, np.integer, np.floating)) or r.get(k) is None for r in rows)
               for k, _, _ in cols]
    pad = " " * indent
    print(pad + "  ".join(h.rjust(w) if n else h.ljust(w) for (_, h, _), w, n in zip(cols, widths, numeric)))
    print(pad + "  ".join("-" * w for w in widths))
    for c in cells:
        print(pad + "  ".join(v.rjust(w) if n else v.ljust(w) for v, w, n in zip(c, widths, numeric)))

table([{"model": "worker", "calls": 3, "seconds": 41.25}, {"model": "lead", "calls": 1, "seconds": None}],
      [("model", "role", ""), ("calls", "calls", "d"), ("seconds", "seconds", ".1f")])

#%% md
**`bar(frac)`** draws a bar out of `#` characters, for the many places where a quick picture in the printed output is clearer than a number.

#%% code
# no-show-def: shown below, once show_def exists
def bar(frac, width=30, ch="#"):
    """A text bar for a fraction between 0 and 1."""
    frac = 0.0 if frac is None or frac != frac else max(0.0, min(1.0, float(frac)))
    return ch * int(round(frac * width)) + "." * (width - int(round(frac * width)))

print(f"[bar] 0.25 |{bar(0.25)}|")
print(f"[bar] 0.80 |{bar(0.80)}|")

#%% md
**`show_def(obj)`** is the line under every definition. It prints the name, the signature, the number of lines that cost something (blank lines and comment lines are free, docstrings are not) and the **cyclomatic complexity**, which is one plus the number of places where the code can branch. A reader can see at a glance which pieces are small and which ones deserve a closer look, and S71 adds them all up to weigh the whole system.

#%% code
DEFS = {}   # every definition shown so far: name -> its size, complexity and layer


def source_of(obj):
    """The source text of a function or class defined in this notebook."""
    try:
        return inspect.getsource(obj)
    except (OSError, TypeError):
        pass
    if inspect.isclass(obj):   # a class defined in a cell: find it in the cells Python has seen
        pattern = re.compile(rf"^\s*class {re.escape(obj.__name__)}\b")
        for fname in reversed(list(linecache.cache)):
            lines = linecache.cache[fname][2]
            for i, ln in enumerate(lines):
                if pattern.match(ln):
                    j = i
                    while j > 0 and lines[j - 1].lstrip().startswith("@"):   # keep its decorators
                        j -= 1
                    return "".join(lines[j:i]) + "".join(inspect.getblock(lines[i:]))
    return ""


def complexity(src):
    """One plus the number of branch points: if, for, while, except, boolean operators, conditional expressions."""
    try:
        tree = ast.parse(textwrap.dedent(src))
    except SyntaxError:
        return 0
    n = 1
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler, ast.IfExp, ast.comprehension)):
            n += 1
        elif isinstance(node, ast.BoolOp):
            n += len(node.values) - 1
    return n


def show_def(*objs, layer="lab"):
    """One line per definition: its name, signature, size in lines and complexity."""
    for obj in objs:
        src = textwrap.dedent(source_of(obj))
        n = sum(1 for ln in src.splitlines() if ln.strip() and not ln.strip().startswith("#"))
        try:
            sig = str(inspect.signature(obj))
        except (TypeError, ValueError):
            sig = ""
        sig = scrub(sig)
        sig = sig if len(sig) <= 70 else sig[:67] + "...)"
        kind = "class" if inspect.isclass(obj) else "def"
        name = getattr(obj, "__qualname__", getattr(obj, "__name__", str(obj)))
        DEFS[name] = {"layer": layer, "lines": n, "complexity": complexity(src)}
        print(f"[{kind}] {name}{sig}  {n} lines, complexity {DEFS[name]['complexity']}")

show_def(set_seed, rel, scrub, table, bar, source_of, complexity, show_def)

#%% md
**`method_of(cls)`** lets a class be built one method per cell. Each method gets its own explanation and its own test, instead of arriving as one wall of code. It is a decorator: the function under it is attached to the class, and every existing object of the class gains the method at once.

#%% code
def method_of(cls):
    """Attach the decorated function to cls as a method, so a class can grow one cell at a time."""
    def attach(fn):
        fn.__qualname__ = f"{cls.__name__}.{fn.__name__}"   # reads as Ledger.get in show_def and tracebacks
        setattr(cls, fn.__name__, fn)
        return fn
    return attach

show_def(method_of)

#%% md
**`save_exp(name, record)`** writes an experiment's numbers to `artifacts/exp_<name>.json`, and **`load_exp(name)`** reads them back. Floats are rounded to four places before they are written, so float noise never reaches the prose. Every number quoted in the markdown of this notebook is filled in from one of these records when the notebook is built, which is why a sentence can never disagree with the run above it.

#%% code
def _round(obj):
    """Round floats to 4 places, recursively; NaN becomes None so the JSON stays valid."""
    if isinstance(obj, float) or isinstance(obj, np.floating):
        return None if obj != obj else round(float(obj), 4)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, dict):
        return {str(k): _round(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_round(v) for v in obj]
    return obj


def save_exp(name, record):
    """Write artifacts/exp_<name>.json and say where it went."""
    path = ART / f"exp_{name}.json"
    path.write_text(json.dumps(_round(record), indent=2, default=str), encoding="utf-8")
    print(f"[exp] {rel(path)}")


def load_exp(name):
    """Read an experiment record written by save_exp."""
    return json.loads((ART / f"exp_{name}.json").read_text(encoding="utf-8"))

show_def(_round, save_exp, load_exp)

#%% md
**`expect(name, ok)`** is the notebook's test framework, all of it. Each call records one named check and prints `PASSED` or `FAILED`. A section's tests are a list of these lines, and a smoke run of the whole notebook is only green when every one of them passed.

#%% code
results = []   # (name, passed) for every expect() in the notebook


def expect(name, ok):
    """Record and print one check."""
    results.append((name, bool(ok)))
    print(f"  {'PASSED' if ok else 'FAILED'}  {name}")

show_def(expect)

#%% md
**The palette.** Eight colours in a fixed order and five neutrals, used the same way in every figure: blue is the system we are building, grey is a baseline, red marks something wrong or missing, green marks something that passed. Colour is never the only carrier of meaning; every figure also has labels or text.

#%% code
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"   # blue, orange, green, amber
C5, C6, C7, C8 = "#e87ba4", "#008300", "#4a3aa7", "#e34948"   # pink, deep green, violet, red
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8880", "#e6e5e1", "#fcfcfb"
PALETTE = [C1, C2, C3, C4, C5, C6, C7, C8]
matplotlib.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "font.size": 9, "axes.edgecolor": GRID, "axes.labelcolor": INK2, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "legend.frameon": False, "figure.dpi": 110, "savefig.dpi": 110,
})
print(f"[style] {len(PALETTE)} colours, figures at {matplotlib.rcParams['savefig.dpi']} dpi")

#%% md
**`finish(fig, name, title, sub)`** gives every figure the same frame. The title states the finding, not the axes ("one agent alone found 14 of 72", not "recall per arm"). The grey subtitle carries the number or the caveat. The figure is saved to `artifacts/figures/`, shown, closed so a long run does not pile up open figures, and numbered. The numbers are recorded too, and the reading under each figure takes its number from that record when the notebook is built, so a reading can never point at the wrong figure. **`panel(ax, text)`** puts a small grey caption at the top left of one panel.

#%% code
FIG_N = [0]       # figures shown so far
FIG_NUMBERS = {}  # figure name -> its number; the build fills every "Reading FIG" from this record


def finish(fig, name, title, sub=None):
    """Title that states the finding, a grey subtitle, then save, show and close."""
    FIG_N[0] += 1
    FIG_NUMBERS[name] = FIG_N[0]
    (ART / "exp_figures.json").write_text(json.dumps(FIG_NUMBERS, indent=1), encoding="utf-8")
    h = fig.get_size_inches()[1]
    fig.suptitle(title, x=0.02, y=1 - 0.16 / h, ha="left", va="top", fontsize=11, color=INK, weight="bold")
    if sub:
        fig.text(0.02, 1 - 0.42 / h, sub, ha="left", va="top", fontsize=8.5, color=INK2)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)       # a crowded figure keeps its layout rather than printing a warning
        fig.tight_layout(rect=[0, 0, 1, 1 - (0.62 if sub else 0.36) / h])
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight")
    plt.show()
    plt.close(fig)
    print(f"[fig {FIG_N[0]}] {name}.png")


def panel(ax, text):
    """A small grey caption at the top left of one panel."""
    ax.set_title(text, fontsize=9, color=INK2, loc="left")

show_def(finish, panel)

#%% md
**`widgets()`** returns the `ipywidgets` module when someone can actually click, and `None` in a headless build or when the package is missing. Every interactive cell in the notebook prints a static view first, so a reader on GitHub sees the same information as a reader in Jupyter.

#%% code
def widgets():
    """ipywidgets where a person can use them, None otherwise."""
    if HEADLESS:
        return None
    try:
        import ipywidgets
    except ImportError:
        return None
    return ipywidgets

show_def(widgets)

#%% md
**Testing the house style.** Each helper gets a check. These look trivial, and that is the point: a broken `table` or a `scrub` that misses a path would quietly damage every later section.

#%% code
results = []
expect("rel() makes a path relative to the root", rel(ROOT / "data" / "x.py") == "data/x.py")
expect("scrub() hides a secret", (SECRETS.append("ms-secret-123") or scrub("key=ms-secret-123")) == "key=[key]")
SECRETS.clear()
expect("scrub() removes the machine path", str(ROOT) not in scrub(str(ROOT / "a.py")))
expect("bar() is full at 1 and empty at 0", bar(1, 10) == "#" * 10 and bar(0, 10) == "." * 10)
expect("complexity() counts an if and a loop", complexity("def f(x):\n    for i in x:\n        if i: pass") == 3)
expect("_round() keeps 4 places and turns NaN into None", _round({"a": 1 / 3, "b": float("nan")}) == {"a": 0.3333, "b": None})
save_exp("selftest", {"pi": math.pi})
expect("save_exp() and load_exp() round trip", load_exp("selftest") == {"pi": 3.1416})
print(f"[S0] {sum(ok for _, ok in results)} of {len(results)} checks passed")
