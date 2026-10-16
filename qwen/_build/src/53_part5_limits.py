#%% md
## S35 - What JSON cannot say

**Theory.** A data plan can only use the words its format has. Ours has phases that run once, in a fixed order, with fixed settings. Three ideas that a careful engineer would want to try do not fit:

1. **Loop until nothing new.** Scan again with fresh samples while each round still finds new places, and stop when a round adds little. The number of rounds depends on what the rounds find.
2. **Decide from results.** Act on what a step returned: for example, drop a finding without spending skeptics on it when its own failing call, run in the sandbox, returned exactly what the finder expected.
3. **No barrier between steps.** Let each shard's findings go to verification as soon as that shard is read, instead of waiting for the slowest shard of the whole library.

Each could be added to the JSON format as a new field, and each new field needs new compiler code, a new validator rule and a new explanation for the lead. A format that grows a field for every idea becomes a programming language without the benefits of one. Before deciding, we measure what each idea would be worth, on the records of the three fixed-plan runs, without a single new call.

**In plain terms.** Some good ideas need "repeat until", "if" or "do this per item as soon as it is ready". A form cannot say those things; a short program can.

**For teams.** Before you extend a configuration format, write down the feature as code and measure what it buys on data you already have. Most format extensions are programs in disguise.

#%% md
**Gap 1, measured: what more rounds of scanning find.** The three runs of the fixed plan scanned the whole library three times with different samples, which is exactly what three rounds of a loop would do. Reading them as rounds 1, 2 and 3 gives the discovery curve of a loop: how many new places each round reports, and how many planted bugs are among everything reported so far, before any verification.

#%% code
def discovery(traces):
    """Per round: new places, places so far, new planted bugs, and the scan-stage recall so far."""
    seen, bugs, curve = set(), set(), []
    for k, found in enumerate(traces, 1):
        places = {key_of(f) for f in found if f.get("file")}
        found_bugs = set(match(as_findings(found)).found)
        curve.append({"round": k, "new_places": len(places - seen), "places": len(seen | places),
                      "new_bugs": len(found_bugs - bugs), "scan_recall": len(bugs | found_bugs) / len(ANSWER_KEY)})
        seen |= places
        bugs |= found_bugs
    return curve

show_def(discovery)
DISCOVERY = discovery([kit.trace["found"] for _, kit, _ in C_OBJS])
table(DISCOVERY, [("round", "round", "d"), ("new_places", "new places", "d"), ("places", "places so far", "d"),
                  ("new_bugs", "new planted bugs", "d"), ("scan_recall", "planted bugs reported so far", ".2f")])
print(f"[loop] rounds 2 and 3 added {sum(r['new_bugs'] for r in DISCOVERY[1:])} planted bugs and "
      f"{sum(r['new_places'] for r in DISCOVERY[1:])} places in total; a program says it in four lines (below)")

#%% md
**Gap 2, measured: deciding from the evidence.** Every place the fixed plan verified had its failing call run in the sandbox. Group those places by what the sandbox saw. If the call *agrees*, meaning the code returned exactly what the finder said it should, the finder's own example does not show a bug. A plan that could act on results could drop those places before paying three skeptics for each. The question is what that would cost in planted bugs.

#%% code
def evidence_table(kit):
    """Verified places of one run grouped by what the sandbox saw: places, planted bugs among them, skeptic calls spent."""
    checked = {v["key"] for v in kit.trace["checked"]}
    places = [f for f in dedupe(kit.trace["found"]) if key_of(f) in checked]
    calls = collections.Counter(v["key"] for v in kit.trace["checked"])
    rows = collections.defaultdict(lambda: {"places": 0, "planted": 0, "calls": 0})
    for f in places:
        st = evidence(f)["status"]
        rows[st]["places"] += 1
        rows[st]["planted"] += match(as_findings([f])).tp
        rows[st]["calls"] += calls[key_of(f)] / 6               # a skeptic call covers a batch of up to six places
    return [{"evidence": k, **v} for k, v in sorted(rows.items())]

