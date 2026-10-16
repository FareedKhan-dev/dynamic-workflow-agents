#%% md
## S55 - The ablation ledger

**Theory.** An **ablation** removes one feature and measures what changes. Part VI already made every measurement this needs, mostly as pairs: the same places judged with and without evidence, the same shards read with three lenses and with three general readings. This section turns each pair into a number with an interval and a verdict. The rule was fixed in S50's spirit before looking:

- **KEPT** if removing the feature measurably hurts its target metric: the 95% interval of the change excludes zero, in the bad direction;
- **HARMFUL** if removing it measurably helps;
- **NEUTRAL** otherwise. NEUTRAL does not mean useless; it means these runs cannot tell.

Intervals come from a **paired bootstrap**: the units that both arms share (planted bugs, or checked places) are resampled together, so the noise that the two arms have in common cancels.

**In plain terms.** For each feature: take it away, see how much worse (or better) things get, and only call it a winner if the difference is bigger than the noise.

**For teams.** Keep a ledger like this for every switch in your pipeline, and re-run it when the model changes. A feature that was KEPT with one model can be NEUTRAL with the next.

#%% code
def paired_boot(units, metric, n=2000, seed=SEED):
    """(estimate, low, high): metric(resampled units), with the 95% percentile interval over n resamples."""
    rng_ = np.random.default_rng(seed)
    units = list(units)
    est = metric(units)
    draws = [metric([units[i] for i in rng_.integers(0, len(units), len(units))]) for _ in range(n)]
    return float(est), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def verdict_of(est, lo, hi, bad="negative"):
    """KEPT, HARMFUL or NEUTRAL for the change caused by removing a feature, whose bad direction is `bad`."""
    if bad == "negative":
        return "KEPT" if hi < 0 else "HARMFUL" if lo > 0 else "NEUTRAL"
    return "KEPT" if lo > 0 else "HARMFUL" if hi < 0 else "NEUTRAL"

show_def(paired_boot, verdict_of)
print(f"[boot] mean of 1..10 resampled: {paired_boot(range(1, 11), np.mean)}")
print(f"[verdict] change -0.05 (-0.08 to -0.02) when removed: {verdict_of(-0.05, -0.08, -0.02)}; "
      f"+0.01 (-0.02 to +0.04): {verdict_of(0.01, -0.02, 0.04)}")

#%% md
**The measurements, one row per feature.** Each metric function receives resampled units and returns *metric without the feature minus metric with it*, so a negative number means the feature helped.

#%% code
BUG_IDS = [b["id"] for b in ANSWER_KEY]
lens_sets = {"with": arms["three lenses"], "without": arms["general x3"]}
round_sets = {"with": set(match(as_findings(C_OBJS[0][1].trace["found"] + C_OBJS[1][1].trace["found"])).found),
              "without": set(match(as_findings(C_OBJS[0][1].trace["found"])).found)}


def recall_change(sets):
    return lambda ids: (sum(i in sets["without"] for i in ids) - sum(i in sets["with"] for i in ids)) / len(ids)


def rows_by_place(rows):
    out = collections.defaultdict(list)
    for r in rows:
        out[r["key"]].append(r)
    return out


def accuracy_change(with_rows, without_rows):
    w, wo = rows_by_place(with_rows), rows_by_place(without_rows)
    return lambda keys: accuracy([r for k in keys for r in wo[k]])["accuracy"] - accuracy([r for k in keys for r in w[k]])["accuracy"]


def kept_precision(k, need):
    """Precision of the places kept by `need` of the first `k` skeptics, as a function of resampled places."""
    def f(keys):
        kept = [key for key in keys if (sum(real_votes[key][:k]) >= need if k else True)]
        return sum(C0_TRUTH[key] for key in kept) / max(1, len(kept))
    return f

show_def(recall_change, rows_by_place, accuracy_change, kept_precision)
places = sorted(C0_TRUTH)
ABLATION = [
    {"feature": "three lenses (vs three general readings)", "metric": "scan-stage recall",
     **dict(zip(("est", "lo", "hi"), paired_boot(BUG_IDS, recall_change(lens_sets))))},
    {"feature": "a second round of scanning", "metric": "scan-stage recall",
     **dict(zip(("est", "lo", "hi"), paired_boot(BUG_IDS, recall_change(round_sets))))},
    {"feature": "executable evidence", "metric": "skeptic accuracy",
     **dict(zip(("est", "lo", "hi"), paired_boot(places, accuracy_change(WITH_EV, WITHOUT_EV))))},
    {"feature": "verification, 2 of 3 skeptics", "metric": "precision",
     **dict(zip(("est", "lo", "hi"), paired_boot(places, lambda ks: kept_precision(0, 0)(ks) - kept_precision(3, 2)(ks))))},
    {"feature": "three skeptics (vs one)", "metric": "precision",
     **dict(zip(("est", "lo", "hi"), paired_boot(places, lambda ks: kept_precision(1, 1)(ks) - kept_precision(3, 2)(ks))))},
    {"feature": "a judge from another generation", "metric": "skeptic accuracy",
     **dict(zip(("est", "lo", "hi"), paired_boot(places, accuracy_change(WITH_EV, SAME_GEN))))},
]
for r in ABLATION:
    r["verdict"] = verdict_of(r["est"], r["lo"], r["hi"])
