#%% md
## S32 - Plans as data

**Theory.** The first form a plan can take is a **document**: a small JSON object that lists phases and their settings, and says nothing about how they run. A document has real advantages. It can be checked against a schema before anything happens. It can be drawn as a picture, compared with another plan line by line, stored, and approved by somebody who does not read Python. And whoever writes it, a person or a model, cannot make it do anything the format has no word for.

That last property is also the weakness, and S35 measures it. Here we build the three pieces every data plan needs:

- a **schema** that says which plans are well formed: a title, a goal, and one to six phases, each of kind `scan`, `verify` or `report` with its own settings;
- a **validator** that adds the rules a schema cannot express, such as "a verify phase needs a scan phase before it";
- a **compiler** that turns a valid plan into a short **plan program** in the runtime's own words. A data plan is never interpreted by a pile of `if` statements. It becomes ordinary plan code, the same kind of code the lead will later write itself, and that code runs on the runtime of Part IV.

**In plain terms.** A plan written as a form to fill in. The form is easy to check, and our own code turns a filled-in form into instructions for the runtime.

**For teams.** Start with plans as data whenever the shape of your workflow is known. They are easy to review, easy to diff in a pull request, and impossible to abuse. Move to plans as programs only for the parts a form cannot describe, and measure that the move pays.

![plans](attachment:plans.png)

#%% code
PHASE_KINDS = ["scan", "verify", "report"]
PLAN_SCHEMA = {
    "type": "object", "required": ["title", "phases"], "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "minLength": 3, "maxLength": 80},
        "goal": {"type": "string", "maxLength": 400},
        "phases": {"type": "array", "minItems": 1, "maxItems": 6, "items": {
            "type": "object", "required": ["name", "kind"], "additionalProperties": False,
            "properties": {
                "name": {"type": "string", "minLength": 1, "maxLength": 40},
                "kind": {"enum": PHASE_KINDS},
                "model": {"enum": sorted(MODELS)},
                "shard_tokens": {"type": "integer", "minimum": 5_000, "maximum": 200_000},
                "lenses": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"enum": ["general"] + LENSES}},
                "batch_size": {"type": "integer", "minimum": 1, "maximum": 8},
                "skeptics": {"type": "integer", "minimum": 1, "maximum": 5},
                "need": {"type": "integer", "minimum": 1, "maximum": 5},
                "evidence": {"type": "boolean"},
                "why": {"type": "string", "maxLength": 300}}}}}}
PHASE_DEFAULTS = {"scan": {"model": "worker", "shard_tokens": SHARD_TOKENS, "lenses": ["general"]},
                  "verify": {"model": "judge", "batch_size": 6, "skeptics": 3, "need": 2, "evidence": True},
                  "report": {"model": "lead"}}
print(f"[plan] a data plan has {len(PLAN_SCHEMA['properties'])} top-level fields and phases of {len(PHASE_KINDS)} kinds; "
      f"settings per phase: {', '.join(k for k in PLAN_SCHEMA['properties']['phases']['items']['properties'] if k not in ('name', 'kind'))}")
for kind, d in PHASE_DEFAULTS.items():
    print(f"  {kind:<7} defaults: {d}")

#%% md
**`validate_plan(plan)`** returns a list of readable problems, empty for a good plan. The schema check comes first. Then come seven rules that need to see the whole plan at once:

1. phase names are unique, so events and figures can tell phases apart;
2. there is exactly one `report` phase, and it is the last one;
3. every `verify` phase has a `scan` phase somewhere before it;
4. a vote cannot ask for more agreeing skeptics than there are (`need` at most `skeptics`);
5. settings belong to their kind: a `verify` phase has no lenses and a `scan` phase has no skeptics, because a setting in the wrong place is almost always a misunderstanding;
6. a shard, with the instruction and room for the answer, must fit the worker's context window;
7. the plan may not start more workers than `MAX_AGENTS_PER_RUN`.

Every problem names the phase it was found in, because these messages go back to the lead when it has to repair its own plan (S34).

#%% code
OWN_SETTINGS = {"scan": {"shard_tokens", "lenses"}, "verify": {"batch_size", "skeptics", "need", "evidence"}, "report": set()}
ANY_SETTINGS = {"name", "kind", "model", "why"}


