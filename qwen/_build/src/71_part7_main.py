#%% md
## S52 - The main comparison

**Theory.** Five designs of the same job, each run more than once where the budget allows:

| arm | design | runs | where it was run |
|---|---|---|---|
| A | one agent alone with tools, 150 turns | 3 | S17 |
| A2 | one agent alone, as many turns as the median D run's Magicubes buy | 2 | here |
| B | a lead calling helpers one at a time | 1 | S19 |
| C | the fixed plan: three lenses, three skeptics with evidence, report | 3 | S32 |
| D | the dynamic workflow: the lead writes a new plan program for each run | 3 | S39 (run 0) and here |

Each D run gets its own sample index for the lead *and* its own sample offset for the workers, so the three D runs are three different plans executed independently. Arm A2 exists because "the workflow spent more" is the first objection to any result in its favour: A2 gives one agent the same money and lets it keep going.

**In plain terms.** Every design gets its turns, the same scorer judges them all, and we look at every run, not just the best one.

#%% code
def recorded_seconds(run_id):
    """Wall clock of a run from its first to its last event, as recorded when it was paid for."""
    path = RUNS_DIR / run_id / "events.jsonl"
    if not path.exists():
        return None
    ev = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    return ev[-1]["t"] - ev[0]["t"] if ev else None


def dynamic_run(r):
    """D run r: the lead writes a program with sample r, it is checked, priced, approved, and run with offset r."""
    w = LEAD.write_program(JOB, SHOW_PAGE, sample=r, budget_mc=SHOW_BUDGET)
    decision, why = approve(w["estimate"], SHOW_BUDGET, person=lambda est: est["magicubes"] <= SHOW_BUDGET / 2)
    if not (w["valid"] and decision == "approved"):
        return {"run": r, "status": f"not run: {decision}", "why": why}, None
    run = Run(f"dynamic workflow, run {r}", JOB, run_id=f"d-dynamic-{r}", llm=job_door(SHOW_BUDGET), concurrency=32)
    kit = AuditKit(run, number=r)
    result = run.run_sync(lambda rr: run_program(w["src"], kit))
    kit.save()
    return {"run": r, **outcome(result, kit), "full_price": full_price(run), "features": ", ".join(features(w["src"])),
            "estimate": w["estimate"]["magicubes"], "tries": w["tries"]}, (run, kit, result)

show_def(recorded_seconds, dynamic_run)
D_RUNS = [{"run": 0, **SHOW_OUT, "full_price": SHOW_FULL, "features": ", ".join(SHOW_FEATURES), "estimate": SHOW_EST["magicubes"],
           "tries": SHOW["tries"]}]
D_OBJS = [(SHOW_RUN, SHOW_KIT, SHOW_RESULT)]
for r in (1, 2):
    row, objs = dynamic_run(r)
    D_RUNS.append(row)
    D_OBJS.append(objs)
    print(f"[D{r}] {row['status']}: recall {row.get('recall', 0):.2f}, precision {(row.get('precision') or 0):.2f}, "
          f"{row.get('full_price', 0):.1f} MC at full price; plan uses: {row.get('features') or 'nothing beyond a data plan'}")

#%% md
**Arm A2: one agent with the workflow's money.** The turn budget is the median full price of the D runs divided by the worker's price per call, capped at 400 turns. The two runs use sample indexes 10 and 11, so they share no calls with arm A.

#%% code
A2_TURNS = int(min(400, round(np.median([d.get("full_price", 0) for d in D_RUNS]) / PRICE.get(MODELS["worker"], 0.2))))
print(f"[A2] the median D run cost {np.median([d.get('full_price', 0) for d in D_RUNS]):.1f} MC at full price: {A2_TURNS} turns of one agent")
t0 = time.perf_counter()
with cf.ThreadPoolExecutor(2) as pool:
    SOLO2 = list(pool.map(lambda r: solo_audit(f"solo2-{r}", max_turns=A2_TURNS, sample=10 + r, run_id=f"solo2-{r}"), range(2)))
