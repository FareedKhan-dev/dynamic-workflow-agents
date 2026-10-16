#%% md
### What one agent alone did

The next two figures are built from the turn records. The first follows each run's findings and its coverage turn by turn. The second follows the context of one run: how it grows with every file read, and what each compaction does to it.

#%% code
# FIG  findings and coverage, turn by turn, for the three solo runs
key_hits = lambda e, upto: match([f for f in e.findings[:upto]]).tp
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6))
ax = axes[0]
for k, (e, colour) in enumerate(zip(SOLO, [C1, C7, C2])):
    xs = [t.n for t in e.turns]
    real = [key_hits(e, t.reported) for t in e.turns]
    ax.plot(xs, real, color=colour, lw=2, label=f"run {k + 1}: real bugs")
    ax.plot(xs, [t.reported for t in e.turns], color=colour, lw=1, ls=":", label=f"run {k + 1}: reported")
ax.axhline(len(ANSWER_KEY), color=C8, ls="--", lw=1)
ax.text(1, len(ANSWER_KEY) - 4, f" {len(ANSWER_KEY)} planted", color=C8, fontsize=8)
ax.set_xlabel("turn")
ax.set_ylabel("bugs")
ax.legend(fontsize=7, ncol=2)
panel(ax, "solid: matched to a planted bug; dotted: everything reported")
ax = axes[1]
for k, (e, colour) in enumerate(zip(SOLO, [C1, C7, C2])):
    ax.plot([t.n for t in e.turns], [t.files_read / len(CORPUS) for t in e.turns], color=colour, lw=2, label=f"run {k + 1}")
ax.axhline(1, color=MUTED, ls="--", lw=1)
ax.set_ylim(0, 1.05)
ax.set_xlabel("turn")
ax.set_ylabel("share of files read")
ax.legend(fontsize=8)
panel(ax, "coverage of the corpus")
best_solo = max(SOLO_ROWS, key=lambda r: r["recall"])
finish(fig, "s17_solo_progress", f"One agent alone found {min(r['found'] for r in SOLO_ROWS)} to {max(r['found'] for r in SOLO_ROWS)} "
       f"of {len(ANSWER_KEY)} bugs in {SOLO_TURNS} turns",
       f"it read at most {max(r['coverage'] for r in SOLO_ROWS):.0%} of the files; three independent runs of the worker model")

#%% md
**Reading FIG {{figures.s17_solo_progress}} (s17_solo_progress).** The left panel counts bugs as each run goes. Solid lines are findings that match a planted bug; dotted lines are everything the agent reported, true or not. The three runs found {{solo.found_min}}, {{solo.found_mid}} and {{solo.found_max}} of the {{answer_key.bugs}} planted bugs. The right panel shows why the totals stay low whatever the agent's skill: after {{solo.turns}} turns the runs had read between {{solo.coverage_min|.0%}} and {{solo.coverage_max|.0%}} of the files. A bug in a file nobody opened cannot be found. The spread between runs is the other lesson: the same agent, given the same job three times, chose different files and found different bugs.

#%% code
# FIG  the context of one run: growth, compaction, and the time each turn took
e = SOLO[0]
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.4))
ax = axes[0]
ax.plot([t.n for t in e.turns], [t.context_tokens for t in e.turns], color=C1, lw=1.6)
ax.axhline(COMPACT_AT, color=C8, ls="--", lw=1)
ax.text(1, COMPACT_AT * 1.02, f" compaction threshold {COMPACT_AT // 1000}k", color=C8, fontsize=8)
ax.set_xlabel("turn")
ax.set_ylabel("tokens sent to the model")
panel(ax, f"run 1: {e.compactions} compactions")
ax = axes[1]
secs = [t.seconds for t in e.turns]
ax.scatter([t.context_tokens / 1000 for t in e.turns], secs, s=10, color=C1, alpha=0.7)
ax.set_xlabel("context, thousands of tokens")
ax.set_ylabel("seconds for the turn")
ctx_ = [t.context_tokens for t in e.turns]
corr = float(np.corrcoef(ctx_, secs)[0, 1]) if len(secs) > 3 and np.std(secs) > 0 and np.std(ctx_) > 0 else 0.0
panel(ax, f"correlation {corr:.2f}: " + ("a bigger context is a slower turn" if corr > 0.2 else "turn time against context size"))
finish(fig, "s17_solo_context", f"The context filled up {e.compactions} times in one run, and each refill erased the detail of what was read",
       f"median turn {np.median(secs):.1f} s; total model time {sum(secs) / 60:.0f} minutes for {len(e.turns)} turns")

