#%% md
## S3 - Hiding the answer key without leaving a fingerprint

**Theory.** A planted bug comes with its proof: the examples it breaks. If those examples stayed in the file, finding the bug would be trivial. An agent would only have to run the doctests and read off the failures, and we would be measuring whether it can run tests, not whether it can review code. So the failing examples are **hidden**: moved out of the file into a folder no agent can read. They become the hidden test that confirms a bug, and the rest of the file's examples stay where they were.

Hiding has a trap of its own. If only buggy files lost examples, the hiding would leave a **fingerprint**: a docstring that announces "Examples:" and then shows two, while every other file shows six. A sharp agent, or a lucky statistic, could find the bugs by looking for files with missing examples instead of reading code. The fix is to hide examples **everywhere**. Every clean file also loses a random share of its examples, with the share drawn from the same distribution as the buggy files. After that, the number of visible examples says nothing about where the bugs are, and we check this with a statistical test instead of assuming it.

There is one practical constraint. Examples inside one docstring share state: an early example can create a variable that a later one uses. Removing that early example would break the later one. So we only hide **self-contained** examples, a single expression with an expected output, and after hiding we run the file again and accept the result only when every example left in view still passes.

**In plain terms.** We take the tests that would give the bug away out of the file, and we take the same kind of tests out of the clean files too, so nobody can tell which files had something taken away.

**For teams.** Any evaluation where the system under test can see more than a real user would see is measuring the wrong thing. Before trusting a benchmark, ask what an agent could infer from the shape of the data alone, and test that it cannot.

#%% md
**`examples_with_lines(src)`** finds every doctest example in a file together with the exact lines it occupies, and marks whether it can be hidden on its own. It reads each docstring twice: as the string Python sees, to find the examples the way the doctest module does, and as the raw text in the file, to know which physical lines they sit on. A docstring whose escapes would make the two disagree on line breaks is left alone entirely.

#%% code
HEADER = re.compile(r"^\s*(>>>\s*)?(examples?|doctests?|tests?|usage)\s*:?\s*$", re.I)


def docstring_constants(tree):
    """(owner, string node) for the docstring of the module and of every class and function."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                yield getattr(node, "name", "<module>"), first.value


def examples_with_lines(src):
    """Every example: its owner, first and last line, source, expected output, and whether it can be hidden alone."""
    out = []
    parser = doctest.DocTestParser()
    for owner, const in docstring_constants(ast.parse(src)):
        raw = ast.get_source_segment(src, const)
        quote = re.match(r'^[rRbBuU]*("""|\'\'\'|"|\')', raw)
        body = raw[quote.end():len(raw) - len(quote.group(1))]
        if body.count("\n") != const.value.count("\n"):
            continue                                    # escapes change the line layout: leave this docstring alone
        for ex in parser.get_examples(const.value):
            first = const.lineno + ex.lineno
            last = first + len(ex.source.splitlines()) + len(ex.want.splitlines()) - 1
            try:
                ast.parse(ex.source, mode="eval")      # a single expression...
                single = True
            except SyntaxError:
                single = False
            out.append({"owner": owner, "first": first, "last": last, "source": ex.source, "want": ex.want,
                        "hideable": single and bool(ex.want.strip()), "doc_end": const.end_lineno})
    return out

show_def(docstring_constants, examples_with_lines)
DEMO_EX = examples_with_lines(SOURCES[DEMO_FILE])
print(f"[examples] {DEMO_FILE}: {len(DEMO_EX)} examples, {sum(e['hideable'] for e in DEMO_EX)} can be hidden on their own")
for e in DEMO_EX[:3] + [x for x in DEMO_EX if not x["hideable"]][:2]:
    print(f"    lines {e['first']:>3}-{e['last']:<3} {e['owner']:<26} {'hideable' if e['hideable'] else 'keeps state'}: {e['source'].strip()[:48]}")

