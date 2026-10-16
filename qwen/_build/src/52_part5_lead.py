#%% md
## S33 - The scout: what the lead reads instead of the work

**Theory.** A lead that plans an audit of a million tokens cannot read a million tokens, and should not try: Part III showed what happens to an agent whose context fills up with the material it is meant to organise. The lead needs a **summary of the work**: how much there is, how it is structured, what the measurements so far say, what things cost, and how much may be spent. Every one of those facts can be computed exactly by ordinary code, so the summary is written by a function, not by a model. We call it the **scout**. It is free, it is exact, and it gives the same answer every time, which makes the lead's plans reproducible.

The scout also carries the **measurements** of earlier sections: recall against shard size from S13, findings per scan call, and the median time of each kind of call from the ledger. A lead that knows that 40,000-token shards found as much as 20,000-token ones, at half the calls, can make that decision from evidence instead of from habit.

**In plain terms.** Before planning, the lead gets a one-page fact sheet about the job, produced by a program that measured everything.

**For teams.** Give your planning model a fact sheet produced by code: counts, sizes, prices, limits, measured rates. It is cheaper than letting the model explore, it cannot be wrong about the facts, and it can be checked into the record next to the plan it produced.

#%% code
AUDIT_GOAL = ("Find the behaviour bugs in a library of {files} Python files: places where a function returns a wrong result, "
              "or crashes, for an input its docstring allows. Report each bug with its file, its line and a call that shows it.")