def validate_plan(plan):
    """Readable problems with a data plan; an empty list when it is good."""
    errors = validate(plan, PLAN_SCHEMA)
    if errors:
        return errors
    phases, out = plan["phases"], []
    names = [p["name"] for p in phases]
    for n in sorted({n for n in names if names.count(n) > 1}):
        out.append(f"two phases are called '{n}'; give every phase its own name")
    kinds = [p["kind"] for p in phases]
    if kinds.count("report") != 1 or kinds[-1] != "report":
        out.append("the plan needs exactly one report phase, and it must be the last phase")
    for i, p in enumerate(phases):
        where = f"phase '{p['name']}'"
        if p["kind"] == "verify" and "scan" not in kinds[:i]:
            out.append(f"{where} verifies findings, but no scan phase comes before it")
        if p.get("need", 1) > p.get("skeptics", PHASE_DEFAULTS["verify"]["skeptics"]) and p["kind"] == "verify":
            out.append(f"{where} needs {p['need']} agreeing skeptics but has only {p.get('skeptics', 3)}")
        for k in sorted(set(p) - ANY_SETTINGS - OWN_SETTINGS[p["kind"]]):
            out.append(f"{where} is a {p['kind']} phase and cannot have the setting '{k}'")
        if p["kind"] == "scan":
            tokens = p.get("shard_tokens", SHARD_TOKENS)
            window = CONTEXT_TOKENS.get(MODELS.get(p.get("model", "worker")), 128_000)
            if tokens + 20_000 > window:
                out.append(f"{where}: shards of {tokens:,} tokens plus about 20,000 for the instruction and the answer "
                           f"do not fit the {window:,}-token window of {p.get('model', 'worker')}")
    workers = sum(plan_workers(plan).values())
    if workers > MAX_AGENTS_PER_RUN:
        out.append(f"the plan would start about {workers:,} workers; the limit per run is {MAX_AGENTS_PER_RUN:,}")
    return out

show_def(validate_plan)

#%% md
**Counting a data plan's workers by reading it.** A data plan has no loops and no conditions, so its size can be read off directly. A scan phase starts one worker per shard per lens, exactly. A verify phase starts one skeptic per batch per sample, and the number of batches depends on how many places the scans report, which nobody knows in advance. **`plan_workers(plan)`** uses the average measured so far: findings per scan call and places per finding, from the kit run of S31 and from the ledger. The verify count is therefore an estimate, and it is printed with a tilde. For programs, S37 replaces this arithmetic with a dry run.

#%% code
def scan_stats():
    """(findings per scan call, places per finding), measured from the ledger and the kit's trace, with fallbacks."""
    counts = []
    for (blob,) in FRONT_DOOR.ledger.query("SELECT reply FROM calls WHERE role = 'scan' LIMIT 400"):
        text = json.loads(zlib.decompress(blob).decode()).get("text", "")
        counts.append(len((extract_json(text) or {}).get("findings", []) or []))
    per_call = float(np.mean(counts)) if len(counts) >= 10 else 4.0
    places = len(dedupe(KIT.trace["found"])) / max(1, len(KIT.trace["found"])) if KIT.trace["found"] else 0.7
    return per_call, places


def plan_workers(plan):
    """Workers per phase name: exact for scan and report phases, estimated for verify phases."""
    per_call, place_ratio = SCAN_STATS
    out, candidates = {}, 0.0
    for p in plan["phases"]:
        s = {**PHASE_DEFAULTS[p["kind"]], **p}
        if s["kind"] == "scan":
            n = len(shards(s["shard_tokens"])) * len(s["lenses"])
            candidates = candidates + n * per_call * place_ratio
        elif s["kind"] == "verify":
            n = math.ceil(candidates / s["batch_size"]) * s["skeptics"]
            candidates = candidates * 0.5                     # assumed share confirmed, for a later phase's count
        else:
            n = 1
        out[p["name"]] = n
    return out

show_def(scan_stats, plan_workers)
SCAN_STATS = scan_stats()
print(f"[estimate] {SCAN_STATS[0]:.1f} findings per scan call and {SCAN_STATS[1]:.2f} places per finding, "
      f"from {len(FRONT_DOOR.ledger.query('SELECT key FROM calls WHERE role = ' + repr('scan')))} scan calls in the ledger")