#%% md
**`hide(src, chosen)`** removes the chosen examples from a file and returns the new text with a **line map**, a table from every surviving old line number to its new one. The line map is what lets the answer key point at the right line after the lines above a bug have moved up. If removing examples leaves a header such as "Examples:" with nothing under it, the header goes too, because an empty header is exactly the kind of fingerprint we are trying to avoid.

#%% code
def orphan_headers(src, drop):
    """Header lines ('Examples:' and the like) whose every following docstring line is being dropped."""
    lines = src.split("\n")
    extra = set()
    for _, const in docstring_constants(ast.parse(src)):
        for ln in range(const.lineno, const.end_lineno + 1):
            if HEADER.match(lines[ln - 1].strip().strip('"\'')):
                rest = [k for k in range(ln + 1, const.end_lineno + 1)
                        if lines[k - 1].strip().strip('"\'') and k not in drop]
                if not rest:
                    extra.add(ln)
    return extra


def hide(src, chosen):
    """The source without the chosen examples (and their orphaned headers), and the old-to-new line map."""
    drop = set()
    for e in chosen:
        drop |= set(range(e["first"], e["last"] + 1))
    drop |= orphan_headers(src, drop)
    kept, line_map = [], {}
    for i, line in enumerate(src.split("\n"), 1):
        if i not in drop:
            kept.append(line)
            line_map[i] = len(kept)
    return "\n".join(kept), line_map

show_def(orphan_headers, hide)
pick = [e for e in DEMO_EX if e["hideable"]][:2]
demo_hidden, demo_map = hide(SOURCES[DEMO_FILE], pick)
print(f"[hide] removed {len(SOURCES[DEMO_FILE].splitlines()) - len(demo_hidden.splitlines())} lines; "
      f"old line {max(demo_map)} is now line {demo_map[max(demo_map)]}")
rep = run_doctests(ORIGINAL, DEMO_FILE, demo_hidden)
print(f"[hide] after hiding: {len(rep['examples'])} examples left in view, all pass: {all(e['passed'] for e in rep['examples'])}")

#%% md
### Planting for real

**`plant_one(edit, proof)`** turns a proven candidate into a planted bug, or refuses. It applies the edit and hides exactly the examples the proof says fail. Then it runs the file again and accepts only if every example still in view passes. That last run catches the shared-state problem: if hiding a failing example broke a neighbour that depended on it, the candidate is rejected and the next one is tried.

#%% code
def plant_one(e, proof):
    """A bug record for a proven candidate, or (None, reason) when its evidence cannot be hidden cleanly."""
    mutated = apply_edit(SOURCES[e.path], e)
    exs = examples_with_lines(mutated)
    failing = set(proof["failed"])
    chosen = [x for x in exs if x["first"] in failing]
    if len(chosen) != len(failing):
        return None, "failing example not found"
    if not all(x["hideable"] for x in chosen):
        return None, "failing example keeps state"
    audited, line_map = hide(mutated, chosen)
    rep = run_doctests(ORIGINAL, e.path, audited, timeout=30)
    if not rep.get("ok") or not all(x["passed"] for x in rep["examples"]):
        return None, "hiding broke another example"
    line = SOURCES[e.path].split("\n")[e.line - 1]
    return {"path": e.path, "folder": e.path.split("/")[0], "operator": e.operator, "function": e.function,
            "line_original": e.line, "line": line_map[e.line], "old": e.old, "new": e.new,
            "before": line.strip(), "after": (line[:e.col0] + e.new + line[e.col1:]).strip(),
            "failing": len(failing), "examples": proof["examples"], "loudness": proof["loudness"],
            "visible": len(rep["examples"]), "hidden": [{k: x[k] for k in ("owner", "first", "source", "want")} for x in chosen],
            "audited_src": audited, "mutated_src": mutated}, "planted"

show_def(plant_one)

