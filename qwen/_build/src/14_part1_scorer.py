#%% md
## S4 - The scorer: what counts as finding a bug

**Theory.** Every arm of every experiment ends with a list of **findings**: a file, a line, the function, a one-sentence claim, and a call that should fail. The scorer turns that list into two numbers. **Recall** is the share of planted bugs that at least one finding points at. **Precision** is the share of distinct findings that point at a planted bug. The hard part is deciding what "points at" means, and the scorer has to decide it the same way every time, for every arm, without asking a model.

Models are vague about line numbers. A worker that has read 40,000 tokens of code will often name the line next to the right one, or the line where the faulty value is used rather than the line where it is computed. So a finding **matches** a bug when it names the same file, lands in the **same function**, and is within **five lines** of the planted line. Five is a judgement call, so S63 re-scores everything with windows from 0 to 10 lines and with function-only matching, and checks that no conclusion depends on the choice. Two findings that match the same bug count once; the second is recorded as a **duplicate**, which costs nothing in precision but is reported, because duplicates are wasted work. A finding that matches nothing is a **false positive**, unless S66 later shows it is a real bug in the original code that we did not plant.

**In plain terms.** You get credit for a bug if you name the right file and the right function and land within five lines of it. Saying it twice does not count twice.

**For teams.** Write the matching rule down before the first run and keep it in code. A rule decided after seeing the results can always be bent toward the result you hoped for.

#%% md
**`Finding`** is what any agent, worker or baseline reports. Only the file and the line are needed for scoring. The claim, the failing call and the expected value are what a human or a verifier reads.

#%% code
@dataclass
class Finding:
    file: str                 # path inside the audited tree, such as "searches/binary_search.py"
    line: int                 # the line the finding points at
    function: str = ""        # the function it names, if any
    claim: str = ""           # one sentence: what is wrong
    failing_call: str = ""    # a call that should show the bug, such as "binary_search([1, 2, 3], 3)"
    expected: str = ""        # what that call should return
    source: str = ""          # who reported it: an arm, a worker, a lens

show_def(Finding)

#%% md
**`normalise_path`** and **`function_at`** clean up what a model writes before it is compared. A model may write `./searches/binary_search.py`, the full path from the project root, or Windows separators; all of these mean the same file. `function_at` looks the line up in the audited copy, the copy the agent actually read.

#%% code
AUDITED_SPANS = {p: function_spans(ast.parse((AUDITED / p).read_text(encoding="utf-8"))) for p in CORPUS}


def normalise_path(path):
    """A path as the corpus spells it: relative, forward slashes, no leading ./ or tree prefix."""
    p = re.sub(r"/+", "/", str(path).strip().replace("\\", "/"))
    changed = True
    while changed:                                  # strip prefixes in any order and any number
        changed = False
        for prefix in ("./", "/", "data/algorithms/audited/", "algorithms/audited/", "audited/"):
            if p.startswith(prefix):
                p, changed = p[len(prefix):], True
    return p


def function_at(path, line):
    """The function around a line of the audited copy, or None."""
    return enclosing(AUDITED_SPANS.get(path, []), int(line))

show_def(normalise_path, function_at)
for messy in ["./data/algorithms/audited/searches/binary_search.py", "audited\\searches\\binary_search.py", "/searches//binary_search.py"]:
    print(f"[paths] {messy!r:<55} -> {normalise_path(messy)}")
b0 = ANSWER_KEY[0]
print(f"[function_at] {b0['path']}:{b0['line']} is in {function_at(b0['path'], b0['line'])} (the key says {b0['function']})")

#%% md
**`Score`** holds everything one scoring pass produces, and **`match(findings)`** fills it. For each finding the scorer looks for planted bugs in the same file and keeps those that pass the rule; when several do, the nearest wins. False positives are counted once per file and function, so a worker that repeats the same wrong claim three times is charged once, as a duplicate wrong claim is still one wrong idea.

#%% code
@dataclass
class Score:
    found: list               # ids of the planted bugs matched at least once
    recall: float             # found / planted
    precision: float          # distinct matched / (distinct matched + distinct false positives); None with no findings
    tp: int                   # distinct planted bugs matched
    fp: int                   # distinct false positives
    duplicates: int           # findings that matched a bug another finding had already matched
    unmatched: list           # the findings that matched nothing
    n: int                    # findings scored


def match(findings, key=None, window=5, scope="function"):
    """Score findings against the answer key. scope: 'function' (same function and within window), 'line' (window only), 'function-only' (same function, any line)."""
    key = ANSWER_KEY if key is None else key
    bugs_in = collections.defaultdict(list)
    for b in key:
        bugs_in[b["path"]].append(b)
    matched, duplicates, unmatched, fp_keys = {}, 0, [], set()
    for f in findings:
        path = normalise_path(f.file)
        try:
            line = int(f.line)
        except (TypeError, ValueError):
            line = -1
        fn = function_at(path, line) if line > 0 else None
        hits = []
        for b in bugs_in.get(path, []):
            near = abs(line - b["line"]) <= window
            same_fn = fn == b["function"] or (f.function and f.function.split(".")[-1] == b["function"].split(".")[-1])
            ok = (near and same_fn) if scope == "function" else near if scope == "line" else same_fn
            if ok:
                hits.append((abs(line - b["line"]), b["id"]))
        if hits:
            bid = min(hits)[1]
            if bid in matched:
                duplicates += 1
            else:
                matched[bid] = f
        else:
            unmatched.append(f)
            fp_keys.add((path, fn or f"line {line // 10}"))
    tp, fp = len(matched), len(fp_keys)
    return Score(found=sorted(matched), recall=(tp / len(key)) if key else None, precision=(tp / (tp + fp)) if tp + fp else None,
                 tp=tp, fp=fp, duplicates=duplicates, unmatched=unmatched, n=len(findings))