calls_saved = [c["calls_saved"] for c in CRITIC_ROWS]
DESCRIBED = [
    {"feature": "merging duplicates (dedupe)", "metric": "skeptic calls per run", "value": f"saves {np.mean(calls_saved):.0f} calls per run",
     "verdict": "KEPT" if min(calls_saved) > 0 else "NEUTRAL"},
    {"feature": "the completeness critic", "metric": "lift of missed bugs in named folders", "value": f"lift {np.mean([c['lift'] for c in CRITIC_ROWS]):.1f}",
     "verdict": "REPORTED"},
    {"feature": "model routing", "metric": "recall per cent on the subset", "value": f"front: {', '.join(r['role'] for r in FRONT)}",
     "verdict": "REPORTED"},
    {"feature": "hedged requests", "metric": "slowest call (demo server)", "value": f"p90 hedging: {load_exp('hedging')['slowest_p90']:.2f} s "
     f"against {load_exp('hedging')['slowest_none']:.2f} s", "verdict": "REPORTED"},
    {"feature": "a pipeline instead of a barrier", "metric": "wall clock (simulated)", "value": f"ratio {H7_RATIO:.2f}",
     "verdict": "REPORTED"},
]
table(ABLATION, [("feature", "feature", ""), ("metric", "target metric", ""), ("est", "change when removed", "+.3f"),
                 ("lo", "95% low", "+.3f"), ("hi", "95% high", "+.3f"), ("verdict", "verdict", "")])
table(DESCRIBED, [("feature", "feature", ""), ("metric", "measured as", ""), ("value", "value", ""), ("verdict", "verdict", "")])

#%% code
# FIG  the ablation ledger: what removing each feature does, with 95% intervals
fig, ax = plt.subplots(figsize=(9.4, 3.6))
vcol = {"KEPT": C3, "NEUTRAL": MUTED, "HARMFUL": C8}
for i, r in enumerate(ABLATION):
    ax.errorbar([r["est"]], [i], xerr=[[r["est"] - r["lo"]], [r["hi"] - r["est"]]], fmt="o", color=vcol[r["verdict"]], capsize=4, ms=7)
    ax.text(max(r["hi"], 0) + 0.01, i, f"{r['verdict']}  ({r['metric']})", va="center", fontsize=7.5, color=vcol[r["verdict"]])