#%% md
**Reading FIG {{figures.s17_solo_context}} (s17_solo_context).** The left panel is the sawtooth every long-running agent lives with. The context grows by a few thousand tokens with every file read, reaches the threshold, and falls back when the host compacts it. Run 1 compacted {{solo.compactions_run1}} times. After each compaction the agent knows *which* files it read but no longer sees *what* was in them, so a bug that only shows when two files are compared is out of reach unless both are read again. The right panel shows the other cost of a long context: turns with more context take longer, so the agent slows down as it works. Both problems come from the same cause, one context doing everything, which is the cause a team of workers with fresh contexts is meant to remove.

#%% md
## S18 - Baseline B: a lead who reads every result

**Theory.** The second baseline is a team, but an old-fashioned one. A **lead** model plans nothing up front. It hands the codebase out one shard at a time to a **helper**, the same scan worker as in S13. It reads each helper's report as it arrives, decides which shard to send next, and at the end keeps the findings it believes. This is how many multi-agent systems work today: subagents are called like tools, one after another, and the lead stays in the loop for every result.

It fixes the coverage problem, because every shard gets a fresh helper with a fresh context. It keeps two others. The work is **sequential**: one helper runs at a time, so the time is the sum of all helper times plus the lead's own turns. And the lead's context grows with **every** report, so the lead pays in time and attention for results it only needs at the end.

**In plain terms.** One boss, many helpers, but the boss waits for each helper to finish and reads every report before sending the next one out.

**For teams.** If a subagent is called like a function, the caller waits like a function. Count that waiting before you call a design parallel.

#%% code
LEAD_SEQ_SYSTEM = """You lead a code audit, but you cannot read code yourself. You have helpers: a helper reviews one shard of the codebase and reports the behaviour bugs it finds, each with an id such as F7.

Each turn, send exactly one JSON object:
- {{"tool": "delegate", "args": {{"shard": <number>}}}} sends one shard to a helper; its findings come back as the next message
- {{"tool": "done", "args": {{"keep": ["F1", "F7"]}}}} ends the audit, listing the ids of the findings you believe are real bugs

There are {n} shards, numbered 0 to {last}. Their folders:
{listing}

Review every shard if you can, one at a time. At the end keep only findings you believe, and drop duplicates."""


def lead_with_helpers(label="sequential", sample=0):
    """A lead that delegates one shard at a time and reads every result; returns an Episode plus timings."""
    shards = pack(sorted(CORPUS), SHARD_TOKENS)
    listing = "\n".join(f"{i}: " + ", ".join(sorted({p.split('/')[0] for p in s})) for i, s in enumerate(shards))
    messages = [{"role": "system", "content": LEAD_SEQ_SYSTEM.format(n=len(shards), last=len(shards) - 1, listing=listing)},
                {"role": "user", "content": "Start the audit."}]
    params = {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": 6000}
    if "JSON mode" in CAN.get(MODELS["lead"], ()):
        params["response_format"] = {"type": "json_object"}
    by_id, kept, turns, timeline, done = {}, None, [], [], set()
    clock = 0.0
    for n in range(1, len(shards) + 6):
        ctx = sum(est_tokens(m["content"]) for m in messages)
        r = FRONT_DOOR.chat(MODELS["lead"], messages, tag=f"{label}:lead{n}", role="lead", phase="sequential",
                            run_id=label, sample=sample, **params)
        timeline.append(("lead", clock, clock + r.seconds))
        clock += r.seconds
        obj = extract_json(r.text) or {}
        tool, args = obj.get("tool"), obj.get("args") or {}
        if tool == "delegate" and str(args.get("shard", "")).lstrip("-").isdigit() and 0 <= int(args["shard"]) < len(shards):
            i = int(args["shard"])
            fs, hr = scan(shards[i], sample=sample, tag=f"{label}:helper{i}", phase="sequential", run_id=label)
            timeline.append(("helper", clock, clock + hr.seconds))
            clock += hr.seconds
            done.add(i)
            lines = []
            for f in fs:
                fid = f"F{len(by_id) + 1}"
                by_id[fid] = f
                lines.append(f"{fid}: {f.file}:{f.line} in {f.function}: {f.claim}")
            out = f"helper on shard {i} found {len(fs)}:\n" + "\n".join(lines)
        elif tool == "done":
            kept = [by_id[k] for k in args.get("keep", []) if k in by_id]
            turns.append(Turn(n, "done", "", True, ctx, r.prompt_tokens, r.completion_tokens, r.seconds, r.cached, len(by_id), len(done)))
            break
        else:
            out = "error: send delegate with a shard number, or done with the ids to keep"
        turns.append(Turn(n, tool or "none", str(args.get("shard", "")), tool == "delegate", ctx, r.prompt_tokens,
                          r.completion_tokens, r.seconds, r.cached, len(by_id), len(done)))
        messages += [{"role": "assistant", "content": r.text[:2000]}, {"role": "user", "content": f"<result turn={n}>\n{out}\n</result>"}]
    stop = "done" if kept is not None else "turn limit"
    findings = kept if kept is not None else list(by_id.values())
    return Episode(label, findings, turns, done, stop, 0, clock), list(by_id.values()), timeline, len(shards)

show_def(lead_with_helpers)


@SCRIPTED.register
def _lead_seq(model, messages, params):
    if not messages[0]["content"].startswith("You lead a code audit, but you cannot read code yourself"):
        return None
    n = int(re.search(r"There are (\d+) shards", messages[0]["content"]).group(1))
    sent = sum(1 for m in messages if m["role"] == "assistant" and '"delegate"' in m["content"])
    if sent < n:
        return json.dumps({"tool": "delegate", "args": {"shard": sent}})
    ids = re.findall(r"^(F\d+):", "\n".join(m["content"] for m in messages if m["role"] == "user"), re.M)
    return json.dumps({"tool": "done", "args": {"keep": ids}})

show_def(_lead_seq)

#%% code
SEQ, SEQ_ALL, SEQ_TIMELINE, SEQ_SHARDS = lead_with_helpers("sequential")
SEQ_SCORE, SEQ_ALL_SCORE = match(SEQ.findings), match(SEQ_ALL)
helper_s = sum(b - a for k, a, b in SEQ_TIMELINE if k == "helper")
lead_s = sum(b - a for k, a, b in SEQ_TIMELINE if k == "lead")
print(f"[sequential] {len(SEQ.files_read)} of {SEQ_SHARDS} shards reviewed, stopped: {SEQ.stop}; lead turns {len(SEQ.turns)}")
print(f"[sequential] helpers reported {len(SEQ_ALL)} findings ({SEQ_ALL_SCORE.tp} planted bugs); the lead kept {len(SEQ.findings)} "
      f"({SEQ_SCORE.tp} planted bugs)")
print(f"[sequential] recall {SEQ_SCORE.recall:.2f}, precision {SEQ_SCORE.precision if SEQ_SCORE.precision is not None else float('nan'):.2f}; "
      f"time {SEQ.seconds / 60:.0f} min ({helper_s / 60:.0f} min helpers, {lead_s / 60:.0f} min lead), one after another")
print(f"[sequential] the lead's context grew from {SEQ.turns[0].context_tokens:,} to {SEQ.turns[-1].context_tokens:,} tokens; "
      f"cost {cost_of('sequential')['magicubes']:.1f} Magicubes")

#%% code
# FIG  the sequential team: one helper at a time, and a lead that reads everything
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.3), gridspec_kw={"width_ratios": [1.5, 1]})
ax = axes[0]
for kind, a, b in SEQ_TIMELINE:
    ax.barh(0 if kind == "helper" else 1, (b - a) / 60, left=a / 60, color=C1 if kind == "helper" else C7, height=0.6)