#%% md
The context windows used by rule 6 are the provider's published ones, from the parameters of S0.

#%% code
for role, m in sorted(MODELS.items()):
    print(f"  {role:<9} {m.split('/')[-1]:<22} context {CONTEXT_TOKENS[m]:>8,} tokens")

#%% md
**The validator, tested on broken plans.** Each plan below is the fixed plan of this section with one thing broken. The table shows the first problem the validator reports, which is the text a lead would read.

#%% code
FIXED_PLAN = {
    "title": "Fixed audit: scan with three lenses, verify with three skeptics, report",
    "goal": "Find the behaviour bugs in the library. Every file is read through three lenses; every finding is checked by "
            "three skeptics with the sandbox result in front of them; what two of them confirm is reported.",
    "phases": [
        {"name": "Scan", "kind": "scan", "model": "worker", "shard_tokens": SHARD_TOKENS, "lenses": list(LENSES),
         "why": "every file read three times, each time looking for a different family of mistakes"},
        {"name": "Verify", "kind": "verify", "model": "judge", "batch_size": 6, "skeptics": 3, "need": 2, "evidence": True,
         "why": "most findings are false alarms; three independent skeptics with evidence remove them"},
        {"name": "Report", "kind": "report", "model": "lead", "why": "merge, rank and summarise what survived"},
    ]}


def broken(change):
    """A deep copy of the fixed plan with one change applied."""
    p = copy.deepcopy(FIXED_PLAN)
    change(p)
    return p

show_def(broken)
BROKEN = {
    "an unknown phase kind": broken(lambda p: p["phases"][0].update(kind="read")),
    "a shard size of 900,000 tokens": broken(lambda p: p["phases"][0].update(shard_tokens=900_000)),
    "two phases called Scan": broken(lambda p: p["phases"][1].update(name="Scan")),
    "no report phase": broken(lambda p: p["phases"].pop()),
    "verify before any scan": broken(lambda p: p["phases"].insert(0, p["phases"].pop(1))),
    "need 3 of 2 skeptics": broken(lambda p: p["phases"][1].update(skeptics=2, need=3)),
    "lenses on a verify phase": broken(lambda p: p["phases"][1].update(lenses=["logic"])),
    "shards too big for the window": broken(lambda p: p["phases"][0].update(model="omni", shard_tokens=300_000)),
    "an extra field the format lacks": broken(lambda p: p.update(loop_until_dry=True)),
}
VALIDATION = [{"plan": name, "problems": len(validate_plan(p)), "first": (validate_plan(p) or ["(none)"])[0][:110]}
              for name, p in BROKEN.items()]
table([{"plan": "the fixed plan itself", "problems": len(validate_plan(FIXED_PLAN)), "first": "(none)"}] + VALIDATION,
      [("plan", "what is broken", ""), ("problems", "problems", "d"), ("first", "first problem reported", "")])

#%% md
The last row is worth a second look. A plan that asks to *loop until nothing new is found* is rejected, not because looping is wrong, but because the format has no word for it. S35 comes back to exactly this.

**`compile_plan(plan)`** writes the plan program. Each phase kind has a fixed template of two to four lines; the settings fill in the numbers. The program keeps a running list called `candidates`: a scan phase adds its findings to it and merges duplicates, a verify phase replaces it by what the vote kept, and the report phase reports it. The generated text is ordinary plan code, printed below so it can be read.

#%% code
def compile_plan(plan):
    """The plan program for a valid data plan."""
    lines = [f"# {plan['title']}", "candidates = []"]
    for p in plan["phases"]:
        s = {**PHASE_DEFAULTS[p["kind"]], **p}
        lines.append(f"phase({s['name']!r})")
        if s["kind"] == "scan":
            lines += [f"found = flatten(parallel([lambda s=s, lens=lens: scan(s, lens, model={s['model']!r}) "
                      f"for s in shards({s['shard_tokens']}) for lens in {list(s['lenses'])!r}]))",
                      "candidates = dedupe(candidates + found)",
                      f"log(f\"{s['name']}: {{len(found)}} findings, {{len(candidates)}} places so far\")"]
        elif s["kind"] == "verify":
            lines += [f"verdicts = flatten(parallel([lambda b=b, k=k: check(b, sample=k, model={s['model']!r}, "
                      f"with_evidence={s['evidence']}) for b in batches(candidates, {s['batch_size']}) for k in range({s['skeptics']})]))",
                      f"candidates = vote(candidates, verdicts, need={s['need']})",
                      f"log(f\"{s['name']}: {{len(candidates)}} confirmed\")"]
        else:
            lines.append(f"result = report(candidates, model={s['model']!r})")
    return "\n".join(lines)