#%% md
**Choosing the final bugs.** We walk through each operator's candidates and plant until the operator has its quota of six, with **one bug per file** across all operators. At every step the next candidate comes from the length quarter that holds the fewest bugs so far, so the planted files end up as long or as short as the corpus itself. Two bugs in one file would make the scorer's job ambiguous and would tell an agent that found one bug where to look for the next.

#%% code
BUGS, PLANT_LOG, used_files = [], collections.Counter(), set()
per_quarter = collections.Counter()                     # bugs planted so far in each length quarter
for op in OPERATORS:
    got = 0
    queue = list(CANDIDATES[op.__name__])
    while got < N_BUGS_PER_OPERATOR and queue:
        queue.sort(key=lambda c: per_quarter[QUARTER[c[0].path]])   # the emptiest quarter first; stable otherwise
        e, proof = queue.pop(0)
        if e.path in used_files:
            PLANT_LOG[(op.__name__, "file already holds a bug")] += 1
            continue
        bug, why = plant_one(e, proof)
        PLANT_LOG[(op.__name__, why)] += 1
        if bug:
            BUGS.append(bug)
            used_files.add(e.path)
            per_quarter[QUARTER[e.path]] += 1
            got += 1
    print(f"  {op.__name__[3:]:<20} planted {got} of {N_BUGS_PER_OPERATOR}   "
          + ", ".join(f"{w} {n}" for (o, w), n in PLANT_LOG.items() if o == op.__name__ and w != "planted"))
print(f"[plant] bugs per length quarter, shortest first: {[per_quarter[q] for q in range(4)]}")
for i, b in enumerate(BUGS, 1):
    b["id"] = f"B{i:02d}"
print(f"[plant] {len(BUGS)} bugs in {len(used_files)} files, {len({b['folder'] for b in BUGS})} folders")

#%% md
Here are the first few planted bugs, exactly as the answer key stores them: the file, the function, the line in the audited copy, the line before and after the change, and how many of the file's examples the change broke. Every row is something a reader can check by opening the file.

#%% code
for b in BUGS[:8]:
    print(f"  {b['id']}  {b['path']}:{b['line']}  in {b['function']}   ({b['operator']}, breaks {b['failing']} of {b['examples']} examples)")
    print(f"        before: {b['before'][:96]}")
    print(f"        after : {b['after'][:96]}")

#%% md
**Hiding in the clean files.** Each clean file loses a share of its examples drawn from the shares the buggy files lost. The examples are chosen at random among the self-contained ones, and the file is run again to confirm the examples left in view still pass. If they do not, we draw again, up to five times.

#%% code
def hide_clean(path, src, rng, shares):
    """Hide a random share of a clean file's self-contained examples; the share comes from the buggy files."""
    exs = examples_with_lines(src)
    pool = [x for x in exs if x["hideable"]]
    for _ in range(5):
        share = rng.choice(shares)
        k = min(len(pool), max(1, round(share * len(exs))))
        chosen = rng.sample(pool, k) if pool else []
        audited, _ = hide(src, chosen)
        rep = run_doctests(ORIGINAL, path, audited, timeout=60)
        if rep.get("ok") and all(x["passed"] for x in rep["examples"]):
            return audited, chosen
    return src, []                                   # nothing could be hidden safely: leave the file as it was

show_def(hide_clean)
rng = random.Random(SEED + 1)
SHARES = [b["failing"] / b["examples"] for b in BUGS]
clean_paths = [p for p in sorted(CORPUS) if p not in used_files]
with cf.ThreadPoolExecutor(4) as pool:
    jobs = {p: random.Random(f"{SEED}:{p}") for p in clean_paths}           # one generator per file: order-independent
    CLEAN_HIDDEN = dict(zip(clean_paths, pool.map(lambda p: hide_clean(p, SOURCES[p], jobs[p], SHARES), clean_paths)))
n_hidden_clean = sum(len(c) for _, c in CLEAN_HIDDEN.values())
untouched = sum(1 for _, c in CLEAN_HIDDEN.values() if not c)
print(f"[hide] {len(clean_paths)} clean files: {n_hidden_clean} examples hidden, {untouched} files could not be touched safely")