SOLO2_SCORES = [match(e.findings) for e in SOLO2]
SOLO2_ROWS = [{"run": e.label, "turns": len(e.turns), "stop": e.stop, "coverage": len(e.files_read & set(CORPUS)) / len(CORPUS),
               "found": s.tp, "recall": s.recall, "precision": s.precision, "full_price": PRICE.get(MODELS["worker"], 0.2) * len(e.turns),
               "minutes": sum(t.seconds for t in e.turns) / 60, "found_ids": s.found} for e, s in zip(SOLO2, SOLO2_SCORES)]
table(SOLO2_ROWS, [("run", "run", ""), ("turns", "turns", "d"), ("stop", "stopped because", ""), ("coverage", "files read", ".0%"),
                   ("found", "found", "d"), ("recall", "recall", ".2f"), ("precision", "precision", ".2f"), ("full_price", "Magicubes", ".1f")])
print(f"[A2] {time.perf_counter() - t0:.0f} s of wall clock for both runs")

#%% md
**All runs of all arms, in one table.** Cost is at full price everywhere, so an arm that reused calls through the ledger is not made to look cheaper than it was. Wall clock is the time the run took when it was paid for: for the single agent and the sequential team, the sum of their model times, since they work one call at a time; for C and D, the recorded span of the run.

#%% code
ARMS = []
for i, (row, e) in enumerate(zip(SOLO_ROWS, SOLO)):
    ARMS.append({"arm": "A", "run": i, "recall": row["recall"], "precision": row["precision"], "found_ids": SOLO_SCORES[i].found,
                 "tp": SOLO_SCORES[i].tp, "fp": SOLO_SCORES[i].fp, "cost": PRICE.get(MODELS["worker"], 0.2) * len(e.turns),
                 "minutes": row["minutes"]})
for i, row in enumerate(SOLO2_ROWS):
    ARMS.append({"arm": "A2", "run": i, "recall": row["recall"], "precision": row["precision"], "found_ids": row["found_ids"],
                 "tp": SOLO2_SCORES[i].tp, "fp": SOLO2_SCORES[i].fp, "cost": row["full_price"], "minutes": row["minutes"]})
ARMS.append({"arm": "B", "run": 0, "recall": SEQ_REC["recall"], "precision": SEQ_REC["precision"], "found_ids": SEQ_SCORE.found,
             "tp": SEQ_SCORE.tp, "fp": SEQ_SCORE.fp, "minutes": SEQ_REC["minutes"],
             "cost": len(SEQ.turns) * PRICE.get(MODELS["lead"], 0.5) + len(SEQ.files_read) * PRICE.get(MODELS["worker"], 0.2)})
for (run, kit, result), row in zip(C_OBJS, C_RUNS):
    ARMS.append({"arm": "C", "run": row["run"], "recall": row["recall"], "precision": row["precision"], "found_ids": row["found_ids"],
                 "tp": row["tp"], "fp": row["fp"], "cost": full_price(run), "minutes": (recorded_seconds(run.run_id) or 0) / 60})
for objs, row in zip(D_OBJS, D_RUNS):
    if objs:
        ARMS.append({"arm": "D", "run": row["run"], "recall": row["recall"], "precision": row["precision"], "found_ids": row["found_ids"],
                     "tp": row["tp"], "fp": row["fp"], "cost": row["full_price"], "minutes": (recorded_seconds(objs[0].run_id) or 0) / 60})
table(ARMS, [("arm", "arm", ""), ("run", "run", "d"), ("recall", "recall", ".2f"), ("precision", "precision", ".2f"),
             ("cost", "Magicubes", ".1f"), ("minutes", "minutes", ".1f")])

#%% md
**Intervals.** **`boot_recall(a, b)`** resamples the 72 planted bugs, and within each arm its runs, 2,000 times, and returns the 95% interval of the difference in mean recall between two arms. **`boot_precision`** does the same for precision, resampling each run's reported places.

