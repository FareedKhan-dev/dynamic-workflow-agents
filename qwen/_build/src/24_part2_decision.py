#%% md
## S13 - The decision measurement: how much code can one worker read at once?

**Theory.** Every design choice after this section depends on one number: how many tokens of code we hand to one worker in one call. We call that piece of work a **shard**. Billing makes big shards tempting. A call costs the same Magicubes whether it carries ten thousand tokens or a hundred thousand, so the whole corpus in 100k-token shards costs about ten calls, while 20k-token shards cost fifty. But a model reading a long input does not attend to all of it equally. Details in the middle of a long context are easier to miss, and a bug is exactly such a detail.

So we measure instead of guessing. We take a **subset** of the corpus that holds 24 of the planted bugs, two per operator, and enough clean files to keep the bugs as rare as they are in the whole corpus. One worker scans it in shards of four sizes, twice each. Three questions follow:

1. How does recall change with shard size, and what does each size cost in calls?
2. Within one shard, does a bug near the end get missed more often than one near the start?
3. Does thinking help? With per-call billing it costs only time, so the question is whether that time buys recall.

The rule for the decision was written before the runs: **use the largest shard size whose recall is within 0.05 of the best size's recall.** That buys the fewest calls without giving up bugs.

**In plain terms.** We test how much code one worker can read at once before it starts missing things, and pick the biggest piece that does not cost us bugs.

**For teams.** Most teams set this number once by intuition ("the model has a 256k window, so send 200k") and never measure it. The window size is how much a model accepts, not how much it uses well.

#%% md
**Showing a worker the code.** **`numbered(path)`** returns a file from the audited tree with every line prefixed by its number, so a worker can cite exact lines. **`render_shard(paths)`** joins several files, each under a `### path` header. **`est_tokens(text)`** estimates a text's size in tokens from its length; the ratio starts at a common rule of thumb and is replaced below by the ratio the server's own token counts imply.

#%% code
CHARS_PER_TOKEN = 3.6     # provisional; calibrated from the server's prompt_tokens at the end of this section


def numbered(path):
    """An audited file with every line numbered, read through the path guard."""
    lines = readable(path).read_text(encoding="utf-8").split("\n")
    return "\n".join(f"{i:>5}| {ln}" for i, ln in enumerate(lines, 1))


def render_shard(paths):
    """Several files as one text, each under a ### header."""
    return "\n\n".join(f"### {p}\n{numbered(p)}" for p in paths)


def est_tokens(text):
    return int(len(text) / CHARS_PER_TOKEN)

show_def(numbered, render_shard, est_tokens)
print(render_shard([DEMO_FILE])[:420])

#%% md
**`pack(paths, target)`** packs whole files into shards of about `target` tokens. Files are grouped by folder so that related code, which often imports each other, lands together. Within a folder the biggest files go first, and each file goes into the first shard with room for it (**first-fit decreasing**, a classic bin-packing rule). A file is never cut in half: a bug in the second half of a file is only understandable with the first half in view.

#%% code
FILE_TOKENS = {p: est_tokens(f"### {p}\n" + numbered(p)) for p in sorted(CORPUS)}


def pack(paths, target):
    """Shards (lists of paths) of about target tokens each; whole files, grouped by folder, first-fit decreasing."""
    shards, sizes = [], []
    for folder in sorted({p.split("/")[0] for p in paths}):
        for p in sorted((q for q in paths if q.split("/")[0] == folder), key=lambda q: -FILE_TOKENS[q]):
            t = FILE_TOKENS[p]
            for i, s in enumerate(sizes):
                if s + t <= target:
                    shards[i].append(p)
                    sizes[i] += t
                    break
            else:
                shards.append([p])
                sizes.append(t)
    return shards