#%% md
**Writing the two trees.** The audited tree is what agents will read: every file of the corpus, with its bug if it has one and with its share of examples hidden. The hidden folder holds the answer key (one record per bug) and, for each buggy file, the full mutated file with all of its examples, so the proof can be re-run at any time. The path guard defined at the end of this section makes sure no agent tool can open that folder.

#%% code
if AUDITED.exists():
    shutil.rmtree(AUDITED)
if (HIDDEN / "full").exists():
    shutil.rmtree(HIDDEN / "full")
for p in sorted(CORPUS):
    (AUDITED / p).parent.mkdir(parents=True, exist_ok=True)
for b in BUGS:
    (AUDITED / b["path"]).write_text(b["audited_src"], encoding="utf-8")
    (HIDDEN / "full" / b["path"]).parent.mkdir(parents=True, exist_ok=True)
    (HIDDEN / "full" / b["path"]).write_text(b["mutated_src"], encoding="utf-8")
for p, (src, _) in CLEAN_HIDDEN.items():
    (AUDITED / p).write_text(src, encoding="utf-8")
ANSWER_KEY = [{k: v for k, v in b.items() if k not in ("audited_src", "mutated_src")} for b in BUGS]
(HIDDEN / "answer_key.json").write_text(json.dumps(ANSWER_KEY, indent=1), encoding="utf-8")
(HIDDEN / "clean_hidden.json").write_text(json.dumps(
    {p: [{k: x[k] for k in ("owner", "first", "source", "want")} for x in c] for p, (_, c) in CLEAN_HIDDEN.items()},
    indent=1), encoding="utf-8")
AUDITED_LINES = sum(len((AUDITED / p).read_text(encoding="utf-8").splitlines()) for p in CORPUS)
print(f"[trees] audited: {len(CORPUS)} files, {AUDITED_LINES:,} lines; hidden: {len(ANSWER_KEY)} bug records and {len(BUGS)} full files")

#%% md
**Checking the trees, all of them, from scratch.** Two runs over everything. First, every file of the audited tree, run as it now stands on disk: every example in view must pass, including in the 72 files that hold a bug. Second, every hidden full file, which still carries all of its examples: each must fail exactly as many examples as its proof said.

#%% code
with cf.ThreadPoolExecutor(4) as pool:
    audited_reports = dict(zip(sorted(CORPUS), pool.map(lambda p: run_doctests(AUDITED, p), sorted(CORPUS))))
    hidden_reports = dict(zip([b["path"] for b in BUGS],
                              pool.map(lambda b: run_doctests(AUDITED, b["path"], b["mutated_src"]), BUGS)))
visible_fail = [p for p, r in audited_reports.items() if not r.get("ok") or not all(x["passed"] for x in r["examples"])]
proof_mismatch = [b["id"] for b in BUGS
                  if sum(not x["passed"] for x in hidden_reports[b["path"]]["examples"]) != b["failing"]]
VISIBLE_EXAMPLES = sum(len(r["examples"]) for r in audited_reports.values())
print(f"[verify] audited tree: {len(audited_reports) - len(visible_fail)} of {len(audited_reports)} files pass every visible example "
      f"({VISIBLE_EXAMPLES:,} examples in view)")
print(f"[verify] hidden proofs: {len(BUGS) - len(proof_mismatch)} of {len(BUGS)} bugs fail exactly as recorded")

#%% md
### The leak test: can the hiding be detected?

**Theory.** If the hiding left a fingerprint, some simple property of a file would separate the buggy files from the clean ones. We measure five such properties on the audited tree, the one an agent sees. For each property we compute the **AUROC** (defined in S2): the probability that a randomly chosen buggy file scores higher than a randomly chosen clean one. An AUROC of 0.5 means the property carries no information about where the bugs are; 1.0 or 0.0 means it gives them away completely. We fold it as `max(AUROC, 1 - AUROC)`, so 0.5 is the only good value whichever way a property leans. The rule we committed to before looking: every property must stay below 0.6. A Kolmogorov-Smirnov test on visible examples per function adds a second check: its p-value should not be small.