show_def(compile_plan)
FIXED_PROGRAM = compile_plan(FIXED_PLAN)
print(FIXED_PROGRAM)
ast.parse(FIXED_PROGRAM)
print(f"\n[compile] {len(FIXED_PLAN['phases'])} phases -> {len(FIXED_PROGRAM.splitlines())} lines of plan code; it parses")

#%% md
**`run_program(src, kit)`** executes plan code with nothing in reach but the kit's vocabulary and a short list of harmless built-in functions, and returns whatever the program assigns to `result`. For programs our own compiler wrote, that is all the safety needed. When the lead starts writing programs itself (S36), a checker runs before this function is ever called. **`run_plan(plan, run_id, number)`** is the whole path for one run: compile if needed, create the run and its kit, execute, save the trace, and score the outcome.

#%% code
import builtins

PLAN_BUILTINS = ["len", "range", "enumerate", "zip", "sorted", "min", "max", "sum", "any", "all", "list", "dict", "set",
                 "tuple", "str", "int", "float", "round", "abs"]


def run_program(src, kit):
    """Execute plan code with only the kit's names and a few built-ins; return what it assigns to `result`."""
    env = dict(kit.names())
    env["__builtins__"] = {n: getattr(builtins, n) for n in PLAN_BUILTINS}
    exec(compile(src, f"<plan {kit.run.run_id}>", "exec"), env)
    return env.get("result")


def run_plan(plan, run_id, number=0, llm=None, concurrency=32, title=None):
    """Compile (if needed), run and score one plan; returns (run, kit, result, outcome)."""
    src = plan if isinstance(plan, str) else compile_plan(plan)
    run = Run(title or (plan["title"] if isinstance(plan, dict) else run_id), (plan.get("goal", "") if isinstance(plan, dict) else ""),
              run_id=run_id, llm=llm, concurrency=concurrency)
    kit = AuditKit(run, number)
    result = run.run_sync(lambda r: run_program(src, kit))
    kit.save()
    return run, kit, result, outcome(result, kit)

show_def(run_program, run_plan)

#%% md
**Drawing a plan.** **`draw_plan(ax, plan)`** turns a data plan into a page: a box per phase, left to right, with its kind, model and settings, and one small circle per worker it will start (a ring of circles for the estimated ones). It is used for the fixed plan below and for the lead's plans in S34.

#%% code
KIND_COLOUR = {"scan": C1, "verify": C4, "report": C3}