show_def(pack)
ALL_TOKENS = sum(FILE_TOKENS.values())
print(f"[pack] the whole audited corpus is about {ALL_TOKENS:,} tokens with line numbers")
for target in (20_000, 40_000, 60_000, 100_000):
    sh = pack(sorted(CORPUS), target)
    sz = [sum(FILE_TOKENS[p] for p in s) for s in sh]
    print(f"  shards of {target // 1000:>3}k tokens: {len(sh):>3} shards, {min(sz):>6,} to {max(sz):>6,} tokens; one scan of everything = {len(sh)} calls")

#%% md
**The scan worker.** This is the instruction every bug-finding worker in the notebook starts from. It says what counts as a bug and what to ignore, shows how to read the numbered lines, and demands a concrete failing call for every finding. That demand matters twice. It forces the worker to commit to something testable, and Part VI runs that call in a sandbox as evidence for the verifiers. Part VI adds **lenses** to this instruction; here every worker gets the same general one.

#%% code
SCAN_SYSTEM = """You are reviewing Python code for behaviour bugs.

A behaviour bug is a line that makes a function return a wrong result, or crash, for an input that its name and docstring say it should handle. Ignore style, naming, speed, missing type hints, missing checks for invalid input, and anything inside an `if __name__ == "__main__":` block. Most files are correct; report only what you are confident is wrong.

The code is several files. Each file starts with a line `### <path>`, and every code line starts with its line number and a bar, for example `   57| return lo`. Use those numbers.

For each bug give:
- file: the path from its ### header
- line: the number of the faulty line
- function: the function it is in
- claim: one sentence saying what is wrong
- failing_call: one Python call to a function in that file, with literal arguments, that shows the bug
- expected: what that call should return if the code were right
- confidence: a number from 0 to 1

Answer with one JSON object and nothing else: {"findings": [ ... ]}. If you find no bug, answer {"findings": []}."""

FINDINGS_SCHEMA = {"type": "object", "required": ["findings"], "properties": {"findings": {"type": "array", "items": {
    "type": "object", "required": ["file", "line", "claim"],
    "properties": {"file": {"type": "string"}, "line": {"type": "integer"}, "function": {"type": "string"},
                   "claim": {"type": "string"}, "failing_call": {"type": "string"}, "expected": {"type": "string"},
                   "confidence": {"type": "number"}}}}}}
LENS_TEXT = {"general": ""}   # Part VI adds lenses: extra paragraphs that point a worker at one family of mistakes


def scan(paths, *, model=None, lens="general", sample=0, thinking=WORKER_THINKING, tag="scan", phase="", run_id=""):
    """One worker reads one shard and returns (findings, reply)."""
    model = model or MODELS["worker"]
    system = SCAN_SYSTEM + ("\n\n" + LENS_TEXT[lens] if LENS_TEXT.get(lens) else "")
    obj, turns, errs, reply = ask_json(model, system, render_shard(paths), FINDINGS_SCHEMA, tag=tag, role="scan",
                                       phase=phase, run_id=run_id, sample=sample, thinking=thinking, max_tokens=16000)
    found = [Finding(file=f.get("file", ""), line=f.get("line", 0), function=f.get("function", ""), claim=f.get("claim", ""),
                     failing_call=f.get("failing_call", ""), expected=str(f.get("expected", "")), source=f"{tag}#{sample}")
             for f in (obj or {}).get("findings", [])]
    return found, reply

show_def(scan)
print(f"[scan] instruction: {len(SCAN_SYSTEM.split())} words, about {est_tokens(SCAN_SYSTEM)} tokens; schema needs file, line and claim")

#%% md
**A scripted scanner for smoke runs.** In smoke mode no model is called, so a responder plays the scan worker. It cheats on purpose: it reads the answer key and reports each planted bug in the shard it was given, with a probability that falls as the shard gets longer and as the bug sits deeper in it. It also adds a false positive now and then. The shapes it produces are invented, which is exactly what a smoke run needs: every code path below runs, and no number from it is ever quoted.