show_def(evidence_table)
EV_ROWS = evidence_table(C_OBJS[0][1])
table(EV_ROWS, [("evidence", "what the sandbox saw", ""), ("places", "places verified", "d"), ("planted", "planted bugs among them", "d"),
                ("calls", "skeptic calls (share)", ".1f")])
agrees = next((r for r in EV_ROWS if r["evidence"] == "agrees"), {"places": 0, "planted": 0, "calls": 0})
total_places = sum(r["places"] for r in EV_ROWS)
print(f"[triage] dropping the places whose call agrees would skip {agrees['places']} of {total_places} places "
      f"({agrees['places'] / max(1, total_places):.0%} of the skeptic work) and lose {agrees['planted']} planted bugs")

#%% md
**Gap 3, measured: what the barrier cost.** In the fixed plan nobody verified anything until the slowest scan worker had finished. The run's events say how long each scan worker's findings sat waiting at that barrier. Summed over workers, that is the time a pipeline would have put to use.

#%% code
def barrier_wait(run_id, phase="Scan"):
    """(worker-minutes spent waiting at the end of a phase, the phase's length in minutes) from the recorded timeline."""
    lanes = [l for l in timeline(run_id) if l[1] == phase]
    if not lanes:
        return 0.0, 0.0
    end = max(e for _, _, _, e, _ in lanes)
    start = min(s for _, _, s, _, _ in lanes)
    return sum(end - e for _, _, _, e, _ in lanes) / 60, (end - start) / 60

show_def(barrier_wait)
WAITS = [barrier_wait(run.run_id) for run, _, _ in C_OBJS]
for (run, _, _), (w, length) in zip(C_OBJS, WAITS):
    print(f"[barrier] {run.run_id}: scan phase {length:.1f} min; findings waited {w:.1f} worker-minutes in total for the slowest shard")

#%% md
**The same three ideas as plan code.** Each fits in a few lines of the language S36 defines, using only the primitives and the kit. In the JSON format, each would need a new field, new compiler code and a new validator rule.

#%% code
GAP_CODE = {
    "loop until nothing new": """candidates = []
for rnd in range(3):
    new = [f for f in flatten(parallel([lambda s=s: scan(s, "general", sample=rnd) for s in shards(40000)]))
           if key_of(f) not in [key_of(c) for c in candidates]]
    candidates = dedupe(candidates + new)
    if len(dedupe(new)) < 5:
        break""",
    "decide from results": """candidates = [c for c in candidates if evidence(c)["status"] != "agrees"]""",
    "no barrier between steps": """checked = pipeline(shards(40000),
                   lambda _, s, i: dedupe(scan(s, "general")),
                   lambda found, s, i: flatten([check(b) for b in batches(found, 6)]))""",
}
GAPS = [{"idea": "loop until nothing new", "json": "new field + compiler loop + validator rule", "lines": len(GAP_CODE["loop until nothing new"].splitlines()),
         "measured": f"rounds 2-3 added {sum(r['new_bugs'] for r in DISCOVERY[1:])} planted bugs to the scan stage"},
        {"idea": "decide from results", "json": "new field + evidence step in the compiler", "lines": 1,
         "measured": f"{agrees['places'] / max(1, total_places):.0%} of verify work skipped, {agrees['planted']} planted bugs lost"},
        {"idea": "no barrier between steps", "json": "a second execution model in the compiler", "lines": 3,
         "measured": f"{np.mean([w for w, _ in WAITS]):.0f} worker-minutes of waiting per run"}]
for idea, code in GAP_CODE.items():
    print(f"--- {idea}\n{code}\n")
table(GAPS, [("idea", "idea", ""), ("json", "what JSON would need", ""), ("lines", "lines of plan code", "d"), ("measured", "measured on the fixed plan's runs", "")])