def draw_plan(ax, plan, compact_text=False):
    """A plan as a row of phase boxes with their settings and worker counts."""
    phases, counts = plan["phases"], plan_workers(plan)
    n = len(phases)
    ax.set_xlim(0, n * 3.2)
    ax.set_ylim(0, 4.2)
    ax.axis("off")
    for i, p in enumerate(phases):
        s = {**PHASE_DEFAULTS[p["kind"]], **p}
        x = i * 3.2 + 0.15
        ax.add_patch(plt.Rectangle((x, 0.9), 2.7, 3.0, facecolor=SURF, edgecolor=KIND_COLOUR[s["kind"]], lw=1.6))
        ax.text(x + 0.12, 3.62, f"{i + 1}. {s['name']}", fontsize=9, weight="bold", va="top")
        if s["kind"] == "scan":
            detail = f"{len(shards(s['shard_tokens']))} shards of {s['shard_tokens'] // 1000}k\nlenses: {', '.join(s['lenses'])}"
        elif s["kind"] == "verify":
            detail = (f"batches of {s['batch_size']}, {s['skeptics']} skeptic(s)\nkeep if {s['need']} agree"
                      f"\nevidence {'on' if s['evidence'] else 'off'}")
        else:
            detail = "one worker merges\nand ranks"
        ax.text(x + 0.12, 3.2, f"{s['kind']} | {s['model']}\n{detail}", fontsize=7 if compact_text else 7.6, va="top", color=INK2)
        k = counts[p["name"]]
        shown = min(k, 60)
        xs = [x + 0.24 + (j % 12) * 0.2 for j in range(shown)]
        ys = [1.12 + (j // 12) * 0.2 for j in range(shown)]
        colour = KIND_COLOUR[s["kind"]]
        ax.scatter(xs, ys, s=26, facecolors=colour if s["kind"] != "verify" else "none", edgecolors=colour, linewidths=1)
        ax.text(x + 2.6, 3.62, f"{'~' if s['kind'] == 'verify' else ''}{k} worker{'s' if k != 1 else ''}"
                + (" (60 shown)" if k > shown else ""), fontsize=7.6, ha="right", va="top", color=INK2)
        if i < n - 1:
            ax.annotate("", xy=(x + 3.12, 2.4), xytext=(x + 2.88, 2.4), arrowprops=dict(arrowstyle="-|>", color=INK2))

show_def(draw_plan)

#%% code
# FIG  the fixed plan, drawn from its data
fig, ax = plt.subplots(figsize=(10.4, 3.4))
draw_plan(ax, FIXED_PLAN)
total = sum(plan_workers(FIXED_PLAN).values())
finish(fig, "s32_fixed_plan", f"The fixed plan: three phases, about {total} workers, every number readable from the plan itself",
       "filled circles: workers known exactly; rings: estimated from the findings measured so far")

#%% md
**Reading FIG {{figures.s32_fixed_plan}} (s32_fixed_plan).** The plan is three boxes. The scan phase starts {{fixed.scan_workers}} workers, one per shard per lens, and that number is exact. The verify phase starts about {{fixed.verify_workers}} skeptics, an estimate, because it depends on how many places the scans will report. The report phase is one worker. Everything a reviewer needs to approve this plan is on the page: what runs, on which model, with which settings, and roughly how many calls it will make.

#%% md
### Baseline C: the fixed plan, run three times

The fixed plan is the third baseline, after one agent alone (A) and the sequential team (B). It is a good, sensible pipeline that a careful engineer could write without any model's help: read everything three times through three lenses, verify every finding three times with evidence, and report. The dynamic plans of this Part must beat it, or at least match it more cheaply, to justify letting a model write plans at all.

Each of the three runs uses its own sample offset (S31), so the three runs are three independent looks at the same library.

#%% code
C_RUNS, C_OBJS = [], []
for r in range(RUNS):
    run, kit, result, out = run_plan(FIXED_PLAN, f"c-fixed-{r}", number=r)
    C_RUNS.append({"run": r, **out})
    C_OBJS.append((run, kit, result))
    print(f"[C{r}] {run.status}: {out['findings']} findings -> {out['checked']} places checked -> {out['confirmed']} confirmed -> "
          f"{out['bugs_reported']} reported; {out['tp']} planted bugs found, {out['fp']} other places; "
          f"{out['calls']} calls, {out['cents']:.1f} cents")
SOLO_REC, SEQ_REC = load_exp("solo"), load_exp("sequential")
rows = [{"arm": f"A: one agent, run {i}", "recall": r["recall"], "precision": r["precision"], "cents": r.get("cents")}
        for i, r in enumerate(SOLO_REC["runs"])]
rows.append({"arm": "B: sequential team", "recall": SEQ_REC["recall"], "precision": SEQ_REC["precision"], "cents": SEQ_REC["cents"]})
rows += [{"arm": f"C: fixed plan, run {c['run']}", "recall": c["recall"], "precision": c["precision"], "cents": c["cents"]}
         for c in C_RUNS]
table(rows, [("arm", "arm and run", ""), ("recall", "recall", ".2f"), ("precision", "precision", ".2f"), ("cents", "cents", ".1f")])

#%% code
# FIG  the three baselines side by side: what each found, and what it cost
fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.4))
baseline_arms = [("A", [r["recall"] for r in SOLO_REC["runs"]], [r["precision"] or 0 for r in SOLO_REC["runs"]],
         [r.get("cents") or 0 for r in SOLO_REC["runs"]], MUTED),
        ("B", [SEQ_REC["recall"]], [SEQ_REC["precision"] or 0], [SEQ_REC["cents"]], C2),
        ("C", [c["recall"] for c in C_RUNS], [c["precision"] or 0 for c in C_RUNS], [c["cents"] for c in C_RUNS], C1)]