#%% code
@SCRIPTED.register
def _scan(model, messages, params):
    system = messages[0]["content"]
    if not system.startswith("You are reviewing Python code for behaviour bugs") or "auditing a whole codebase" in system:
        return None                                       # the single agent of S16 shares the first sentence; it is not a scan
    text = messages[-1]["content"]
    if text.startswith("Your answer does not match"):
        return '{"findings": []}'
    heads = [(m.start(), m.group(1)) for m in re.finditer(r"^### (\S+)$", text, re.M)]
    size = len(text) / CHARS_PER_TOKEN
    out = []
    for b in ANSWER_KEY:
        pos = next((s for s, p in heads if p == b["path"]), None)
        if pos is None:
            continue
        depth = pos / max(1, len(text))
        p_find = 0.9 - 0.35 * min(1.0, size / 100_000) - 0.25 * depth
        draw = (zlib.crc32(f"{b['id']}:{messages[0]['content'][-40:]}:{len(text)}:{params.get('enable_thinking')}:{params.get('sample', 0)}"
                           .encode()) % 1000) / 1000
        if draw < p_find:
            out.append({"file": b["path"], "line": b["line"] + (zlib.crc32(b["id"].encode()) % 5) - 2, "function": b["function"],
                        "claim": f"{b['operator']} looks wrong here", "failing_call": "", "expected": "", "confidence": 0.7})
    for k in range(int(size // 25_000)):
        _, p = heads[(k * 7) % len(heads)]
        out.append({"file": p, "line": 5 + k, "function": "", "claim": "this looks suspicious", "confidence": 0.3})
    return json.dumps({"findings": out})

show_def(_scan)

#%% md
**The subset.** Two planted bugs per operator, 24 in all, chosen with the seed, plus clean files drawn at random until the bugs are as rare as in the whole corpus. One worker then scans this subset at four shard sizes, twice each with a different sample index, so every size is measured on two independent looks.

#%% code
rng = random.Random(SEED + 13)
DM_BUGS = []
for op in sorted({b["operator"] for b in ANSWER_KEY}):
    DM_BUGS += rng.sample([b for b in ANSWER_KEY if b["operator"] == op], 2)
density = len(ANSWER_KEY) / len(CORPUS)
n_clean = round(len(DM_BUGS) / density) - len(DM_BUGS)
DM_CLEAN = rng.sample(sorted(p for p in CORPUS if p not in {b["path"] for b in ANSWER_KEY}), n_clean)
DM_FILES = sorted({b["path"] for b in DM_BUGS} | set(DM_CLEAN))
DM_TOKENS = sum(FILE_TOKENS[p] for p in DM_FILES)
print(f"[subset] {len(DM_FILES)} files, {len(DM_BUGS)} planted bugs ({len(DM_BUGS) / len(DM_FILES):.1%} of files, "
      f"the corpus has {density:.1%}), about {DM_TOKENS:,} tokens")
SIZES = [20_000, 40_000, 60_000, 100_000]
JOBS = [(size, i, shard, sample) for size in SIZES for i, shard in enumerate(pack(DM_FILES, size)) for sample in (0, 1)]
print(f"[subset] {len(JOBS)} scans: " + ", ".join(f"{s // 1000}k x {sum(1 for j in JOBS if j[0] == s)}" for s in SIZES))

#%% code
def run_scan_job(job, thinking=WORKER_THINKING):
    size, i, shard, sample = job
    found, reply = scan(shard, sample=sample, thinking=thinking, tag=f"dm:{size // 1000}k:{i}", phase="decision")
    return {"size": size, "shard": i, "sample": sample, "paths": shard, "findings": found, "seconds": reply.seconds,
            "prompt_tokens": reply.prompt_tokens, "chars": len(render_shard(shard)), "thinking": thinking,
            "error": reply.error, "reasoning": len(reply.reasoning)}

show_def(run_scan_job)
t0 = time.perf_counter()
with cf.ThreadPoolExecutor(12) as pool:
    DM = list(pool.map(run_scan_job, JOBS))
print(f"[decision] {len(DM)} scans in {time.perf_counter() - t0:.0f} s; {sum(bool(d['error']) for d in DM)} failed; "
      f"{sum(len(d['findings']) for d in DM)} findings reported")

#%% md
**Scoring each size.** For each shard size and sample, all findings from all its shards are pooled and scored against the 24 subset bugs. Recall is what we decide on; precision and the number of calls are reported alongside, because a size that wins on recall by flooding the verifiers with false positives would not be a win.

#%% code
DM_KEY = DM_BUGS


def score_size(size, sample, thinking=WORKER_THINKING):
    findings = [f for d in DM if d["size"] == size and d["sample"] == sample and d["thinking"] == thinking for f in d["findings"]]
    sc = match(findings, key=DM_KEY)
    calls = sum(1 for d in DM if d["size"] == size and d["sample"] == sample and d["thinking"] == thinking)
    secs = [d["seconds"] for d in DM if d["size"] == size and d["sample"] == sample and d["thinking"] == thinking]
    return {"size": size, "sample": sample, "recall": sc.recall, "precision": sc.precision, "found": sc.tp, "fp": sc.fp,
            "calls": calls, "median_s": float(np.median(secs)) if secs else None}

show_def(score_size)
DM_ROWS = [score_size(s, k) for s in SIZES for k in (0, 1)]
table(DM_ROWS, [("size", "shard tokens", ","), ("sample", "look", "d"), ("found", "found of 24", "d"),
                ("recall", "recall", ".2f"), ("precision", "precision", ".2f"), ("calls", "calls", "d"),
                ("median_s", "median s per call", ".0f")])
MEAN_RECALL = {s: float(np.mean([r["recall"] for r in DM_ROWS if r["size"] == s])) for s in SIZES}
best = max(MEAN_RECALL.values())
CHOSEN = max(s for s in SIZES if MEAN_RECALL[s] >= best - 0.05)
print(f"[decision] mean recall by size: " + ", ".join(f"{s // 1000}k {MEAN_RECALL[s]:.2f}" for s in SIZES))
print(f"[decision] rule: the largest size within 0.05 of the best ({best:.2f})  ->  SHARD_TOKENS = {CHOSEN:,}")

#%% md
**Does depth matter?** For every bug in every scan we know how far into its shard the bug's file started, as a share of the shard. Grouping all bugs from all sizes by that depth shows whether workers read the end of their shard as carefully as the start.

#%% code
def depth_rows():
    rows = []
    for d in DM:
        if d["thinking"] != WORKER_THINKING:
            continue
        here = [b for b in DM_KEY if b["path"] in d["paths"]]
        if not here:
            continue
        text = render_shard(d["paths"])
        found = set(match(d["findings"], key=here).found)
        for b in DM_KEY:
            if b["path"] in d["paths"]:
                rows.append({"size": d["size"], "depth": text.index(f"### {b['path']}") / max(1, len(text)), "found": b["id"] in found})
    return rows

show_def(depth_rows)
DEPTH = depth_rows()
bins = [0, 0.25, 0.5, 0.75, 1.01]
DEPTH_BINS = []
for lo_, hi_ in zip(bins, bins[1:]):
    sel = [r for r in DEPTH if lo_ <= r["depth"] < hi_]
    DEPTH_BINS.append({"depth": f"{lo_:.2f} to {min(1, hi_):.2f}", "bugs": len(sel),
                       "recall": (sum(r["found"] for r in sel) / len(sel)) if sel else None})
table(DEPTH_BINS, [("depth", "where in the shard the file starts", ""), ("bugs", "bug sightings", "d"), ("recall", "found", ".2f")])

#%% md
**Does thinking help?** The 40k-token shards are also scanned with the other setting, on both samples, so the two can be compared.

#%% code
THINK_JOBS = [j for j in JOBS if j[0] == 40_000]
with cf.ThreadPoolExecutor(12) as pool:
    DM += list(pool.map(lambda j: run_scan_job(j, thinking=not WORKER_THINKING), THINK_JOBS))
THINK = []
for thinking in (True, False):
    rs = [score_size(40_000, k, thinking) for k in (0, 1)]
    THINK.append({"thinking": "on" if thinking else "off", "recall": float(np.mean([r["recall"] for r in rs])),
                  "precision": float(np.mean([r["precision"] or 0 for r in rs])),
                  "median_s": float(np.median([d["seconds"] for d in DM if d["size"] == 40_000 and d["thinking"] == thinking]))})
table(THINK, [("thinking", "thinking", ""), ("recall", "recall", ".2f"), ("precision", "precision", ".2f"), ("median_s", "median s per call", ".0f")])

#%% md
### Figures: the decision, in pictures

#%% code
# FIG  the whole job against the published context windows
fig, ax = plt.subplots(figsize=(9.6, 3.0))
windows = [("whole corpus", ALL_TOKENS, C8), ("Qwen3.8-27B window", 262_144, MUTED), ("Qwen3.8-Flash-Next window", 262_144, MUTED),
           ("Qwen3.8-Max window", 991_808, MUTED), (f"one shard ({CHOSEN // 1000}k)", CHOSEN, C1)]
ax.barh(range(len(windows)), [w for _, w, _ in windows], color=[c for _, _, c in windows], height=0.6)
for i, (n, w, _) in enumerate(windows):
    ax.text(w, i, f" {w:,}", va="center", fontsize=8)
ax.set_yticks(range(len(windows)), [n for n, _, _ in windows], fontsize=8.5)
ax.invert_yaxis()
ax.set_xlabel("tokens")
finish(fig, "s13_windows", f"The job is {ALL_TOKENS / 262_144:.1f} times what a worker's context can even accept",
       "window sizes are the provider's published limits, not measured here; how much a model uses well is what the next figure measures")

#%% md
**Reading FIG {{figures.s13_windows}} (s13_windows).** The red bar is the whole audited corpus with line numbers, about {{decision.all_tokens}} tokens. The grey bars are the published context windows of the models we use. The worker model cannot even accept a third of the job in one call. The lead model's window could in principle hold almost all of it, but accepting a text and reading it carefully are different things, which is what the next figure measures. The blue bar is the shard size this section ends up choosing.

#%% code
# FIG  recall and calls against shard size
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5))
ax = axes[0]
for k, marker in ((0, "o"), (1, "s")):
    ax.plot([s / 1000 for s in SIZES], [r["recall"] for r in DM_ROWS if r["sample"] == k], marker=marker, color=C1,
            alpha=0.55, lw=1, label=f"look {k + 1}")