**In plain terms.** We ask whether you could find the buggy files without reading their code, just by counting things. If you could, the experiment would be broken.

#%% code
def visible_features(path):
    """Properties an agent can see without reading the logic: counts of examples, functions and lines."""
    src = (AUDITED / path).read_text(encoding="utf-8")
    exs = examples_with_lines(src)
    funcs = max(1, sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(ast.parse(src))))
    docs = list(docstring_constants(ast.parse(src)))
    doc_lines = sum(c.end_lineno - c.lineno + 1 for _, c in docs)
    return {"examples": len(exs), "examples per function": len(exs) / funcs, "lines": len(src.splitlines()),
            "docstring share": doc_lines / max(1, len(src.splitlines())),
            "blank-line runs in docstrings": len(re.findall(r"\n[ \t]*\n[ \t]*\n", "\n".join(
                "\n".join(src.split("\n")[c.lineno - 1:c.end_lineno]) for _, c in docs)))}


show_def(visible_features)
FEAT = {p: visible_features(p) for p in sorted(CORPUS)}
LEAK = []
for k in FEAT[next(iter(FEAT))]:
    pos = [FEAT[b["path"]][k] for b in BUGS]
    neg = [FEAT[p][k] for p in clean_paths]
    LEAK.append({"property": k, "buggy mean": float(np.mean(pos)), "clean mean": float(np.mean(neg)), "auroc": auroc(pos, neg)})
table(LEAK, [("property", "property an agent can see", ""), ("buggy mean", "buggy files", ".2f"),
             ("clean mean", "clean files", ".2f"), ("auroc", "AUROC (0.5 = no signal)", ".3f")])
KS = ks_2samp([FEAT[b["path"]]["examples per function"] for b in BUGS], [FEAT[p]["examples per function"] for p in clean_paths])
print(f"[leak] Kolmogorov-Smirnov on examples per function: statistic {KS.statistic:.3f}, p = {KS.pvalue:.3f}")
print(f"[leak] largest AUROC {max(r['auroc'] for r in LEAK):.3f} (rule: below 0.6)  ->  "
      f"{'NO FINGERPRINT FOUND' if max(r['auroc'] for r in LEAK) < 0.6 and KS.pvalue > 0.05 else 'FINGERPRINT'}")

#%% md
### Figures: where the bugs are, how quiet they are, and whether the hiding shows

#%% code
# FIG  the bug map: the corpus grid again, with the planted bugs lit
buggy = {b["path"]: b for b in BUGS}
fig, ax = plt.subplots(figsize=(10.5, 0.24 * rows_n + 1.2))
for i, f in enumerate(order):
    r, c = divmod(i, cols)
    hit = f["path"] in buggy
    ax.add_patch(plt.Rectangle((c, -r), 0.86, 0.86, color=C8 if hit else GRID, lw=0))
ax.set_xlim(-0.5, cols + 0.5)
ax.set_ylim(-rows_n - 0.5, 1.5)
ax.set_aspect("equal")
ax.axis("off")
finish(fig, "s3_bug_map", f"{len(BUGS)} bugs hidden in {len(CORPUS)} files",
       f"red: a file holding one planted bug ({len(BUGS) / len(CORPUS):.1%} of files); the agents never see this picture")

#%% md
**Reading FIG {{figures.s3_bug_map}} (s3_bug_map).** The same grid as FIG {{figures.s1_corpus_map}}, in the same order, with the {{answer_key.bugs}} buggy files in red. They are spread over {{answer_key.folders}} folders, a result of the folder-by-folder spreading in S2, and they make up {{answer_key.share_of_files|.1%}} of the files. Most of the work in an audit is therefore reading files that turn out to be fine. That ratio is realistic, and it is what makes the job hard: a reviewer cannot stop reading after the first few finds, because there is no telling how many remain.