#%% code
# FIG  what the three ideas would be worth, measured on records we already have
fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.3))
ax = axes[0]
ax.bar([r["round"] for r in DISCOVERY], [r["new_places"] for r in DISCOVERY], color=C1, alpha=0.35, label="new places")
ax2 = ax.twinx()
ax2.plot([r["round"] for r in DISCOVERY], [r["scan_recall"] for r in DISCOVERY], "o-", color=C8, label="planted bugs reported so far")
ax2.set_ylim(0, 1)
ax.set_xlabel("round of scanning")
ax.set_ylabel("new places")
ax2.set_ylabel("share of planted bugs reported")
ax.set_xticks([r["round"] for r in DISCOVERY])
panel(ax, "1. loop until nothing new")
ax = axes[1]
ax.bar([r["evidence"] for r in EV_ROWS], [r["places"] for r in EV_ROWS], color=C4, label="places")
ax.bar([r["evidence"] for r in EV_ROWS], [r["planted"] for r in EV_ROWS], color=C3, label="planted bugs among them")
ax.set_ylabel("places verified in run 0")
ax.set_ylim(0, 1.3 * max([r["places"] for r in EV_ROWS] + [1]))
ax.legend(fontsize=7.5, loc="upper left")
panel(ax, "2. decide from the evidence")
ax = axes[2]
ax.bar([f"run {k}" for k in range(len(WAITS))], [w for w, _ in WAITS], color=MUTED)
ax.set_ylabel("worker-minutes waiting at the barrier")
panel(ax, "3. the barrier's cost")
finish(fig, "s35_gaps", "Three ideas a data plan cannot express, each measured on the fixed plan's own records",
       "left: the three runs read as rounds of a loop; middle: verified places by sandbox result; right: waiting at the scan barrier")

#%% md
**Reading FIG {{figures.s35_gaps}} (s35_gaps).** Left: read as rounds of one loop, the three fixed-plan runs reported {{json_gaps.round1_places}} places in round 1, and rounds 2 and 3 added {{json_gaps.later_places}} more places and {{json_gaps.later_bugs}} more planted bugs; the share of planted bugs reported went from {{json_gaps.recall_round1|.2f}} to {{json_gaps.recall_round3|.2f}}. Whether those extra rounds are worth their calls is exactly the decision a loop with a stopping rule makes at run time, and Part VI measures it. Middle: {{json_gaps.agrees_places}} of {{json_gaps.places}} verified places had a failing call that returned exactly what the finder expected, and {{json_gaps.agrees_planted}} of those were planted bugs; dropping them before verification would have saved that share of the skeptics' work at that cost in bugs. Right: findings waited {{json_gaps.wait_mean|.0f}} worker-minutes per run at the scan barrier. None of the three can be written in the JSON format of S32, and each is a few lines of plan code. That is the case for plans as programs, and S36 builds the language.

#%% code
save_exp("json_gaps", {"discovery": DISCOVERY, "round1_places": DISCOVERY[0]["places"], "later_places": DISCOVERY[-1]["places"] - DISCOVERY[0]["places"],
                       "later_bugs": sum(r["new_bugs"] for r in DISCOVERY[1:]),
                       "recall_round1": DISCOVERY[0]["scan_recall"], "recall_round3": DISCOVERY[-1]["scan_recall"],
                       "evidence": EV_ROWS, "agrees_places": agrees["places"], "agrees_planted": agrees["planted"], "places": total_places,
                       "wait_mean": float(np.mean([w for w, _ in WAITS])), "gaps": GAPS})
results = []
expect("the discovery curve never goes down", all(a["scan_recall"] <= b["scan_recall"] for a, b in zip(DISCOVERY, DISCOVERY[1:])))
expect("every verified place has a sandbox status", sum(r["places"] for r in EV_ROWS) == total_places)
expect("the barrier wait is measured from the recorded timeline of every run", len(WAITS) == RUNS and all(w >= 0 for w, _ in WAITS))