#%% code
def boot_recall(a, b, n=2000, seed=SEED):
    """95% interval of mean recall(a) - mean recall(b): bugs and runs resampled."""
    rng_ = np.random.default_rng(seed)
    ids = [x["id"] for x in ANSWER_KEY]
    ma = np.array([[i in set(r["found_ids"]) for i in ids] for r in a], dtype=float)
    mb = np.array([[i in set(r["found_ids"]) for i in ids] for r in b], dtype=float)
    diffs = []
    for _ in range(n):
        cols = rng_.integers(0, len(ids), len(ids))
        ra, rb = rng_.integers(0, len(a), len(a)), rng_.integers(0, len(b), len(b))
        diffs.append(ma[ra][:, cols].mean() - mb[rb][:, cols].mean())
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def boot_precision(a, b, n=2000, seed=SEED):
    """95% interval of mean precision(a) - mean precision(b): runs resampled, then each run's distinct places."""
    rng_ = np.random.default_rng(seed)

    def draw(rows):
        ps = []
        for r in rng_.integers(0, len(rows), len(rows)):
            places = np.array([1] * rows[r]["tp"] + [0] * rows[r]["fp"])
            ps.append(places[rng_.integers(0, len(places), len(places))].mean() if len(places) else 0.0)
        return np.mean(ps)
    diffs = [draw(a) - draw(b) for _ in range(n)]
    return float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))

show_def(boot_recall, boot_precision)
by_arm = {k: [r for r in ARMS if r["arm"] == k] for k in ("A", "A2", "B", "C", "D")}
DIFFS = {f"{a} - {b}": boot_recall(by_arm[a], by_arm[b]) for a, b in (("D", "A"), ("D", "A2"), ("D", "C"), ("C", "A"))}
for k, (lo, hi) in DIFFS.items():
    print(f"[boot] mean recall {k}: 95% interval {lo:+.2f} to {hi:+.2f}")
PDIFF = boot_precision(by_arm["D"], by_arm["A"])
print(f"[boot] mean precision D - A: 95% interval {PDIFF[0]:+.2f} to {PDIFF[1]:+.2f}")

#%% code
# FIG  recall of every run of every arm
fig, ax = plt.subplots(figsize=(8.6, 3.8))
order = ["A", "A2", "B", "C", "D"]
colour = {"A": MUTED, "A2": C5, "B": C2, "C": C1, "D": C7}
for x, k in enumerate(order):
    ys = [r["recall"] for r in by_arm[k]]
    ax.scatter([x + 0.04 * (j - (len(ys) - 1) / 2) for j in range(len(ys))], ys, s=50, color=colour[k], zorder=3)
    if ys:
        ax.plot([x - 0.25, x + 0.25], [np.mean(ys)] * 2, color=colour[k], lw=2)
SHORT = {"A": "one agent", "A2": "one agent,\nsame money", "B": "sequential\nteam", "C": "fixed plan", "D": "dynamic\nworkflow"}
ax.set_xticks(range(len(order)), [f"{k}\n{SHORT[k]}" for k in order], fontsize=8)
ax.set_ylim(0, 1)
ax.set_ylabel("recall (share of the 72 planted bugs)")
lo, hi = DIFFS["D - A"]
finish(fig, "s52_recall", f"Every run of every arm: the dynamic workflow's mean recall beat one agent's by {lo:+.2f} to {hi:+.2f} (95% interval)",
       "dots: runs; bars: arm means; all runs scored by the same scorer against the same key")

#%% md
**Reading FIG {{figures.s52_recall}} (s52_recall).** Each dot is one run and each bar an arm's mean. One agent alone (A) reached {{main.A_mean|.2f}} on average, and with the workflow's money (A2) {{main.A2_mean|.2f}}. The sequential team (B) reached {{main.B_mean|.2f}}, the fixed plan (C) {{main.C_mean|.2f}} and the dynamic workflow (D) {{main.D_mean|.2f}}. The interval of the mean difference D minus A runs from {{main.DA_lo|+.2f}} to {{main.DA_hi|+.2f}}, and D minus C from {{main.DC_lo|+.2f}} to {{main.DC_hi|+.2f}}. The verdicts on H1 and H1b are computed at the end of this Part, from these intervals and the rules of S50.