for ax, idx, label in ((axes[0], 1, "recall (share of the planted bugs)"), (axes[1], 2, "precision"), (axes[2], 3, "cents per run")):
    for x, arm in enumerate(baseline_arms):
        ys = arm[idx]
        ax.scatter([x] * len(ys), ys, color=arm[4], s=42, zorder=3)
        ax.plot([x - 0.2, x + 0.2], [np.mean(ys)] * 2, color=arm[4], lw=2)
    ax.set_xticks(range(len(baseline_arms)), [a[0] for a in baseline_arms])
    ax.set_xlim(-0.6, len(baseline_arms) - 0.4)
    panel(ax, label)
axes[0].set_ylim(0, 1)
axes[1].set_ylim(0, 1)
c_mean = float(np.mean([c["recall"] for c in C_RUNS]))
finish(fig, "s32_baselines", f"The fixed plan found {c_mean:.0%} of the planted bugs on average, against "
       f"{np.mean([r['recall'] for r in SOLO_REC['runs']]):.0%} for one agent alone",
       "A: one agent alone (S17); B: a lead with helpers one at a time (S19); C: the fixed plan, three runs; bars are means")

#%% md
**Reading FIG {{figures.s32_baselines}} (s32_baselines).** Each dot is one run; the bar is the mean. The fixed plan (C) reached a mean recall of {{fixed.recall_mean|.2f}}, against {{solo.recall_mean|.2f}} for one agent alone and {{sequential.recall|.2f}} for the sequential team, with a mean precision of {{fixed.precision_mean|.2f}}. It paid {{fixed.cents_mean|.1f}} cents per run, where one agent alone spent {{solo.cents_mean|.1f}}. These are the cents paid in this session: calls already in the ledger from earlier sections cost nothing, so at full price a run of C is worth far more, and S37 puts that number next to its estimate. The spread between C's three runs, {{fixed.recall_min|.2f}} to {{fixed.recall_max|.2f}}, is the noise any later comparison must look past. From here on, C is the bar: a plan the lead writes has to do better than this, or as well for less.

#%% code
FIXED_COUNTS = plan_workers(FIXED_PLAN)
save_exp("fixed", {"runs": C_RUNS, "recall_mean": float(np.mean([c["recall"] for c in C_RUNS])),
                   "recall_min": min(c["recall"] for c in C_RUNS), "recall_max": max(c["recall"] for c in C_RUNS),
                   "precision_mean": float(np.mean([c["precision"] or 0 for c in C_RUNS])),
                   "cents_mean": float(np.mean([c["cents"] for c in C_RUNS])),
                   "calls_mean": float(np.mean([c["calls"] for c in C_RUNS])), "minutes_mean": float(np.mean([c["seconds"] for c in C_RUNS])) / 60,
                   "scan_workers": FIXED_COUNTS["Scan"], "verify_workers": FIXED_COUNTS["Verify"],
                   "program_lines": len(FIXED_PROGRAM.splitlines()), "broken_caught": sum(v["problems"] > 0 for v in VALIDATION),
                   "broken_total": len(VALIDATION)})
results = []
expect("the fixed plan is valid", validate_plan(FIXED_PLAN) == [])
expect("every broken plan is caught, each with at least one readable problem", all(v["problems"] > 0 for v in VALIDATION))
expect("the compiled program parses and ends by assigning the result", "result = report(" in FIXED_PROGRAM.splitlines()[-1])
expect("all three runs of the fixed plan completed", all(c["status"] == "completed" for c in C_RUNS))
expect("every run of the fixed plan read every file", all(c["coverage"] == 1.0 for c in C_RUNS))
expect("each run's scan phase started exactly the workers the plan says",
       all(sum(t.label.startswith("scan:") for t in run.threads) == FIXED_COUNTS["Scan"] for run, _, _ in C_OBJS))