ax.set_yticks([0, 1], ["helpers", "lead"])
ax.set_xlabel("minutes since the start")
panel(ax, "never more than one thing happening at a time")
ax = axes[1]
ax.plot([t.n for t in SEQ.turns], [t.context_tokens for t in SEQ.turns], color=C7, lw=2)
ax.set_xlabel("lead turn")
ax.set_ylabel("lead context, tokens")
panel(ax, "the lead's context grows with every report")
finish(fig, "s18_sequential", f"The sequential team covered every shard but took {SEQ.seconds / 60:.0f} minutes end to end",
       f"recall {SEQ_SCORE.recall:.2f}; the lead kept {len(SEQ.findings)} of {len(SEQ_ALL)} helper findings")

#%% md
**Reading FIG {{figures.s18_sequential}} (s18_sequential).** The left panel is the timeline of the whole audit. Blue bars are helpers and violet bars are the lead, and they never overlap: each helper waits for the lead to send it, and the lead waits for each helper to come back. The audit took {{sequential.minutes|.0f}} minutes, almost all of it helper time that could have happened at once. The right panel shows the lead's context growing with every report it has to read, although it only needs the reports at the very end. The helpers found {{sequential.all_found}} planted bugs between them, and the lead kept {{sequential.kept_found}}. Any gap between those two numbers is bugs a helper found and the lead threw away.

#%% md
## S19 - What the baselines teach

Three limits showed up, and each points at a feature of the system the next Parts build:

| limit | where it showed | what removes it |
|---|---|---|
| **coverage** | one agent alone read at most {{solo.coverage_max|.0%}} of the files | split the job into shards and give every shard a worker (Part IV) |
| **memory** | every compaction erased the detail of what was read | give each worker a fresh context of the size S13 measured (Part IV) |
| **waiting** | the sequential team spent {{sequential.minutes|.0f}} minutes, one helper at a time | run the workers of a phase in parallel, in the background (Part IV) |
| **the lead in the loop** | the lead read every report as it arrived | let the lead write the plan once and get back one combined result (Part V) |

