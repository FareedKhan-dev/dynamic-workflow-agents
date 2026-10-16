#%% md
## S1 - The library: a hundred thousand lines of classic algorithms

**Theory.** To test whether a team of agents beats one agent, we need a job with three properties. It has to be **too big for one context**, or the comparison is not interesting. It has to have a **known right answer**, or we can only argue about quality instead of measuring it. And it has to be **understandable**, so a student can look at any single piece of it and judge for themselves. Bug hunting in a large codebase has the first property naturally. The other two depend on the code we pick and on how the bugs get there.

We use a public collection of textbook algorithms: binary search, quicksort, Dijkstra, the Caesar cipher, dynamic programming, number theory and many more, one algorithm per file, written by many contributors. Almost every file carries **doctests**, small examples inside the docstrings like `>>> binary_search([1, 3, 5], 3)` followed by the expected answer. Those examples are what make the job measurable: in S2 they let us prove that a bug we planted really changes the behaviour, and in S3 the examples a bug breaks become the hidden answer key.

**In plain terms.** Everyone who has studied programming knows what binary search should return. That makes every planted bug something a reader can check by eye, and every claim an agent makes something we can test by running the code.

**For teams.** Before measuring an agent on your own codebase, ask the same three questions. Is the job really too big for one context? Is there a ground truth? Can a person check a single answer in a minute? If any answer is no, fix that first, because no amount of orchestration rescues an unmeasurable job.

#%% md
**Where the code comes from.** The files are taken from an open collection of algorithms in Python, published under the MIT license by its contributors. The license requires that its notice travels with the code, so the license file is saved next to our copy in `data/algorithms/`. We take the collection's own index, `DIRECTORY.md`, which lists every file, and keep a filtered subset. The rules for that filter are in the next cell, and each one has a reason in its comment.

#%% code
CORPUS_RAW = "https://raw.githubusercontent.com/TheAlgorithms/Python/HEAD/"   # MIT licensed; license kept beside the copy
ALGO = DATA / "algorithms"
ORIGINAL = ALGO / "original"      # the files exactly as published
AUDITED = ALGO / "audited"        # what the agents will read: bugs planted, some examples hidden (S2, S3)
HIDDEN = ALGO / "hidden"          # the answer key; no tool an agent holds can read this folder
for d in (ORIGINAL, AUDITED, HIDDEN):
    d.mkdir(parents=True, exist_ok=True)

SKIP_FOLDERS = {"project_euler",  # puzzle answers, not reusable algorithms
                "web_programming", "file_transfer",  # need the network
                "tests", "docs", "scripts"}          # not algorithms
SIDE_EFFECT_MODULES = {"urllib", "http", "socket", "smtplib", "ftplib", "webbrowser", "tkinter", "turtle",
                       "subprocess", "multiprocessing", "asyncio", "shutil", "tempfile", "ctypes", "signal"}
ALLOWED_THIRD_PARTY = {"numpy"}   # installed in our environment; everything else would need extra packages
MIN_EXAMPLES = 3                  # fewer doctest examples than this gives us nothing to prove a bug with

print(f"[corpus] skipping {len(SKIP_FOLDERS)} folders; {len(SIDE_EFFECT_MODULES)} stdlib modules count as side effects")
print(f"[corpus] a file needs at least {MIN_EXAMPLES} doctest examples and may import only the stdlib and numpy")

#%% md
**`fetch_text(url, path)`** downloads one text file and keeps it on disk. A second call for the same file reads the disk copy, so the network is used once, ever. The snapshot is committed with the notebook, which means a reader never downloads anything: every run after ours starts from exactly the bytes we used.

#%% code
def fetch_text(url, path, timeout=30):
    """The text at url, cached at path; the network is only touched when the file is missing."""
    path = Path(path)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", "replace").replace("\r\n", "\n")   # one newline style on every machine
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text

show_def(fetch_text)

#%% md
**`corpus_index()`** reads the collection's index and returns the path of every Python file it lists. The license file is fetched along with it.

#%% code
def corpus_index():
    """Every .py path listed in the collection's DIRECTORY.md, in the order listed."""
    idx = fetch_text(CORPUS_RAW + "DIRECTORY.md", ALGO / "DIRECTORY.md")
    fetch_text(CORPUS_RAW + "LICENSE.md", ALGO / "LICENSE.md")
    found = re.findall(r"\]\((?:https://github\.com/TheAlgorithms/Python/blob/master/)?([A-Za-z0-9_./-]+\.py)\)", idx)
    return list(dict.fromkeys(found))     # keep the order, drop repeats