#%% code
# FIG  how quiet the bugs are, and that clean files lost a matching share of examples
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5))
ax = axes[0]
loud = [b["loudness"] for b in BUGS]
ax.hist(loud, bins=np.linspace(0, MAX_LOUDNESS, 17), color=C8, alpha=0.85)
ax.axvline(np.median(loud), color=INK, ls="--", lw=1)
ax.text(np.median(loud), ax.get_ylim()[1] * 0.9, f" median {np.median(loud):.0%}", fontsize=8)
ax.set_xlabel("share of the file's examples the bug breaks (loudness)")
ax.set_ylabel("bugs")
panel(ax, f"every bug breaks at least one example and at most {MAX_LOUDNESS:.0%}")
ax = axes[1]
share_b = sorted(len(b["hidden"]) / b["examples"] for b in BUGS)
share_c = sorted(len(c) / max(1, len(examples_with_lines(SOURCES[p]))) for p, (_, c) in CLEAN_HIDDEN.items())
ax.plot(share_b, np.linspace(0, 1, len(share_b)), color=C8, lw=2, label="buggy files")
ax.plot(share_c, np.linspace(0, 1, len(share_c)), color=C1, lw=2, label="clean files")
ax.set_xlabel("share of examples hidden")
ax.set_ylabel("share of files (cumulative)")
ax.legend(fontsize=8)
panel(ax, "hidden shares, buggy vs clean")
finish(fig, "s3_quiet_bugs", f"The bugs are quiet: the median one breaks {np.median(loud):.0%} of its file's examples",
       "right: clean files lost examples in the same proportions as buggy files, so a missing example is no clue")

#%% md
**Reading FIG {{figures.s3_quiet_bugs}} (s3_quiet_bugs).** The left panel is the loudness of every bug. The median bug breaks {{answer_key.median_loudness|.0%}} of its file's examples, which means the file's other examples, the ones left in view, keep passing. In real code a bug that breaks most tests is caught on the first run; the bugs worth an audit are the ones the existing tests walk past, and these are built to be that kind. The right panel compares how much was hidden in buggy and clean files. The two curves track each other because the clean shares were drawn from the buggy ones, which is the whole idea of hiding without a fingerprint.