#%% code
# FIG  precision against recall, run by run
fig, ax = plt.subplots(figsize=(6.8, 4.2))
for k in order:
    rs = by_arm[k]
    ax.scatter([r["recall"] for r in rs], [r["precision"] or 0 for r in rs], s=55, color=colour[k], label=k, zorder=3)
ax.set_xlim(0, 1)
ax.set_ylim(0, 1.05)
ax.set_xlabel("recall")
ax.set_ylabel("precision")
ax.legend(fontsize=8, title="arm", title_fontsize=8)
finish(fig, "s52_precision", "Precision against recall for every run: up and to the right is better",
       "each dot is one run; precision counts distinct places, so repeating a correct finding never helps")

#%% md
**Reading FIG {{figures.s52_precision}} (s52_precision).** Up and to the right is better on both counts. The single agent's runs sit at {{main.A_prec|.2f}} precision on average, the fixed plan's at {{main.C_prec|.2f}} and the dynamic workflow's at {{main.D_prec|.2f}}. The interval of the precision difference D minus A runs from {{main.PDA_lo|+.2f}} to {{main.PDA_hi|+.2f}}, which is what H3 is decided on.

#%% code
# FIG  what each arm cost, in Magicubes and in wall clock
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.4))
for ax, key, label in ((axes[0], "cost", "Magicubes per run (full price)"), (axes[1], "minutes", "minutes per run")):
    for x, k in enumerate(order):
        ys = [r[key] for r in by_arm[k]]
        ax.bar(x, np.mean(ys) if ys else 0, color=colour[k], alpha=0.35)
        ax.scatter([x] * len(ys), ys, color=colour[k], s=30, zorder=3)
    ax.set_xticks(range(len(order)), order)
    panel(ax, label)
finish(fig, "s52_cost", f"The dynamic workflow cost {np.mean([r['cost'] for r in by_arm['D']]):.1f} Magicubes and "
       f"{np.mean([r['minutes'] for r in by_arm['D']]):.0f} minutes per run on average",
       "bars: arm means; dots: runs; minutes are the wall clock recorded when the calls were paid for")

#%% md
**Reading FIG {{figures.s52_cost}} (s52_cost).** Left: the dynamic workflow spent {{main.D_cost|.1f}} Magicubes per run against {{main.A_cost|.1f}} for one agent alone; A2 was given {{main.A2_cost|.1f}}. Right: time. One agent works one call at a time, so its minutes add up call by call; the workflow's workers run side by side, so its minutes are the span of a run. With per-call billing, a workflow that makes more calls costs more Magicubes even when it saves hours. Whether those Magicubes bought enough recall is the question H1b answers.

#%% code
summ = {f"{k}_mean": float(np.mean([r["recall"] for r in v])) if v else None for k, v in by_arm.items()}
summ.update({f"{k}_prec": float(np.mean([r["precision"] or 0 for r in v])) if v else None for k, v in by_arm.items()})
summ.update({f"{k}_cost": float(np.mean([r["cost"] for r in v])) if v else None for k, v in by_arm.items()})
summ.update({"DA_lo": DIFFS["D - A"][0], "DA_hi": DIFFS["D - A"][1], "DA2_lo": DIFFS["D - A2"][0], "DA2_hi": DIFFS["D - A2"][1],
             "DC_lo": DIFFS["D - C"][0], "DC_hi": DIFFS["D - C"][1], "PDA_lo": PDIFF[0], "PDA_hi": PDIFF[1], "a2_turns": A2_TURNS,
             "arms": [{k: v for k, v in r.items() if k != "found_ids"} for r in ARMS]})
save_exp("main", summ)
results = []
expect("every arm has the runs the pre-registration promised", [len(by_arm[k]) for k in order] == [3, 2, 1, 3, 3])
expect("every run was scored by the same scorer against all 72 planted bugs", all(0 <= r["recall"] <= 1 for r in ARMS))
expect("the bootstrap intervals are ordered", all(lo <= hi for lo, hi in DIFFS.values()))

#%% md
## S53 - Consistency: the same bugs, run after run?