show_def(corpus_index)
INDEX = corpus_index()
by_folder = collections.Counter(p.split("/")[0] for p in INDEX)
print(f"[index] {len(INDEX):,} Python files in {len(by_folder)} folders")
print(f"[index] largest folders: " + ", ".join(f"{f} {n}" for f, n in by_folder.most_common(6)))

#%% md
**`imports_of(src)`** lists the top-level modules a file imports, by reading its syntax tree rather than searching its text, so a word like "import" inside a docstring cannot fool it.

#%% code
def imports_of(src):
    """Top-level module names imported by this source (relative imports are ignored)."""
    tree = ast.parse(src)
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split(".")[0])
    return mods

show_def(imports_of)
print(f"[imports] {sorted(imports_of('import numpy as np' + chr(10) + 'from maths.prime_check import is_prime' + chr(10) + 's = \"import os\"'))}")

#%% md
**`main_block_lines(tree)`** finds the lines of a file's `if __name__ == "__main__":` block. Many files end with a small interactive demo there that asks for keyboard input. Doctests never run that block, and neither will our agents, so a call to `input()` inside it is harmless; the same call anywhere else would make the file hang when imported.

**`eligible(path, src)`** applies the filter and says why a file was turned away. The reasons are counted below, because a filter that silently drops a third of the data is a decision the reader deserves to see.

#%% code
LOCAL_FOLDERS = set(by_folder)   # a file may import another file of the collection


def main_block_lines(tree):
    """Line numbers inside module-level `if __name__ == "__main__":` blocks."""
    lines = set()
    for node in tree.body:
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name) and node.test.left.id == "__name__"):
            lines |= set(range(node.lineno, node.end_lineno + 1))
    return lines


def calls_outside_main(tree, names):
    """Names from `names` that are called somewhere outside the __main__ block."""
    skip = main_block_lines(tree)
    return {n.func.id for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in names and n.lineno not in skip}


def eligible(path, src):
    """(True, 'ok') when the file can join the corpus, else (False, reason)."""
    if path.split("/")[0] in SKIP_FOLDERS:
        return False, "skipped folder"
    try:
        mods = imports_of(src)
    except SyntaxError:
        return False, "does not parse"
    if mods & SIDE_EFFECT_MODULES:
        return False, "side effects (network, files, processes)"
    if not mods <= set(sys.stdlib_module_names) | ALLOWED_THIRD_PARTY | LOCAL_FOLDERS:
        return False, "third-party package"
    if calls_outside_main(ast.parse(src), {"input", "open"}):
        return False, "reads input or files"
    if src.count(">>> ") < MIN_EXAMPLES:
        return False, f"fewer than {MIN_EXAMPLES} doctest examples"
    return True, "ok"

show_def(main_block_lines, calls_outside_main, eligible)

#%% md
**`snapshot(paths)`** fetches every listed file (16 at a time, since the work is waiting on the network), applies the filter, and keeps the eligible ones on disk. When the snapshot is already there, as it is for every run after the first, nothing is downloaded.

#%% code
def snapshot(paths, workers=16):
    """{path: source} for every eligible file, plus a Counter of why the others were dropped."""
    def get(p):
        try:
            return p, fetch_text(CORPUS_RAW + p, ORIGINAL / p)
        except (urllib.error.URLError, TimeoutError, OSError):
            return p, None
    on_disk = {f.relative_to(ORIGINAL).as_posix() for f in ORIGINAL.rglob("*.py")}   # "/" on every OS, as in the index
    todo = [p for p in paths if p.split("/")[0] not in SKIP_FOLDERS]
    if on_disk:   # a committed snapshot: read only what is on disk, never the network
        todo = [p for p in todo if p in on_disk]
    with cf.ThreadPoolExecutor(workers) as pool:
        fetched = list(pool.map(get, todo))
    keep, why = {}, collections.Counter()
    why["skipped folder"] = sum(p.split("/")[0] in SKIP_FOLDERS for p in paths)
    for p, src in fetched:
        if src is None:
            why["download failed"] += 1
            continue
        ok, reason = eligible(p, src)
        why[reason] += 1
        if ok:
            keep[p] = src
        elif (ORIGINAL / p).is_file():
            (ORIGINAL / p).unlink()          # keep the snapshot to eligible files only
    return keep, why, len(on_disk)