def median_seconds(role):
    """Median seconds of the paid calls of one role, as the lead's page quotes them, or None.

    The medians are read from the ledger once and frozen in a record (artifacts/exp_scout_latency.json). The page the
    lead plans from is part of its request, so it must not drift as the ledger grows: a replay then asks the lead
    exactly what the paid run asked."""
    path = ART / "exp_scout_latency.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8")).get(role)
    xs = sorted(s for (s,) in FRONT_DOOR.ledger.query("SELECT seconds FROM calls WHERE role = ? AND seconds > 0.5", (role,)))
    return xs[len(xs) // 2] if xs else None


def scout(budget_mc=None):
    """A short, exact summary of the audit: size, structure, measurements, prices, limits and budget."""
    folders = collections.Counter(p.split("/")[0] for p in WORK)
    tokens_in = collections.Counter()
    for p in WORK:
        tokens_in[p.split("/")[0]] += FILE_TOKENS[p]
    dec = load_exp("decision")
    return {"files": len(WORK), "lines": AUDITED_LINES, "tokens": sum(FILE_TOKENS[p] for p in WORK),
            "largest_file": max(FILE_TOKENS[p] for p in WORK), "folders": len(folders),
            "top_folders": [(f, folders[f], tokens_in[f]) for f, _ in folders.most_common(6)],
            "shard_options": [{"tokens": t, "shards": len(shards(t)), "recall": dec.get(f"recall_{t // 1000}k")}
                              for t in (20_000, 40_000, 60_000, 100_000)],
            "chosen_shard": SHARD_TOKENS, "findings_per_scan": SCAN_STATS[0], "places_per_finding": SCAN_STATS[1],
            "latency": {r: median_seconds(r) for r in ("scan", "skeptic", "report")},
            "prices": {role: PRICE.get(MODELS[role], 0.2) for role in ("worker", "fast", "judge", "lead", "lead_alt")},
            "max_agents": MAX_AGENTS_PER_RUN, "parallel": 32,
            "budget": round(budget_mc if budget_mc is not None else budget_left(FRONT_DOOR), 1)}

show_def(median_seconds, scout)

#%% md
**`scout_text(s)`** writes the summary as the page the lead reads. It is plain prose with numbers, grouped under three headings: the work, what has been measured, and prices and limits.

#%% code
def scout_text(s):
    """The scout's summary as the page the lead reads."""
    lat = ", ".join(f"{r} {v:.0f} s" for r, v in s["latency"].items() if v) or "not measured yet"
    shard_lines = "\n".join(f"  - {o['tokens'] // 1000}k tokens: {o['shards']} shards"
                            + (f", recall {o['recall']:.2f} in the S13 test" if o["recall"] is not None else "") for o in s["shard_options"])
    return f"""THE WORK
- {s['files']} Python files, {s['lines']:,} lines, about {s['tokens']:,} tokens with line numbers. The largest file is {s['largest_file']:,} tokens.
- {s['folders']} folders; the largest: {', '.join(f'{f} ({n} files, {t // 1000}k tokens)' for f, n, t in s['top_folders'])}.
- Every file has doctest examples, and every example still visible passes. Bugs, if any, are where the visible examples do not reach.

MEASURED SO FAR
- Shard size against recall, one worker per shard on a 15% sample with known bugs:
{shard_lines}
- The measured best shard size is {s['chosen_shard'] // 1000}k tokens.
- A scan worker reports about {s['findings_per_scan']:.1f} findings per call; merging duplicates leaves {s['places_per_finding']:.2f} places per finding.
- Median seconds per call: {lat}.

PRICES AND LIMITS
- Price per call in Magicubes: {', '.join(f'{r} {p}' for r, p in s['prices'].items())}. Billing is per call, not per token.
- At most {s['max_agents']} workers per run; about {s['parallel']} run at the same time.
- Budget for this job: {s['budget']:.0f} Magicubes."""

show_def(scout_text)
if not (ART / "exp_scout_latency.json").exists():          # the first paid run freezes what its page will quote
    save_exp("scout_latency", {r: median_seconds(r) for r in ("scan", "skeptic", "report")})
SCOUT = scout(budget_mc=150)
SCOUT_TEXT = scout_text(SCOUT)
print(SCOUT_TEXT)
print(f"\n[scout] the lead reads {est_tokens(SCOUT_TEXT):,} tokens about a job of {SCOUT['tokens']:,} tokens: "
      f"{est_tokens(SCOUT_TEXT) / SCOUT['tokens']:.3%} of it")

#%% code
results = []
expect("the scout is exact and repeatable: two calls give the same page", scout_text(scout(150)) == SCOUT_TEXT)
expect("the scout's page is under one thousand tokens", est_tokens(SCOUT_TEXT) < 1000)
expect("the scout counts every file of the work", SCOUT["files"] == len(WORK))

#%% md
## S34 - The lead writes a JSON plan

**Theory.** The lead's instruction has three parts. The **plan language**: the phase kinds, their settings and what each costs, with one small example. The **rules**: stay under half the budget, read every file, use the measurements, answer with JSON only. And the **job**: the goal and the scout's page. The lead answers with one JSON object. The validator of S32 checks it; if there are problems, they go back to the lead in the validator's own words, and the lead gets two chances to repair the plan. A plan that is still invalid after that is not run.

We ask for five plans, with five sample indexes, for the same job. The differences between them show how much a plan depends on the draw, which matters twice: for reproducibility, and for how many plans one should look at before choosing.

**In plain terms.** The lead gets the rules of the plan format and the fact sheet, writes a plan, and fixes it when the checker complains.

**For teams.** Feed validation errors back to the model verbatim and cap the number of repairs. Record every attempt, not only the one that passed: the failures tell you which part of your format is confusing.

#%% code
LEAD_JSON_SYSTEM = """You are the lead of a code audit, and you write the plan as one JSON object. You never read the code yourself: workers do, following your plan.

THE PLAN LANGUAGE
A plan has a title, a goal and one to six phases, run one after another. Each phase has a name, a kind and settings.
- kind "scan": workers read the code. The library is cut into shards of about shard_tokens tokens; one worker reads one shard through one lens, so a scan phase starts shards x lenses workers. Lenses: "general"; "boundaries" (comparisons, ranges, slices, indexes, empty inputs); "logic" (operators, conditions, argument order); "state" (starting values, updates, early returns, returned variables).
- kind "verify": skeptics check the findings so far, batch_size findings per call. Each batch goes to `skeptics` independent skeptics, and a finding is kept when `need` of them say it is real. With "evidence": true, each finding's failing call is run in a sandbox first and the skeptic sees the result.
- kind "report": one worker merges, ranks and summarises what is left. Exactly one report phase, and it must be last.
Settings: model (a role: worker, fast, judge, lead, lead_alt), shard_tokens (5000 to 200000), lenses, batch_size (1 to 8), skeptics (1 to 5), need, evidence, why (one sentence: why the phase is there).

COSTS
Billing is per call: every call costs its model's price, whatever its length. A scan phase costs shards x lenses calls. A verify phase costs batches x skeptics calls, and the number of batches depends on how many findings the scans report.

RULES
- Keep the expected cost under half of the budget for this job.
- Every file must be read by at least one scan worker.
- Use what was measured: shard sizes, findings per scan and latencies are in the summary.
- Answer with the JSON object only.

EXAMPLE OF THE FORMAT (not a recommendation)
{"title": "One quick pass", "goal": "...", "phases": [{"name": "Scan", "kind": "scan", "model": "worker", "shard_tokens": 40000, "lenses": ["general"], "why": "read everything once"}, {"name": "Report", "kind": "report", "model": "lead", "why": "summarise"}]}"""
print(f"[lead] the JSON-plan instruction: {len(LEAD_JSON_SYSTEM.split())} words, about {est_tokens(LEAD_JSON_SYSTEM)} tokens")

#%% md
**`Lead`** is a small class. It holds the lead's model and front door, and a record of everything the lead has read, which S39 compares with what one agent alone had to read. **`Lead.ask`** makes one call as the lead. All of the lead's calls go through the same front door and the same session budget as every run: the lead pays for its own thinking.

#%% code
class Lead:
    """The lead: reads the scout's page, writes and repairs plans, and later writes the memo."""

    def __init__(self, model="lead", llm=None):
        self.model, self.llm = MODELS.get(model, model), llm or FRONT_DOOR
        self.read = []                        # (what, tokens) for every call: what the lead has had to read

    def ask(self, messages, tag, sample=0, json_mode=False, max_tokens=8000):
        params = {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": max_tokens}
        if json_mode and "JSON mode" in CAN.get(self.model, ()):
            params["response_format"] = {"type": "json_object"}
        r = self.llm.chat(self.model, messages, tag=tag, role="lead", phase="planning", run_id="lead", sample=sample, **params)
        self.read.append((tag, sum(est_tokens(m["content"]) for m in messages)))
        return r

show_def(Lead)

#%% md
**`Lead.write_json_plan(job, page, sample)`** asks for a plan, validates it, and repairs it at most twice. It returns the plan, whether it is valid, and the problems found at every attempt.

#%% code
@method_of(Lead)
def write_json_plan(self, job, page, sample=0, repairs=2):
    messages = [{"role": "system", "content": LEAD_JSON_SYSTEM}, {"role": "user", "content": f"THE JOB\n{job}\n\n{page}"}]
    attempts = []
    for k in range(1 + repairs):
        r = self.ask(messages, f"lead:json#{sample}:try{k + 1}", sample, json_mode=True)
        plan = extract_json(r.text) if r.finish != "error" else None
        problems = validate_plan(plan) if plan is not None else ["the reply is not one JSON object"]
        attempts.append(problems)
        if not problems:
            return {"plan": plan, "valid": True, "tries": k + 1, "attempts": attempts}
        messages = messages + [{"role": "assistant", "content": r.text[:8000]},
                               {"role": "user", "content": "Your plan has these problems:\n- " + "\n- ".join(problems)
                                + "\nSend the whole corrected plan as one JSON object."}]
    return {"plan": plan, "valid": False, "tries": 1 + repairs, "attempts": attempts}

show_def(Lead.write_json_plan)

#%% md
**A scripted lead for smoke runs.** The stand-in writes one of five reasonable plans, chosen by the sample index, and shrinks it when the budget on the page is small. One of the five makes a mistake on its first attempt (a shard size outside the allowed range) and fixes it when told, so the repair path runs in every smoke build.

#%% code
@SCRIPTED.register
def _lead_json(model, messages, params):
    if "and you write the plan as one JSON object" not in messages[0]["content"][:200]:
        return None
    first = messages[1]["content"]
    budget = float((re.search(r"Budget for this job: ([0-9.]+)", first) or [0, "150"])[1])
    k = params.get("sample", 0) % 5
    lenses, size, skeptics, need, ev = [(list(LENSES), 1, 3, 2, True), (["general"], 2, 3, 2, True), (["boundaries", "logic"], 1, 2, 1, True),
                                        (list(LENSES), 1, 3, 2, False), (["general", "state"], 1, 1, 1, True)][k]
    if budget < 40:
        lenses, skeptics, need = ["general"], 1, 1
    plan = {"title": f"Audit plan {k + 1}", "goal": "Find the behaviour bugs and report them with evidence.",
            "phases": [{"name": "Scan", "kind": "scan", "model": "worker", "shard_tokens": SHARD_TOKENS * size, "lenses": lenses,
                        "why": "read every file"},
                       {"name": "Verify", "kind": "verify", "model": "judge", "batch_size": 6, "skeptics": skeptics, "need": need,
                        "evidence": ev, "why": "remove false alarms"},
                       {"name": "Report", "kind": "report", "model": "lead", "why": "merge and rank"}]}
    if k == 3 and not messages[-1]["content"].startswith("Your plan has these problems"):
        plan["phases"][0]["shard_tokens"] = 300_000
    return json.dumps(plan)

show_def(_lead_json)

#%% md
**Five plans for the same job.** The same instruction and the same page, with sample indexes 0 to 4. The table lists the decisions each plan made and what the validator said about each attempt.

#%% code
LEAD = Lead()
JOB = AUDIT_GOAL.format(files=len(WORK))
JSON_PLANS = [LEAD.write_json_plan(JOB, SCOUT_TEXT, sample=k) for k in range(5)]
rows = []
for k, a in enumerate(JSON_PLANS):
    p = a["plan"] or {"phases": []}
    sc = next((ph for ph in p["phases"] if ph.get("kind") == "scan"), {})
    vf = next((ph for ph in p["phases"] if ph.get("kind") == "verify"), {})
    rows.append({"sample": k, "tries": a["tries"], "valid": "yes" if a["valid"] else "no", "phases": len(p["phases"]),
                 "lenses": ", ".join(sc.get("lenses", ["general"])), "shard": sc.get("shard_tokens", SHARD_TOKENS) // 1000,
                 "skeptics": f"{vf.get('need', '-')} of {vf.get('skeptics', '-')}" if vf else "none",
                 "evidence": {True: "on", False: "off"}.get(vf.get("evidence"), "-"),
                 "workers": sum(plan_workers(p).values()) if a["valid"] else None})
table(rows, [("sample", "sample", "d"), ("tries", "tries", "d"), ("valid", "valid", ""), ("phases", "phases", "d"),
             ("lenses", "lenses", ""), ("shard", "shard k", "d"), ("skeptics", "keep if", ""), ("evidence", "evidence", ""),
             ("workers", "workers (est.)", "d")])
for k, a in enumerate(JSON_PLANS):
    for i, problems in enumerate(a["attempts"]):
        if problems:
            print(f"[repair] sample {k}, attempt {i + 1}: {problems[0][:120]}")

#%% code
# FIG  five plans the lead wrote for the same job, drawn from their data
valid_plans = [(k, a["plan"]) for k, a in enumerate(JSON_PLANS) if a["valid"]]
fig, axes = plt.subplots(len(valid_plans), 1, figsize=(10.4, 2.05 * len(valid_plans)))
for ax, (k, p) in zip(np.atleast_1d(axes), valid_plans):
    draw_plan(ax, p, compact_text=True)
    ax.text(-0.05, 0.5, f"sample {k}", transform=ax.transAxes, rotation=90, va="center", ha="right", fontsize=8.5, color=INK2)
n_distinct = len({json.dumps(p["phases"], sort_keys=True) for _, p in valid_plans})
finish(fig, "s34_five_plans", f"Five samples, {n_distinct} different plans: the lead's choices of lenses, shard size and skeptics vary",
       "each row is one plan the lead wrote for the same job and page; circles are workers")

#%% md
**Reading FIG {{figures.s34_five_plans}} (s34_five_plans).** Each row is one plan, drawn from its data exactly like the fixed plan in S32. The five samples produced {{lead_json.distinct}} different plans. They agree on the shape, scan then verify then report, and differ in the settings: how many lenses, how big the shards, how many skeptics and whether to show them evidence. {{lead_json.valid_first}} of 5 were valid at the first attempt and {{lead_json.valid_final}} of 5 after repair. The estimated size ranges from {{lead_json.workers_min}} to {{lead_json.workers_max}} workers. That spread is a property of asking a model, and it is why S38 measures plans over many samples instead of trusting one.

#%% md
**Running the lead's first plan.** Plan 0 is compiled and run like the fixed plan, with the sample offset of run 0. Where its settings coincide with the fixed plan's, its calls are the same requests and are answered from the ledger for free, which is the ledger working as designed: equal questions cost once.

#%% code
D_JSON = next(a["plan"] for a in JSON_PLANS if a["valid"])
print(compile_plan(D_JSON))
d_run, d_kit, d_result, D_JSON_OUT = run_plan(D_JSON, "d-json-0", number=0)
hits = sum(r.cached for t in d_run.threads for r in t.replies)
print(f"\n[lead plan] {d_run.status}: recall {D_JSON_OUT['recall']:.2f}, precision {(D_JSON_OUT['precision'] or 0):.2f}, "
      f"{D_JSON_OUT['calls']} calls of which {hits} came from the ledger, {D_JSON_OUT['magicubes']:.1f} Magicubes paid")
table([{"plan": "C, the fixed plan (mean of 3)", "recall": load_exp("fixed")["recall_mean"], "precision": load_exp("fixed")["precision_mean"],
        "magicubes": load_exp("fixed")["magicubes_mean"]},
       {"plan": "the lead's JSON plan 0", "recall": D_JSON_OUT["recall"], "precision": D_JSON_OUT["precision"], "magicubes": D_JSON_OUT["magicubes"]}],
      [("plan", "plan", ""), ("recall", "recall", ".2f"), ("precision", "precision", ".2f"), ("magicubes", "Magicubes", ".1f")])

#%% code
workers = [r["workers"] for r in rows if r["workers"] is not None]
save_exp("lead_json", {"rows": rows, "distinct": n_distinct, "valid_first": sum(a["tries"] == 1 and a["valid"] for a in JSON_PLANS),
                       "valid_final": sum(a["valid"] for a in JSON_PLANS), "workers_min": min(workers), "workers_max": max(workers),
                       "run": {k: v for k, v in D_JSON_OUT.items() if k != "found_ids"}, "ledger_hits": hits,
                       "instruction_tokens": est_tokens(LEAD_JSON_SYSTEM)})
results = []
expect("at least four of the five plans are valid after repair", sum(a["valid"] for a in JSON_PLANS) >= 4)
expect("every invalid attempt came with at least one readable problem", all(p for a in JSON_PLANS for p in a["attempts"][:-1]))
expect("the lead's plan ran to completion", d_run.status == "completed")
expect("the lead's calls were charged to the planning phase of the ledger",
       len(FRONT_DOOR.ledger.query("SELECT key FROM calls WHERE role = 'lead' AND phase = 'planning'")) >= 5)