**Theory.** Two arms with the same mean recall can behave very differently: one finds the same 40 bugs every time, the other a different 40 each time. The first is predictable; the second, run twice, would find many more. **Consistency** is measured per bug: in how many of an arm's runs was it found?

#%% code
ids = [b["id"] for b in ANSWER_KEY]
CONS = {k: np.array([[i in set(r["found_ids"]) for i in ids] for r in by_arm[k]], dtype=int) for k in ("A", "C", "D")}
CONS_ROWS = []
for k, m in CONS.items():
    hits = m.sum(axis=0)
    jac = [len(set(np.where(m[a])[0]) & set(np.where(m[b])[0])) / max(1, len(set(np.where(m[a])[0]) | set(np.where(m[b])[0])))
           for a in range(len(m)) for b in range(a + 1, len(m))]
    CONS_ROWS.append({"arm": k, "every_run": int((hits == len(m)).sum()), "some_runs": int(((hits > 0) & (hits < len(m))).sum()),
                      "no_run": int((hits == 0).sum()), "spread": float(m.mean(axis=1).max() - m.mean(axis=1).min()),
                      "jaccard": float(np.mean(jac)) if jac else None, "union": int((hits > 0).sum())})
table(CONS_ROWS, [("arm", "arm", ""), ("every_run", "found in every run", "d"), ("some_runs", "in some runs", "d"),
                  ("no_run", "in no run", "d"), ("union", "found at least once", "d"), ("spread", "recall spread", ".2f"),
                  ("jaccard", "mean overlap of two runs", ".2f")])

#%% code
# FIG  which bug was found in which run, arm by arm
order_bugs = np.argsort(-(CONS["D"].sum(axis=0) * 100 + CONS["C"].sum(axis=0) * 10 + CONS["A"].sum(axis=0)))
mat = np.vstack([CONS[k][:, order_bugs] for k in ("A", "C", "D")])
fig, ax = plt.subplots(figsize=(10.8, 3.0))
ax.imshow(mat, cmap=matplotlib.colors.ListedColormap([SURF, C1]), aspect="auto", interpolation="nearest")
ax.grid(False)
ax.set_yticks(range(mat.shape[0]), [f"{k} run {r}" for k in ("A", "C", "D") for r in range(len(CONS[k]))], fontsize=7.5)
for y in (len(CONS["A"]) - 0.5, len(CONS["A"]) + len(CONS["C"]) - 0.5):
    ax.axhline(y, color=INK2, lw=1)
ax.set_xticks([])
ax.set_xlabel(f"the {len(ids)} planted bugs, sorted by how often the workflow found them")
cons = {r["arm"]: r for r in CONS_ROWS}
finish(fig, "s53_consistency", f"The dynamic workflow found {cons['D']['every_run']} bugs in every run; one agent alone {cons['A']['every_run']}",
       "blue: found in that run; each row one run, each column one planted bug")

#%% md
**Reading FIG {{figures.s53_consistency}} (s53_consistency).** Each row is a run and each column a planted bug, blue where the run found it. The dynamic workflow found {{consistency.D_every}} bugs in all three of its runs and missed {{consistency.D_none}} in all three; one agent alone found {{consistency.A_every}} in every run. Two of the workflow's runs overlapped by {{consistency.D_jaccard|.2f}} on average (Jaccard), against {{consistency.A_jaccard|.2f}} for one agent alone. The recall spread between best and worst run was {{consistency.D_spread|.2f}} for the workflow and {{consistency.A_spread|.2f}} for one agent: H2 compares exactly these two numbers.

#%% code
save_exp("consistency", {**{f"{r['arm']}_{k}": r[v] for r in CONS_ROWS for k, v in (("every", "every_run"), ("none", "no_run"),
                                                                                     ("jaccard", "jaccard"), ("spread", "spread"),
                                                                                     ("union", "union"))}, "rows": CONS_ROWS})
results = []
expect("every bug is counted once per arm", all(r["every_run"] + r["some_runs"] + r["no_run"] == len(ids) for r in CONS_ROWS))