show_def(snapshot)
SOURCES, WHY, ALREADY = snapshot(INDEX)
print(f"[snapshot] {ALREADY} files were already on disk; {len(SOURCES)} eligible after the filter")
table([{"reason": r, "files": n} for r, n in WHY.most_common()], [("reason", "reason", ""), ("files", "files", "d")])

#%% md
### Running the examples

**Theory.** A doctest is a tiny test written as a conversation with the interpreter: a line starting with `>>> ` is typed in, and the lines under it are what should come back. Running a file's doctests means importing the file and replaying each conversation. We need more than pass or fail for the whole file, though. S2 needs to know **which** examples a planted bug breaks, so our runner reports every example on its own, with the line where it sits.

The runner works in a **fresh interpreter** for every file, with an environment that contains nothing but a `PATH` and a hash seed. In particular it never contains the API key. It reads the source to test from its standard input, so the same runner can test a file as published, a file with a planted bug, or a file with a proposed fix, without writing anything to disk.

A run must also give **the same answer every time**, because everything in Part I is decided by these runs: which files enter the corpus, which bugs count as proven, which examples get hidden. Three things can make a doctest change its mind between runs, and the runner pins all three. Some files call `random` without a seed, so the runner seeds `random` (and NumPy's generator, when the file uses NumPy) before it loads the file. Some examples print sets or dictionaries whose order depends on Python's string hashing, so the hash seed is fixed. That needs care: `python -I`, the obvious way to start a clean interpreter, ignores every `PYTHON...` variable, including `PYTHONHASHSEED`, so the runner uses the separate switches `-s -P -B` (no user site packages, no current folder on the import path, no bytecode files) and passes the environment explicitly. Finally, timing. No decision in Part I depends on how fast anything ran, because speed depends on the machine and on what else it is doing: even CPU time, the obvious candidate, more than doubled for some files when four runs shared a processor. The only time limit is a generous one that separates "finished" from "never finishes". Earlier versions of this notebook missed each of the three in turn, and each time a file left or entered the corpus on some runs and not others, which silently moved every planted bug.

**In plain terms.** For each file we start a clean Python, load the file, replay every `>>>` example and write down which ones came out right.

#%% code
DOCTEST_RUNNER = r'''
import contextlib, doctest, io, json, linecache, random, sys, time, types
root, relpath, seed = sys.argv[1], sys.argv[2], int(sys.argv[3])
src = sys.stdin.read()
random.seed(seed)                                          # files that draw random numbers draw the same ones every run
if "numpy" in src:
    import numpy
    numpy.random.seed(seed)
linecache.cache[root + "/" + relpath] = (len(src), None, src.splitlines(True), root + "/" + relpath)   # line numbers from this source
sys.path.insert(0, root)                                  # so "from maths.x import y" finds its sibling files
name = relpath[:-3].replace("/", ".")
mod = types.ModuleType(name)
mod.__file__ = root + "/" + relpath
sys.modules[name] = mod
start, cpu = time.perf_counter(), time.process_time()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(src, mod.__file__, "exec"), mod.__dict__)
except BaseException as e:
    print(json.dumps({"ok": False, "error": ("import " + type(e).__name__ + ": " + str(e))[:300]}))
    raise SystemExit(0)
seen = []
class Recorder(doctest.DocTestRunner):                    # one record per example, not one per file
    def report_start(self, out, test, example): pass
    def report_success(self, out, test, example, got): seen.append((test, example, True))
    def report_failure(self, out, test, example, got): seen.append((test, example, False))
    def report_unexpected_exception(self, out, test, example, exc): seen.append((test, example, False))
runner = Recorder(optionflags=doctest.ELLIPSIS | doctest.NORMALIZE_WHITESPACE)
for test in doctest.DocTestFinder().find(mod, name, module=mod):
    if test.examples:
        with contextlib.redirect_stdout(io.StringIO()):
            runner.run(test, out=lambda s: None)
rows = [{"owner": t.name.split(".", name.count(".") + 1)[-1], "line": None if t.lineno is None else t.lineno + e.lineno + 1,
         "passed": ok} for t, e, ok in seen]
print(json.dumps({"ok": True, "seconds": round(time.perf_counter() - start, 3), "cpu": round(time.process_time() - cpu, 3),
                  "examples": rows}))
'''
print(f"[runner] {len(DOCTEST_RUNNER.strip().splitlines())} lines; run with python -s -P -B, environment = PATH and a hash seed")

#%% md
**`run_doctests(root, relpath, src)`** sends one source through the runner and returns its report. A run that does not finish in time is reported as `timeout` rather than waited for: a planted bug can easily turn a loop into an infinite one, and S2 must be able to throw such a bug away without hanging the notebook.

#%% code
CLEAN_ENV = {"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": str(SEED)}   # nothing else, and certainly no key
CLEAN_FLAGS = ["-s", "-P", "-B"]   # no user site packages, no current folder on sys.path, no bytecode; unlike -I, keeps the hash seed


def run_doctests(root, relpath, src=None, timeout=60, hash_seed=SEED):
    """Per-example doctest results for one file, in a fresh interpreter with fixed hash and random seeds."""
    if src is None:
        src = (Path(root) / relpath).read_text(encoding="utf-8")
    env = dict(CLEAN_ENV, PYTHONHASHSEED=str(hash_seed))
    try:
        p = subprocess.run([sys.executable, *CLEAN_FLAGS, "-c", DOCTEST_RUNNER, str(Path(root).resolve()), relpath, str(hash_seed)],
                           input=src, capture_output=True, text=True, timeout=timeout, env=env, cwd=str(root))
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout"}
    lines = p.stdout.strip().splitlines()
    if not lines:
        return {"ok": False, "error": ("no output: " + p.stderr[-200:]).strip()}
    return json.loads(lines[-1])

show_def(run_doctests)
demo_path = "searches/binary_search.py" if "searches/binary_search.py" in SOURCES else sorted(SOURCES)[0]
demo = run_doctests(ORIGINAL, demo_path)
print(f"[doctest] {demo_path}: {len(demo['examples'])} examples, "
      f"{sum(e['passed'] for e in demo['examples'])} passed, in {demo['seconds']} s ({demo['cpu']} s of CPU)")
seeded = [run_doctests(ORIGINAL, demo_path)["examples"] == demo["examples"] for _ in range(2)]
print(f"[doctest] the same file run twice more gives the same per-example result: {all(seeded)}")
for e in demo["examples"][:4]:
    print(f"    line {e['line']:>4}  {e['owner']:<24} {'passed' if e['passed'] else 'FAILED'}")

#%% md
**`passing_corpus(sources)`** keeps the files whose examples all pass, and repeats until nothing changes. The repetition matters because some files import a sibling file. If the sibling fails and leaves the corpus, a file that imported it fails on the next round and leaves too. When a round removes nothing, one more round runs everything with a **different seed**. A file that passes with one seed and fails with another depends on chance, and is dropped: its examples would make a planted bug look present or absent at random. When that round also removes nothing, the corpus is complete: every file in it passes under both seeds, using only files that are also in it.

#%% code
def passing_corpus(sources, workers=4):
    """{path: report} for files whose every example passes under two seeds, in a tree made only of such files."""
    alive = dict(sources)
    rounds, seed = 0, SEED
    dropped = {}                                                # path -> why it left, from the round it left in
    while True:
        rounds += 1
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            for p, s in alive.items():                          # a tree holding only the surviving files
                (Path(tmp) / p).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / p).write_text(s, encoding="utf-8")
            with cf.ThreadPoolExecutor(workers) as pool:        # the work happens in child processes
                reports = dict(zip(alive, pool.map(lambda p: run_doctests(tmp, p, alive[p], hash_seed=seed), alive)))
        good = {p: r for p, r in reports.items()
                if r.get("ok") and len(r["examples"]) >= MIN_EXAMPLES
                and all(e["passed"] for e in r["examples"])
                and all(e["line"] is not None for e in r["examples"])}
        for p, r in reports.items():
            if p not in good:
                dropped[p] = ("timeout" if r.get("error") == "timeout" else "import error" if not r.get("ok")
                              else ("depends on the seed" if seed != SEED else "an example fails")
                              if not all(e["passed"] for e in r["examples"])
                              else "examples without a line")
        print(f"  [round {rounds}, seed {seed}] {len(alive)} files in, {len(good)} pass every example")
        if len(good) == len(alive):
            if seed != SEED:
                return {p: reports_first[p] for p in good}, dropped
            seed, reports_first = SEED + 7, reports            # stable: confirm under a second seed
        alive = {p: alive[p] for p in good}