show_def(Score, match)

#%% md
**Testing the scorer on findings we wrote by hand.** Each case below is one rule from the theory above, built from a real planted bug so the test exercises the real key. If any of these failed, every recall and precision in the notebook would be wrong.

#%% code
b = next(k for k in ANSWER_KEY if sum(1 for s in AUDITED_SPANS[k["path"]] if s[2] != k["function"]) >= 1)   # a file with another function
other_fn = next(s for s in AUDITED_SPANS[b["path"]] if s[2] != b["function"])
clean_file = next(p for p in sorted(CORPUS) if p not in {k["path"] for k in ANSWER_KEY})
cases = {
    "exact hit":            [Finding(b["path"], b["line"])],
    "three lines off":      [Finding(b["path"], b["line"] + 3, b["function"])],
    "twenty lines off":     [Finding(b["path"], b["line"] + 20)],
    "said twice":           [Finding(b["path"], b["line"]), Finding(b["path"], b["line"] - 1, b["function"])],
    "a clean file":         [Finding(clean_file, 10)],
    "messy path":           [Finding("./data/algorithms/audited/" + b["path"], b["line"])],
    "no findings":          [],
    "every bug, exactly":   [Finding(k["path"], k["line"]) for k in ANSWER_KEY],
}
SC = {name: match(fs) for name, fs in cases.items()}
for name, sc in SC.items():
    print(f"  {name:<20} findings {sc.n:>2}   matched {sc.tp:>2}   false positives {sc.fp}   duplicates {sc.duplicates}   "
          f"recall {sc.recall:.3f}   precision {'-' if sc.precision is None else f'{sc.precision:.2f}'}")

#%% code
results = []
expect("an exact hit matches", SC["exact hit"].tp == 1 and SC["exact hit"].fp == 0)
expect("three lines off, same function, still matches", SC["three lines off"].tp == 1)
expect("twenty lines off is a false positive", SC["twenty lines off"].tp == 0 and SC["twenty lines off"].fp == 1)
expect("saying it twice counts once, plus one duplicate", SC["said twice"].tp == 1 and SC["said twice"].duplicates == 1)
expect("a finding in a clean file is a false positive", SC["a clean file"].fp == 1 and SC["a clean file"].tp == 0)
expect("a messy path is normalised", SC["messy path"].tp == 1)
expect("no findings: recall 0, precision undefined", SC["no findings"].recall == 0 and SC["no findings"].precision is None)
expect("every bug exactly: recall 1 and precision 1", SC["every bug, exactly"].recall == 1 and SC["every bug, exactly"].precision == 1)
wrong = match([Finding(b["path"], other_fn[0] + 1)], window=10_000, scope="function")
expect("a line inside a different function does not match, whatever the window", wrong.tp == 0)

#%% md
**`sensitivity(findings)`** re-scores one list of findings under every matching rule we might have chosen instead. It is used in S63 on the real results. Here it runs on a synthetic list in which every finding is placed a random 0 to 8 lines away from its bug, to show what the curve looks like.

#%% code
def sensitivity(findings, windows=range(0, 11)):
    """Recall under each line window (same function), plus function-only and line-only matching."""
    rows = [{"rule": f"same function, within {w} lines", "recall": match(findings, window=w).recall} for w in windows]
    rows.append({"rule": "same function, any line", "recall": match(findings, scope="function-only").recall})
    rows.append({"rule": "within 5 lines, any function", "recall": match(findings, window=5, scope="line").recall})
    return rows

show_def(sensitivity)
rng = random.Random(SEED)
fuzzy = [Finding(k["path"], k["line"] + rng.randint(-8, 8)) for k in ANSWER_KEY]
SENS = sensitivity(fuzzy)
for r in SENS[:11:2] + SENS[11:]:
    print(f"  {r['rule']:<34} recall {r['recall']:.2f}  {bar(r['recall'], 30)}")

#%% code
save_exp("scorer_tests", {"cases": {k: {"tp": v.tp, "fp": v.fp, "duplicates": v.duplicates, "recall": v.recall,
                                        "precision": v.precision} for k, v in SC.items()},
                          "window": 5, "scope": "function"})
print(f"[part I] {sum(ok for _, ok in results)} of {len(results)} scorer checks passed")

#%% md
**Part I recap.** We now have the job and the means to grade it:

- a snapshot of {{corpus.files}} files and {{corpus.lines}} lines of classic algorithms, every one of them passing its own examples;
- {{answer_key.bugs}} planted bugs, each proven by a failing example, quiet enough to be fair, and spread across {{answer_key.folders}} folders and four length quarters;
- an audited tree in which the evidence is hidden and the hiding leaves no fingerprint (largest AUROC {{answer_key.max_auroc|.2f}});
- a path guard that keeps every agent tool inside that tree;
- a scorer with a written rule, tested case by case.

None of it involved a model. From Part II on, every number is measured against these pieces, which is why they came first.

**Try it yourself.**

1. Set `MAX_LOUDNESS` to 1.0 and rerun S2 and S3. How does the loudness histogram in FIG {{figures.s3_quiet_bugs}} change, and what happens to the leak test in FIG {{figures.s3_leak_test}}? Explain why a loud bug is unfair to the comparison in Part VII.
2. Write a thirteenth mutation operator, for example one that replaces `//` with `/`. Run it through `prove` on five files. Which verdict does it get most often, and why?
3. Change the scorer's window from 5 to 0 and rescore the fuzzy findings above. Then argue for the window you would choose for your own team, with a sentence about what a line number from a model is really worth.