#%% code
# FIG  the leak test: no visible property separates buggy files from clean ones
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.4), gridspec_kw={"width_ratios": [1, 1.1]})
ax = axes[0]
epf_b = sorted(FEAT[b["path"]]["examples per function"] for b in BUGS)
epf_c = sorted(FEAT[p]["examples per function"] for p in clean_paths)
ax.plot(epf_b, np.linspace(0, 1, len(epf_b)), color=C8, lw=2, label="buggy files")
ax.plot(epf_c, np.linspace(0, 1, len(epf_c)), color=C1, lw=2, label="clean files")
ax.set_xscale("log")
ax.set_xlabel("visible examples per function")
ax.set_ylabel("share of files (cumulative)")
ax.legend(fontsize=8)
panel(ax, f"Kolmogorov-Smirnov p = {KS.pvalue:.2f}")
ax = axes[1]
names = [r["property"] for r in LEAK]
vals = [r["auroc"] for r in LEAK]
ax.barh(range(len(names)), vals, color=[C3 if v < 0.6 else C8 for v in vals], height=0.6)
ax.axvline(0.5, color=MUTED, ls="--", lw=1)
ax.axvline(0.6, color=C8, ls="--", lw=1)
ax.text(0.6, len(names) - 0.4, " limit 0.6", color=C8, fontsize=8)
ax.set_xlim(0.45, 1.0)
ax.set_yticks(range(len(names)), names, fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("AUROC, buggy vs clean (0.5 means no signal)")
panel(ax, "every property stays under the limit" if max(vals) < 0.6 else "a property crosses the limit")
finish(fig, "s3_leak_test", "Nothing an agent can count gives the bugs away",
       f"largest AUROC {max(vals):.2f}; a fingerprint would push a bar past the red line")

#%% md
**Reading FIG {{figures.s3_leak_test}} (s3_leak_test).** The left panel shows the property most likely to leak, visible examples per function, for buggy and clean files; the two curves overlap, and the Kolmogorov-Smirnov p-value of {{answer_key.ks_p|.2f}} says the difference is what chance alone produces. The right panel shows all five properties at once. The largest AUROC is {{answer_key.max_auroc|.2f}}, below the limit we set before looking, so counting examples, lines or blank lines tells an agent nothing about where the bugs are. An agent has to read the code.

#%% md
**The path guard.** Every tool an agent will hold (Part III) opens files through **`readable(path)`**, which resolves the path and refuses anything outside the audited tree. A path that climbs with `..`, points at the hidden folder or the original snapshot, or is absolute is refused before a single byte is read. The tests below try the usual tricks.

#%% code
class PathDenied(PermissionError):
    """A tool tried to read outside the audited tree."""


def readable(path):
    """The resolved Path inside the audited tree, or PathDenied."""
    p = (AUDITED / str(path)).resolve()
    if not str(p).startswith(str(AUDITED.resolve()) + os.sep) and p != AUDITED.resolve():
        raise PathDenied(f"outside the audited tree: {path}")
    return p

show_def(PathDenied, readable)
for attempt in ["searches/binary_search.py", "../hidden/answer_key.json", "../original/searches/binary_search.py",
                "/etc/passwd", "searches/../../hidden/full"]:
    try:
        readable(attempt)
        print(f"  allowed  {attempt}")
    except PathDenied:
        print(f"  DENIED   {attempt}")

#%% code
save_exp("answer_key", {"bugs": len(BUGS), "files": len(CORPUS), "share_of_files": len(BUGS) / len(CORPUS),
                        "operators": dict(collections.Counter(b["operator"] for b in BUGS)),
                        "folders": len({b["folder"] for b in BUGS}), "median_loudness": float(np.median(loud)),
                        "audited_lines": AUDITED_LINES, "visible_examples": VISIBLE_EXAMPLES,
                        "hidden_clean": n_hidden_clean, "untouched_clean": untouched,
                        "max_auroc": max(r["auroc"] for r in LEAK), "ks_p": float(KS.pvalue),
                        "leak": LEAK, "plant_log": {f"{o[3:]}|{w}": n for (o, w), n in PLANT_LOG.items()}})
results = []
expect(f"all {len(OPERATORS) * N_BUGS_PER_OPERATOR} bugs were planted", len(BUGS) == len(OPERATORS) * N_BUGS_PER_OPERATOR)
expect("one bug per file", len({b["path"] for b in BUGS}) == len(BUGS))
expect("every visible example of the audited tree passes", not visible_fail)
expect("every hidden proof fails exactly as recorded", not proof_mismatch)
expect("every bug line in the audited copy shows the mutated text",
       all(b["after"] == (AUDITED / b["path"]).read_text(encoding="utf-8").split("\n")[b["line"] - 1].strip() for b in BUGS))
expect("no visible property separates buggy files (AUROC < 0.6)", max(r["auroc"] for r in LEAK) < 0.6)
expect("examples per function: Kolmogorov-Smirnov p > 0.05", KS.pvalue > 0.05)
def denied(q):
    try:
        readable(q)
        return False
    except PathDenied:
        return True


show_def(denied)
expect("the path guard refuses the hidden folder, the original snapshot and absolute paths",
       all(denied(q) for q in ["../hidden/answer_key.json", "../original/searches/binary_search.py",
                               "/etc/passwd", "searches/../../hidden/full"]))
expect("the path guard allows a file of the audited tree", not denied("searches/binary_search.py"))