show_def(passing_corpus)

#%% code
t0 = time.perf_counter()
CORPUS, DROPPED = passing_corpus(SOURCES)
fail_kinds = collections.Counter(DROPPED.values())
print(f"[corpus] {len(CORPUS)} of {len(SOURCES)} eligible files pass every example "
      f"({time.perf_counter() - t0:.0f} s for all runs)")
table([{"why": k, "files": n} for k, n in fail_kinds.most_common()], [("why", "dropped because", ""), ("files", "files", "d")])

#%% md
**The manifest.** One record per file: its size, its number of examples, its runtime and a SHA-256 fingerprint of its bytes. The fingerprint is what makes the snapshot verifiable. If anyone edits a file, the fingerprint changes and the next run says so.

#%% code
def file_record(path):
    src = SOURCES[path]
    rep = CORPUS[path]
    return {"path": path, "folder": path.split("/")[0], "lines": len(src.splitlines()), "chars": len(src),
            "examples": len(rep["examples"]), "seconds": rep["seconds"],
            "functions": sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(ast.parse(src))),
            "sha256": hashlib.sha256(src.encode()).hexdigest()}

show_def(file_record)
FILES = [file_record(p) for p in sorted(CORPUS)]
# timings change from run to run, so the file on disk keeps only what is fixed
(ALGO / "manifest.json").write_text(json.dumps([{k: v for k, v in f.items() if k != "seconds"} for f in FILES], indent=1), encoding="utf-8")
LINES = sum(f["lines"] for f in FILES)
print(f"[corpus] {len(FILES)} files, {LINES:,} lines, {sum(f['functions'] for f in FILES):,} functions, "
      f"{sum(f['examples'] for f in FILES):,} doctest examples, {sum(f['chars'] for f in FILES) / 1e6:.2f} M characters")