#%% code
# FIG  the two baselines side by side
fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.3))
labels = [f"solo {k + 1}" for k in range(RUNS)] + ["sequential"]
recalls = [r["recall"] for r in SOLO_ROWS] + [SEQ_SCORE.recall]
precs = [r["precision"] or 0 for r in SOLO_ROWS] + [SEQ_SCORE.precision or 0]
mcs = [r["magicubes"] for r in SOLO_ROWS] + [cost_of("sequential")["magicubes"]]
mins = [r["minutes"] for r in SOLO_ROWS] + [SEQ.seconds / 60]
cols = [MUTED] * RUNS + [C7]
for ax, vals, name, fmt in ((axes[0], recalls, "recall", "{:.2f}"), (axes[1], precs, "precision", "{:.2f}"), (axes[2], mins, "minutes", "{:.0f}")):
    ax.bar(range(len(labels)), vals, color=cols, width=0.6)
    for i, v in enumerate(vals):
        ax.text(i, v, fmt.format(v), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(range(len(labels)), labels, fontsize=8, rotation=20)
    panel(ax, name)
axes[0].set_ylim(0, 1.05)
axes[1].set_ylim(0, 1.05)
finish(fig, "s19_baselines", "The numbers to beat: recall, precision and time of the two baselines",
       f"solo runs cost {np.mean(mcs[:RUNS]):.1f} Magicubes each; the sequential team {mcs[-1]:.1f}")

#%% md
**Reading FIG {{figures.s19_baselines}} (s19_baselines).** These are the numbers every later design is measured against. One agent alone reached a recall of {{solo.recall_mean|.2f}} on average. The sequential team covered the whole corpus and reached {{sequential.recall|.2f}}, but took {{sequential.minutes|.0f}} minutes. Part IV builds the runtime that runs the same kind of workers in parallel. Part V lets a lead write the plan for them once instead of supervising every step.

#%% code
sfound = sorted(r["found"] for r in SOLO_ROWS)
save_exp("solo", {"runs": SOLO_ROWS, "turns": SOLO_TURNS, "found_min": sfound[0], "found_mid": sfound[len(sfound) // 2],
                  "found_max": sfound[-1], "coverage_min": min(r["coverage"] for r in SOLO_ROWS),
                  "coverage_max": max(r["coverage"] for r in SOLO_ROWS), "recall_mean": float(np.mean([r["recall"] for r in SOLO_ROWS])),
                  "precision_mean": float(np.mean([r["precision"] or 0 for r in SOLO_ROWS])),
                  "compactions_run1": SOLO[0].compactions, "magicubes_mean": float(np.mean(mcs[:RUNS])),
                  "minutes_mean": float(np.mean(mins[:RUNS])), "found_ids": [s.found for s in SOLO_SCORES]})
save_exp("sequential", {"shards": SEQ_SHARDS, "reviewed": len(SEQ.files_read), "stop": SEQ.stop, "lead_turns": len(SEQ.turns),
                        "all_findings": len(SEQ_ALL), "all_found": SEQ_ALL_SCORE.tp, "kept": len(SEQ.findings),
                        "kept_found": SEQ_SCORE.tp, "recall": SEQ_SCORE.recall, "precision": SEQ_SCORE.precision,
                        "minutes": SEQ.seconds / 60, "helper_minutes": helper_s / 60, "lead_minutes": lead_s / 60,
                        "magicubes": cost_of("sequential")["magicubes"], "lead_context_last": SEQ.turns[-1].context_tokens})
results = []
expect("each solo run stopped for a recorded reason", all(e.stop for e in SOLO))
expect("no solo run read a file outside the audited tree", all(p in CORPUS for e in SOLO for p in e.files_read))
expect("the sequential lead reviewed at least half the shards", len(SEQ.files_read) >= SEQ_SHARDS / 2)

#%% md
**Part III recap.** We gave the job to one agent, then to a team that works one helper at a time, and measured both:

- tools that cannot leave the audited tree, and a two-layer sandbox that ran honest calls and stopped every hostile one;
- an agent loop with turn records and a compaction the host writes itself;
- one agent alone: {{solo.found_min}} to {{solo.found_max}} of {{answer_key.bugs}} bugs in {{solo.turns}} turns, limited first by how much it could read;
- a sequential team: full coverage, but {{sequential.minutes|.0f}} minutes of waiting and a lead that reads every report.

**Try it yourself.**

1. Raise `COMPACT_AT` to 200,000 and rerun one solo audit. Do fewer compactions change what it finds, or only how slow its turns are?
2. Give the solo agent a hint in its task: "start with the folders sorts, searches and graphs". How does its recall change, and what does that say about how much of the job is choosing where to look?
3. In `lead_with_helpers`, send two shards per turn instead of one. Which of the four limits in the S19 table does that address, and which does it not?