ax.axvline(0, color=INK, lw=1)
ax.set_yticks(range(len(ABLATION)), [r["feature"] for r in ABLATION], fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("change in the target metric when the feature is removed (negative: the feature helped)")
kept = sum(r["verdict"] == "KEPT" for r in ABLATION)
finish(fig, "s55_ablation", f"{kept} of {len(ABLATION)} measured features KEPT: removing them hurt by more than the noise",
       "95% paired bootstrap intervals, 2,000 resamples over planted bugs (recall) or checked places (accuracy, precision)")

#%% md
**Reading FIG {{figures.s55_ablation}} (s55_ablation).** Each row is one feature, and the dot is the change in its target metric when it is removed, with the 95% interval. Left of the line means the feature was helping. {{ablation.kept}} of {{ablation.total}} features were KEPT: removing them hurt by more than the noise. NEUTRAL rows are not proof of uselessness; their intervals cross zero, so these runs cannot tell. The features in the second table are not judged by an interval. Merging is KEPT because it saved skeptic calls in every run and costs nothing in recall. Routing and the critic were measured once, and hedging only on the demo server, so they are REPORTED. The pipeline was measured only in the simulator, where it saved little (ratio {{sim.h7_ratio|.2f}}, against the 0.80 that H7 asked for), so it is REPORTED too.

#%% code
save_exp("ablation", {"rows": ABLATION, "described": DESCRIBED, "kept": kept, "total": len(ABLATION),
                      "neutral": sum(r["verdict"] == "NEUTRAL" for r in ABLATION), "harmful": sum(r["verdict"] == "HARMFUL" for r in ABLATION)})
results = []
expect("every interval contains its estimate", all(r["lo"] - 1e-9 <= r["est"] <= r["hi"] + 1e-9 for r in ABLATION))
expect("the verdict rule is applied mechanically", all(r["verdict"] == verdict_of(r["est"], r["lo"], r["hi"]) for r in ABLATION))

#%% md
## S56 - The error budget: where every missed bug was lost

**Theory.** A recall of 0.8 says 14 planted bugs were missed and nothing about why. An **error budget** follows each missed bug through the trace of its run and names the first stage that lost it:

1. **never read**: no worker was given its file;
2. **read, never reported**: workers read the file and no finding named the bug;
3. **reported near it, not counted**: a finding named the right file within twenty lines but outside the scorer's rule, a case S63 audits by hand;
4. **reported, then rejected**: a finding named the bug and the skeptics voted it down;
5. **confirmed, then lost**: confirmed, but missing from the final report.

Each category points at a different fix: coverage, reading, the scorer, verification or merging.

**In plain terms.** For every bug a run missed, we look up exactly where along the way it fell out.

#%% code
def near_misses(b, findings):
    """Findings in the bug's file within twenty lines that the scorer did not count."""
    return [f for f in findings if f["file"] == b["path"] and abs(int(f.get("line") or 0) - b["line"]) <= 20
            and not match(as_findings([f]), key=[b]).tp]


def lost_where(b, kit, final_ids):
    """The first stage of a run's trace at which planted bug b was lost, or 'found'."""
    if b["id"] in final_ids:
        return "found"
    if b["path"] not in {p for p, _, _ in kit.trace["scanned"]}:
        return "never read"
    hits = [f for f in kit.trace["found"] if match(as_findings([f]), key=[b]).tp]
    if not hits:
        return "reported near it, not counted" if near_misses(b, kit.trace["found"]) else "read, never reported"
    confirmed = {key_of(f) for f in kit.trace["confirmed"]}
    if any(key_of(f) in confirmed for f in hits):
        return "confirmed, then lost"
    return "reported, then rejected"

show_def(near_misses, lost_where)
STAGES = ["never read", "read, never reported", "reported near it, not counted", "reported, then rejected", "confirmed, then lost", "found"]
BUDGET_ROWS7 = []
for arm, objs, rows in (("C", C_OBJS, C_RUNS), ("D", [o for o in D_OBJS if o], [r for r, o in zip(D_RUNS, D_OBJS) if o])):
    for (run, kit, result), row in zip(objs, rows):
        c = collections.Counter(lost_where(b, kit, set(row["found_ids"])) for b in ANSWER_KEY)
        BUDGET_ROWS7.append({"run": f"{arm} run {row['run']}", **{s: c[s] for s in STAGES}})
for i, e in enumerate(SOLO):
    read = e.files_read & set(CORPUS)
    found = set(SOLO_SCORES[i].found)
    c = collections.Counter("found" if b["id"] in found else "never read" if b["path"] not in read else "read, never reported"
                            for b in ANSWER_KEY)
    BUDGET_ROWS7.insert(i, {"run": f"A run {i}", **{s: c[s] for s in STAGES}})
table(BUDGET_ROWS7, [("run", "run", "")] + [(s, s, "d") for s in STAGES])

#%% code
# FIG  where each run lost the bugs it missed
fig, ax = plt.subplots(figsize=(10.4, 3.8))
stage_colour = dict(zip(STAGES, [MUTED, C2, C4, C8, C7, C3]))
left = np.zeros(len(BUDGET_ROWS7))
for s in STAGES:
    vals = np.array([r[s] for r in BUDGET_ROWS7])
    ax.barh(range(len(BUDGET_ROWS7)), vals, left=left, color=stage_colour[s], label=s)
    left += vals
ax.set_yticks(range(len(BUDGET_ROWS7)), [r["run"] for r in BUDGET_ROWS7])
ax.invert_yaxis()
ax.set_xlabel(f"the {len(ANSWER_KEY)} planted bugs")
ax.legend(fontsize=7, ncol=3, loc="upper center", bbox_to_anchor=(0.5, -0.18))
top = collections.Counter()
for r in BUDGET_ROWS7:
    if r["run"].startswith("D"):
        top.update({s: r[s] for s in STAGES if s != "found"})
worst = top.most_common(1)[0][0] if top else "none"
finish(fig, "s56_error_budget", f"Where the misses were lost: for the dynamic workflow, most often '{worst}'",
       "every planted bug of every run, placed at the first stage of its run's trace that lost it")

#%% md
**Reading FIG {{figures.s56_error_budget}} (s56_error_budget).** Each bar is one run and each colour a stage. One agent alone lost most of its misses at the first stage: it never read the files ({{errors.A_never|.1f}} bugs per run on average). The fixed plan and the dynamic workflow read every file, so their misses happen later. For the workflow, the largest share of misses was lost at *{{errors.D_worst}}*: {{errors.D_worst_n|.1f}} bugs per run. That points at the next thing to improve. A stage that loses bugs at reading calls for more or better readings (lenses, rounds); one that loses them at verification calls for kinder skeptics or better evidence; near misses call for the scorer audit of S63.

#%% code
mean_stage = lambda prefix, s: float(np.mean([r[s] for r in BUDGET_ROWS7 if r["run"].startswith(prefix)]))
save_exp("errors", {"rows": BUDGET_ROWS7, "A_never": mean_stage("A", "never read"), "D_worst": worst,
                    "D_worst_n": mean_stage("D", worst) if worst != "none" else 0.0,
                    **{f"D_{s.split(',')[0].replace(' ', '_')}": mean_stage("D", s) for s in STAGES}})
results = []
expect("every planted bug of every run is placed exactly once", all(sum(r[s] for s in STAGES) == len(ANSWER_KEY) for r in BUDGET_ROWS7))
expect("the error budget's 'found' count agrees with each run's score",
       all(r["found"] == len(row["found_ids"]) for r, row in zip(BUDGET_ROWS7[len(SOLO):], C_RUNS + [x for x, o in zip(D_RUNS, D_OBJS) if o])))