ax.plot([s / 1000 for s in SIZES], [MEAN_RECALL[s] for s in SIZES], "-", color=C1, lw=2.5, label="mean")
ax.axhspan(best - 0.05, best, color=C3, alpha=0.12)
ax.axvline(CHOSEN / 1000, color=C3, ls="--", lw=1.2)
ax.text(CHOSEN / 1000, 0.02, f" chosen: {CHOSEN // 1000}k", color=C6, fontsize=8)
ax.set_xlabel("shard size, thousands of tokens")
ax.set_ylabel("recall on the 24 subset bugs")
ax.set_ylim(0, 1.05)
ax.legend(fontsize=8)
panel(ax, "green band: within 0.05 of the best size")
ax = axes[1]
full_calls = [len(pack(sorted(CORPUS), s)) for s in SIZES]
ax.bar([str(s // 1000) + "k" for s in SIZES], full_calls, color=[C1 if s == CHOSEN else MUTED for s in SIZES], width=0.6)
for i, c in enumerate(full_calls):
    ax.text(i, c, f"{c} calls\n{c * PRICE[MODELS['worker']]:.1f} MC", ha="center", va="bottom", fontsize=8)
ax.set_ylabel("calls for one scan of the whole corpus")
ax.set_ylim(0, max(full_calls) * 1.3)
panel(ax, "what one full scan costs at each size")
finish(fig, "s13_shard_size", f"{CHOSEN // 1000}k-token shards keep recall within 0.05 of the best and cost "
       f"{len(pack(sorted(CORPUS), CHOSEN))} calls per full scan",
       "one worker, 24 planted bugs in a subset as sparse as the corpus, two independent looks per size")

#%% md
**Reading FIG {{figures.s13_shard_size}} (s13_shard_size).** The left panel is the measurement the whole design rests on. Each thin line is one look at the subset and the thick line is their mean. Mean recall was {{decision.recall_20k|.2f}} with 20k-token shards and {{decision.recall_100k|.2f}} with 100k-token shards, and the size chosen by the rule written in advance is **{{decision.chosen}} tokens**, the largest one inside the green band. The right panel is why the rule exists. With per-call billing, every step to a larger shard cuts the calls for one full scan, and those savings repeat for every lens, every round and every run in the rest of the notebook. Two looks per size is a small sample, so the curve is noisy; Part VI re-measures the size inside the full system.

#%% code
# FIG  recall against depth in the shard, and the effect of thinking
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.4))
ax = axes[0]
vals = [b["recall"] if b["recall"] is not None else 0 for b in DEPTH_BINS]
ax.bar(range(len(DEPTH_BINS)), vals, color=C1, width=0.6)
for i, b in enumerate(DEPTH_BINS):
    ax.text(i, vals[i], f"{vals[i]:.2f}\n({b['bugs']})", ha="center", va="bottom", fontsize=8)
ax.set_xticks(range(len(DEPTH_BINS)), [b["depth"] for b in DEPTH_BINS], fontsize=8)
ax.set_xlabel("how deep into the shard the bug's file starts")
ax.set_ylabel("share of sightings found")
ax.set_ylim(0, 1.15)
panel(ax, "all sizes pooled; bracket: number of sightings")
ax = axes[1]
x = np.arange(2)
ax.bar(x - 0.18, [t["recall"] for t in THINK], 0.34, color=C1, label="recall")
ax.bar(x + 0.18, [t["precision"] for t in THINK], 0.34, color=C7, label="precision")
for i, t in enumerate(THINK):
    ax.text(i, 1.02, f"{t['median_s']:.0f} s per call", ha="center", fontsize=8, color=INK2)
ax.set_xticks(x, [f"thinking {t['thinking']}" for t in THINK])
ax.set_ylim(0, 1.15)
ax.legend(fontsize=8, loc="lower right")
panel(ax, "40k shards, two looks each")
finish(fig, "s13_depth_thinking", f"Bugs deep in a shard were found {DEPTH_BINS[-1]['recall'] or 0:.0%} of the time, "
       f"near the start {DEPTH_BINS[0]['recall'] or 0:.0%}",
       f"right: thinking on {THINK[0]['recall']:.2f} recall at {THINK[0]['median_s']:.0f} s per call; off {THINK[1]['recall']:.2f} at {THINK[1]['median_s']:.0f} s")

#%% md
**Reading FIG {{figures.s13_depth_thinking}} (s13_depth_thinking).** The left panel pools every sighting of a subset bug across all scans and asks whether its position in the shard mattered. Bugs whose file started in the first quarter of a shard were found {{decision.depth_first|.0%}} of the time, and those in the last quarter {{decision.depth_last|.0%}}. Any difference here is the reason a single agent reading a long stream of code should be expected to degrade, which Part III tests directly. The right panel compares thinking on and off for the same shards: recall {{decision.think_on|.2f}} against {{decision.think_off|.2f}}, at a median of {{decision.think_on_s|.0f}} s against {{decision.think_off_s|.0f}} s per call. Thinking costs no Magicubes on this service, so the finders in the rest of the notebook keep it on whenever it buys recall.

#%% md
**Calibrating the token estimate.** The server reported the true prompt size of every scan above. Their ratio to the characters we sent replaces the rule of thumb, so every later shard is packed to a real token count.

#%% code
sent = [(d["chars"] + len(SCAN_SYSTEM), d["prompt_tokens"]) for d in DM if d["prompt_tokens"]]
if sent and DW_MODE != "smoke":
    CHARS_PER_TOKEN = sum(c for c, _ in sent) / sum(t for _, t in sent)
    FILE_TOKENS = {p: est_tokens(f"### {p}\n" + numbered(p)) for p in sorted(CORPUS)}
print(f"[tokens] {len(sent)} scans with server token counts; characters per token = {CHARS_PER_TOKEN:.2f}"
      + (" (smoke: the scripted model counts 4 characters a token, so the estimate is kept)" if DW_MODE == "smoke" else ""))
SHARD_TOKENS = CHOSEN
print(f"[params] SHARD_TOKENS = {SHARD_TOKENS:,}, so one scan of the corpus is {len(pack(sorted(CORPUS), SHARD_TOKENS))} calls")

#%% code
save_exp("decision", {"all_tokens": ALL_TOKENS, "subset_files": len(DM_FILES), "subset_bugs": len(DM_BUGS),
                      "subset_tokens": DM_TOKENS, "rows": DM_ROWS, "chosen": CHOSEN,
                      "recall_20k": MEAN_RECALL[20_000], "recall_40k": MEAN_RECALL[40_000], "recall_60k": MEAN_RECALL[60_000],
                      "recall_100k": MEAN_RECALL[100_000], "best": best,
                      "depth": DEPTH_BINS, "depth_first": DEPTH_BINS[0]["recall"], "depth_last": DEPTH_BINS[-1]["recall"],
                      "think_on": THINK[0]["recall"], "think_off": THINK[1]["recall"],
                      "think_on_s": THINK[0]["median_s"], "think_off_s": THINK[1]["median_s"],
                      "chars_per_token": CHARS_PER_TOKEN, "calls": len(DM)})
results = []
expect("every scan returned (none failed outright)", sum(bool(d["error"]) for d in DM) == 0)
expect("the chosen size follows the rule", MEAN_RECALL[CHOSEN] >= best - 0.05 and all(s <= CHOSEN or MEAN_RECALL[s] < best - 0.05 for s in SIZES))
expect("the subset is as sparse as the corpus (within one percentage point)", abs(len(DM_BUGS) / len(DM_FILES) - density) < 0.01)

#%% md
**Part II recap.** We can now talk to the models dependably and measure what we spend:

- a streaming client in the standard library, tested row by row against a local server that fails on command;
- a ledger that turns every answer into a cache entry, a replay record and a line in the accounts, storing shared code once;
- an AIMD gate that found a server's hidden limit on its own, where a fixed limit either lost {{rate_control.fixed16_failed}} of 120 requests or left most of the capacity idle;
- a capability table for six models, and structured output that is checked against a schema and repaired once;
- a measured answer to the question every later design depends on: a worker gets **{{decision.chosen}} tokens** of code per call.

**Try it yourself.**

1. Start the `FakeModelServer` with a capacity of 3 and rerun the three gates in S10. Does AIMD still find the limit? What happens to the fixed gate of 16?
2. In `ModelClient.chat`, remove the random factor from the backoff and rerun the greedy gate. Explain from the 429 counts what the jitter was doing.
3. Change the decision rule in S13 to "within 0.02 of the best" and to "within 0.10 of the best". Which shard sizes would each rule choose, and what would one full scan cost in each case?