print(f"[corpus] median file {int(np.median([f['lines'] for f in FILES]))} lines; "
      f"longest {max(FILES, key=lambda f: f['lines'])['path']} ({max(f['lines'] for f in FILES)} lines)")
print(f"[corpus] slowest examples: {max(CORPUS[p]['cpu'] for p in CORPUS):.2f} s of CPU; median {np.median([CORPUS[p]['cpu'] for p in CORPUS]):.3f} s")

#%% md
**Which files depend on which.** A file that other files import is a shared library inside the collection. If we planted a bug in it, the bug would also break the examples of every file that imports it, and the answer key would be wrong about where the bug is. So these files are marked here and S2 never plants a bug in them.

#%% code
def local_imports(path):
    """Corpus files this file imports, as paths."""
    tree = ast.parse(SOURCES[path])
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            cand = node.module.replace(".", "/") + ".py"
            if cand in CORPUS:
                out.add(cand)
        elif isinstance(node, ast.Import):
            for a in node.names:
                cand = a.name.replace(".", "/") + ".py"
                if cand in CORPUS:
                    out.add(cand)
    return out

show_def(local_imports)
IMPORTED = collections.Counter(q for p in CORPUS for q in local_imports(p))
print(f"[deps] {len(IMPORTED)} corpus files are imported by other corpus files; they will never hold a planted bug")
for q, n in IMPORTED.most_common(5):
    print(f"    {q:<46} imported by {n}")

#%% md
### Figures: what the job looks like

The first figure draws every file as one small square, coloured by its folder, the way a reviewer would see a stack of work waiting. The second shows where the lines are and how long a typical file is.

#%% code
# FIG  the whole corpus, one square per file, coloured by folder
cols = 40
top = [f for f, _ in collections.Counter(f["folder"] for f in FILES).most_common(8)]
colour_of = {f: PALETTE[i] for i, f in enumerate(top)}
order = sorted(FILES, key=lambda f: (top.index(f["folder"]) if f["folder"] in top else 99, f["path"]))
rows_n = math.ceil(len(order) / cols)
fig, ax = plt.subplots(figsize=(10.5, 0.24 * rows_n + 1.4))
for i, f in enumerate(order):
    r, c = divmod(i, cols)
    ax.add_patch(plt.Rectangle((c, -r), 0.86, 0.86, color=colour_of.get(f["folder"], GRID), lw=0))
ax.set_xlim(-0.5, cols + 0.5)
ax.set_ylim(-rows_n - 0.5, 1.5)
ax.set_aspect("equal")
ax.axis("off")
handles = [plt.Rectangle((0, 0), 1, 1, color=colour_of[f]) for f in top] + [plt.Rectangle((0, 0), 1, 1, color=GRID)]
counts = collections.Counter(f["folder"] for f in FILES)
labels = [f"{f.replace('_', ' ')} ({counts[f]})" for f in top] + [f"other folders ({sum(n for f, n in counts.items() if f not in top)})"]
ax.legend(handles, labels, loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=5, fontsize=8)
finish(fig, "s1_corpus_map", f"{len(FILES)} files and {LINES:,} lines: the job a single agent will be handed",
       "one square per file, coloured by folder; every file passes all of its own doctest examples")

#%% md
**Reading FIG {{figures.s1_corpus_map}} (s1_corpus_map).** Each square is one file, so the figure is the whole job at a glance. Maths, data structures, sorting and string algorithms are the biggest blocks, but no folder dominates; the work is spread over dozens of topics, which is what a real codebase looks like and what makes it hard to review in one sitting. Every square passed all of its own examples before anything was changed, so any example that fails later failed because of something we did.

#%% code
# FIG  where the lines are, and how long a file is
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6), gridspec_kw={"width_ratios": [1.1, 1]})
lines_by = collections.Counter()
for f in FILES:
    lines_by[f["folder"]] += f["lines"]
names, vals = zip(*lines_by.most_common(14))
ax = axes[0]
ax.barh(range(len(names)), vals, color=C1, height=0.65)
ax.set_yticks(range(len(names)), [n.replace("_", " ") for n in names], fontsize=8)
ax.invert_yaxis()
for i, v in enumerate(vals):
    ax.text(v, i, f" {v:,}", va="center", fontsize=7.5, color=INK2)
ax.set_xlabel("lines of code")
panel(ax, "the 14 largest folders by lines")
ax = axes[1]
lens = [f["lines"] for f in FILES]
ax.hist(lens, bins=40, color=C1, alpha=0.85)
med = float(np.median(lens))
ax.axvline(med, color=C8, ls="--", lw=1.2)
ax.text(med, ax.get_ylim()[1] * 0.92, f" median {med:.0f} lines", color=C8, fontsize=8)
ax.set_xlabel("lines per file")
ax.set_ylabel("files")
panel(ax, "file length")
finish(fig, "s1_corpus_shape", f"Most files are short, but there are {len(FILES)} of them",
       f"{LINES:,} lines in total; a reviewer reading one file per minute would need {len(FILES) / 60:.0f} hours")

#%% md
**Reading FIG {{figures.s1_corpus_shape}} (s1_corpus_shape).** The left panel shows the volume is spread out: even the largest folder is a small part of the whole. The right panel shows why that matters. A typical file is around a hundred lines, short enough to understand in a minute or two, but there are hundreds of them. The difficulty is not any single file, it is the number of files, which is exactly the shape of job a team of parallel workers is supposed to handle better than one worker.

#%% code
save_exp("corpus", {"index_files": len(INDEX), "eligible": len(SOURCES), "files": len(FILES), "lines": LINES,
                    "functions": sum(f["functions"] for f in FILES), "examples": sum(f["examples"] for f in FILES),
                    "chars": sum(f["chars"] for f in FILES), "imported_files": len(IMPORTED),
                    "median_lines": int(np.median([f["lines"] for f in FILES])),
                    "dropped": dict(WHY), "doctest_failures": dict(fail_kinds)})
results = []
expect("every corpus file passed every one of its examples", all(all(e["passed"] for e in CORPUS[p]["examples"]) for p in CORPUS))
expect("the manifest fingerprints match the files on disk",
       all(hashlib.sha256((ORIGINAL / f["path"]).read_text(encoding="utf-8").encode()).hexdigest() == f["sha256"] for f in FILES))
expect("no corpus file imports a side-effect module", not any(imports_of(SOURCES[p]) & SIDE_EFFECT_MODULES for p in CORPUS))
expect("the corpus holds at least 80,000 lines", LINES >= 80_000)
expect("every corpus file has at least 3 examples", min(f["examples"] for f in FILES) >= MIN_EXAMPLES)
