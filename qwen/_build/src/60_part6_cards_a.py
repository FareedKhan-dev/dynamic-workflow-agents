#%% md
# Part VI. Quality patterns, one feature card each

**Where this sits.** Part V built plans that use lenses, evidence, several skeptics, a judge from another model generation, loops, merging and a report. Each of these costs calls, and none of them was measured on its own. A feature that costs calls and buys nothing should be switched off, and a feature that helps should be known to help, by how much, and at what price. This Part measures them one at a time.

Most of the measurements reuse calls that already exist. The three runs of the fixed plan (S32) scanned the whole library with three lenses and checked every finding three times with evidence. A card that needs a variant, say the same skeptics without evidence, makes only the calls that differ, and the ledger answers the rest.

**By the end of this Part you can**

- say, for each of nine features, what it buys and what it costs, with the measurement behind it;
- estimate how many bugs an audit has left to find, from the audit's own records and without an answer key;
- read a feature card and decide whether to switch the feature on in your own workflow.

**How a feature card reads.** Every card has the same six steps:

1. **Why**: the problem the feature is meant to solve;
2. **Build**: the code, if the kit does not already have it;
3. **Test**: a check of the code on something we can verify by hand;
4. **Live**: the measurement on real workers;
5. **Evidence**: the figure and what it shows;
6. **Verdict**: KEPT, NEUTRAL or HARMFUL. The verdict is not given on the card. It is computed in the ablation ledger of Part VII (S55), under the pre-registered rules of S50, with intervals, so that no card grades itself.

![part6](attachment:part6_map.png)

#%% md
Three small helpers are shared by every card. **`is_planted(f)`** says whether a finding matches a planted bug. **`kappa(a, b)`** is Cohen's kappa, the agreement between two raters corrected for the agreement they would reach by chance: 1 is perfect agreement, 0 is chance. **`C0`** names the first run of the fixed plan, whose records most cards start from.

#%% code
def is_planted(f):
    """True when the finding matches a planted bug under the scorer of S4."""
    return match(as_findings([f])).tp == 1


def kappa(a, b):
    """Cohen's kappa of two equally long lists of booleans."""
    n = len(a)
    if n == 0:
        return None
    po = sum(x == y for x, y in zip(a, b)) / n
    pa, pb = sum(a) / n, sum(b) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return 1.0 if pe >= 1 else (po - pe) / (1 - pe)

show_def(is_planted, kappa)
C0_RUN, C0_KIT, C0_RESULT = C_OBJS[0]
C0_CHECKED = {v["key"] for v in C0_KIT.trace["checked"]}
C0_CANDS = [f for f in dedupe(C0_KIT.trace["found"]) if key_of(f) in C0_CHECKED]
C0_TRUTH = {key_of(f): is_planted(f) for f in C0_CANDS}
print(f"[C0] {len(C0_KIT.trace['found'])} findings, {len(C0_CANDS)} places checked, {sum(C0_TRUTH.values())} of them planted bugs")
print(f"[kappa] identical raters {kappa([1, 0, 1, 0], [1, 0, 1, 0]):.2f}; opposite raters {kappa([1, 0, 1, 0], [0, 1, 0, 1]):.2f}")

#%% md
## S41 - Card: lenses

**Why.** A worker asked to "find bugs" reads with whatever attention the model happens to bring. A **lens** points that attention at one family of mistakes. Three workers with three lenses read the same shard three different ways; three workers with the same general instruction may read it the same way three times. The question is whether narrow readings find more than repeated general ones *for the same number of calls*.

**Build.** The lenses were defined in S31, aimed at four planted kinds each. Here we add only the measurement.

**Test.** `lens_hits` is checked on a hand-made trace before it touches real data.

**Live.** The fixed plan's run 0 already scanned every shard with the three lenses. We add three general scans of every shard with samples 0, 1 and 2: the same number of calls as the three lenses. Everything is compared at the **scan stage**, before any verification, so the comparison is about reading alone.

#%% code
def lens_hits(found, source_prefix):
    """Planted bug ids reported by the findings whose source starts with the prefix."""
    return set(match(as_findings([f for f in found if f["source"].startswith(source_prefix)])).found)

show_def(lens_hits)
fake = [dict(finding({"file": b["path"], "line": b["line"]}, f"scan:{lens}:x#0")) for b, lens in
        zip(ANSWER_KEY[:3], ["logic", "logic", "state"])]
print(f"[test] logic found {sorted(lens_hits(fake, 'scan:logic:'))}, state found {sorted(lens_hits(fake, 'scan:state:'))}")
LENS_TEST = lens_hits(fake, "scan:logic:") == {b["id"] for b in ANSWER_KEY[:2]}

#%% code
GENERAL_RUN = Run("one general reading, three samples", run_id="s41-general", concurrency=32)
GENERAL_KIT = AuditKit(GENERAL_RUN, number=0)


def three_general(run):
    k = GENERAL_KIT.names()
    k["phase"]("Scan")
    return [k["flatten"](k["parallel"]([lambda s=s: k["scan"](s, "general", sample=j) for s in k["shards"]()])) for j in range(3)]

show_def(three_general, layer="plan")
GENERAL = GENERAL_RUN.run_sync(three_general)
GENERAL_FOUND = [f for xs in GENERAL for f in xs]
arms = {"general x1": lens_hits(GENERAL[0], "scan:general:"), **{f"{l} x1": lens_hits(C0_KIT.trace["found"], f"scan:{l}:") for l in LENSES},
        "general x3": lens_hits(GENERAL_FOUND, "scan:general:"), "three lenses": lens_hits(C0_KIT.trace["found"], "scan:")}
calls = {"general x1": len(shards()), **{f"{l} x1": len(shards()) for l in LENSES}, "general x3": 3 * len(shards()), "three lenses": 3 * len(shards())}
LENS_ROWS = [{"arm": a, "calls": calls[a], "bugs": len(ids), "recall": len(ids) / len(ANSWER_KEY)} for a, ids in arms.items()]
table(LENS_ROWS, [("arm", "scan arm", ""), ("calls", "calls", "d"), ("bugs", "planted bugs reported", "d"), ("recall", "scan-stage recall", ".2f")])
only_lenses = arms["three lenses"] - arms["general x3"]
only_general = arms["general x3"] - arms["three lenses"]
print(f"[lenses] found only by the lenses: {len(only_lenses)}; only by three general readings: {len(only_general)}")

#%% md
**Is each lens finding what it is aimed at?** For each planted kind, the share of its bugs each lens reported. If lenses work as designed, each row should be brightest in its own four columns.

#%% code
KIND_ORDER = [k for lens in LENSES for k in LENS_FAMILY[lens]]
kind_of = {b["id"]: b["operator"] for b in ANSWER_KEY}
n_kind = collections.Counter(kind_of.values())
HEAT = np.array([[sum(kind_of[i] == kind for i in lens_hits(C0_KIT.trace["found"], f"scan:{lens}:")) / n_kind[kind] for kind in KIND_ORDER]
                 for lens in LENSES] + [[sum(kind_of[i] == kind for i in arms["general x1"]) / n_kind[kind] for kind in KIND_ORDER]])
aimed_rate = {lens: float(np.mean([HEAT[r, c] for c, kind in enumerate(KIND_ORDER) if kind in LENS_FAMILY[lens]])) for r, lens in enumerate(LENSES)}
other_rate = {lens: float(np.mean([HEAT[r, c] for c, kind in enumerate(KIND_ORDER) if kind not in LENS_FAMILY[lens]])) for r, lens in enumerate(LENSES)}
for lens in LENSES:
    print(f"[aim] {lens:<10} finds {aimed_rate[lens]:.2f} of the kinds it is aimed at and {other_rate[lens]:.2f} of the others")

#%% code
# FIG  three lenses against three general readings, for the same number of calls
fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.8), gridspec_kw={"width_ratios": [1, 1.5]})
ax = axes[0]
colours = [MUTED, C1, C1, C1, C4, C7]
ax.barh([r["arm"] for r in LENS_ROWS], [r["recall"] for r in LENS_ROWS], color=colours)
ax.invert_yaxis()
ax.set_xlim(0, 1)
ax.set_xlabel("share of planted bugs reported (scan stage)")
for i, r in enumerate(LENS_ROWS):
    ax.text(r["recall"] + 0.01, i, f"{r['recall']:.2f} ({r['calls']} calls)", va="center", fontsize=7.5)
panel(ax, "reading alone, before any check")
ax = axes[1]
im = ax.imshow(HEAT, cmap="Blues", vmin=0, vmax=1, aspect="auto")
ax.grid(False)
ax.set_yticks(range(4), LENSES + ["general"])
ax.set_xticks(range(len(KIND_ORDER)), KIND_ORDER, rotation=60, ha="right", fontsize=7)
for c in (3.5, 7.5):
    ax.axvline(c, color="white", lw=2)
fig.colorbar(im, ax=ax, fraction=0.03, label="share of the kind found")
panel(ax, "what each lens finds, by planted kind")
d = LENS_ROWS[-1]["recall"] - LENS_ROWS[-2]["recall"]
finish(fig, "s41_lenses", f"For the same calls, three lenses reported {abs(d):.0%} {'more' if d >= 0 else 'fewer'} of the planted bugs "
       f"than three general readings", "scan stage only; lenses from run 0 of the fixed plan; general readings with samples 0 to 2; "
       "white lines separate the kinds each lens is aimed at")

#%% md
**Evidence. Reading FIG {{figures.s41_lenses}} (s41_lenses).** Left: at the scan stage, one general reading reported {{lenses.general1|.2f}} of the planted bugs and three general readings {{lenses.general3|.2f}}; the three lenses together reported {{lenses.three|.2f}}, for exactly the same number of calls. Right: each row is one lens, each column one planted kind. The boundaries lens found {{lenses.aim_boundaries|.2f}} of its own kinds against {{lenses.other_boundaries|.2f}} of the others; logic {{lenses.aim_logic|.2f}} against {{lenses.other_logic|.2f}}; state {{lenses.aim_state|.2f}} against {{lenses.other_state|.2f}}. A lens that finds its own kinds more often than the others is doing what it was written for. Whether the difference between the arms is larger than run-to-run noise is decided in S55.

#%% code
save_exp("lenses", {"rows": LENS_ROWS, "general1": LENS_ROWS[0]["recall"], "general3": LENS_ROWS[-2]["recall"], "three": LENS_ROWS[-1]["recall"],
                    "only_lenses": len(only_lenses), "only_general": len(only_general), "heat": HEAT.tolist(), "kinds": KIND_ORDER,
                    **{f"aim_{l}": aimed_rate[l] for l in LENSES}, **{f"other_{l}": other_rate[l] for l in LENSES},
                    "found_lenses": sorted(arms["three lenses"]), "found_general3": sorted(arms["general x3"])})
results = []
expect("lens_hits counts a hand-made trace correctly", LENS_TEST)
expect("the two arms made the same number of calls", calls["general x3"] == calls["three lenses"])
expect("the general run scanned every shard three times", len(GENERAL_RUN.threads) == 3 * len(shards()))

#%% md
## S42 - Card: executable evidence

**Why.** A skeptic that reads a claim about code must work out what the code does, in its head, for the input in question. Models are poor at that kind of mental execution, especially for loops and boundaries, which is exactly where the planted bugs are. The sandbox can simply run the call. **Executable evidence** puts the result of that run in front of the skeptic.

**Build.** `evidence` and its use in `check` exist since S31. The measurement needs one function: **`verdict_table`** runs one kind of skeptic over the same batches with given sample indexes and collects one row per verdict, with the truth next to it.

**Test.** On a batch of two findings, one planted and one not, the table must have one row per finding per sample.

**Live.** The places run 0 of the fixed plan checked, in the same batches, judged three times **with** evidence (the fixed plan's own calls, answered by the ledger) and three times **without** (new calls). Accuracy is measured against the answer key: a verdict is right when it calls a planted bug real or a non-planted place not real. A real bug we did not plant counts against the skeptic here, a bias S66 examines.

#%% code
VERDICT_RUNS = {}


def verdict_table(cands, samples, model="judge", with_evidence=True, run_id="verdicts", batch_size=6):
    """One row per verdict: place, sample, verdict, truth, and the sandbox status of the place."""
    run = Run(f"skeptics: {model}, evidence {'on' if with_evidence else 'off'}", run_id=run_id, concurrency=32)
    VERDICT_RUNS[run_id] = run
    kit = AuditKit(run, number=0, with_evidence=with_evidence)
    bs = batches(cands, batch_size)
    out = run.run_sync(lambda r: r.parallel([lambda b=b, s=s: kit.check(b, sample=s, model=model, with_evidence=with_evidence)
                                             for b in bs for s in samples]))
    status = {key_of(f): evidence(f)["status"] for f in cands}
    truth = {key_of(f): is_planted(f) for f in cands}
    return [{"key": v["key"], "sample": v["sample"], "real": v["real"], "planted": truth[v["key"]], "evidence": status[v["key"]]}
            for vs in out if vs for v in vs]

show_def(verdict_table)
two = [next(f for f in C0_CANDS if C0_TRUTH[key_of(f)]), next((f for f in C0_CANDS if not C0_TRUTH[key_of(f)]), C0_CANDS[-1])]
tiny = verdict_table(two, [0, 1], run_id="s42-test")
print(f"[test] {len(tiny)} rows for 2 places x 2 samples: " + "; ".join(f"{r['key'].split('::')[-1]} s{r['sample']} real={r['real']} planted={r['planted']}" for r in tiny))


def accuracy(rows):
    """Accuracy, true positive rate and false positive rate of verdicts against the key (rows with no verdict skipped)."""
    rows = [r for r in rows if r["real"] is not None]
    pos, neg = [r for r in rows if r["planted"]], [r for r in rows if not r["planted"]]
    return {"n": len(rows), "accuracy": sum(r["real"] == r["planted"] for r in rows) / max(1, len(rows)),
            "tpr": sum(r["real"] for r in pos) / max(1, len(pos)), "fpr": sum(r["real"] for r in neg) / max(1, len(neg))}

show_def(accuracy)

#%% code
WITH_EV = verdict_table(C0_CANDS, [0, 1, 2], with_evidence=True, run_id="s42-with-evidence")
WITHOUT_EV = verdict_table(C0_CANDS, [0, 1, 2], with_evidence=False, run_id="s42-without-evidence")
EV_ACC = {"with evidence": accuracy(WITH_EV), "without evidence": accuracy(WITHOUT_EV)}
table([{"skeptics": k, **v} for k, v in EV_ACC.items()],
      [("skeptics", "skeptics", ""), ("n", "verdicts", "d"), ("accuracy", "accuracy", ".2f"), ("tpr", "planted called real", ".2f"),
       ("fpr", "not planted called real", ".2f")])
BY_STATUS = []
for st in ("differs", "raised", "agrees", "not run"):
    w = [r for r in WITH_EV if r["evidence"] == st]
    wo = [r for r in WITHOUT_EV if r["evidence"] == st]
    if w:
        BY_STATUS.append({"status": st, "places": len({r["key"] for r in w}), "with": accuracy(w)["accuracy"], "without": accuracy(wo)["accuracy"]})
table(BY_STATUS, [("status", "what the sandbox saw", ""), ("places", "places", "d"), ("with", "accuracy with evidence", ".2f"),
                  ("without", "accuracy without", ".2f")])

#%% code
# FIG  what the sandbox result does for a skeptic
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5))
ax = axes[0]
labels = ["accuracy", "planted called real", "not planted called real"]
x = np.arange(3)
for j, (name, colour) in enumerate((("without evidence", MUTED), ("with evidence", C3))):
    a = EV_ACC[name]
    ax.bar(x + (j - 0.5) * 0.36, [a["accuracy"], a["tpr"], a["fpr"]], 0.36, color=colour, label=name)
ax.set_xticks(x, labels, fontsize=8)
ax.set_ylim(0, 1)
ax.legend(fontsize=7.5)
panel(ax, "every verdict, against the key")
ax = axes[1]
x = np.arange(len(BY_STATUS))
ax.bar(x - 0.18, [r["without"] for r in BY_STATUS], 0.36, color=MUTED, label="without evidence")
ax.bar(x + 0.18, [r["with"] for r in BY_STATUS], 0.36, color=C3, label="with evidence")
ax.set_xticks(x, [f"{r['status']}\n({r['places']} places)" for r in BY_STATUS], fontsize=8)
ax.set_ylim(0, 1)
ax.set_ylabel("accuracy")
panel(ax, "by what the sandbox saw")
d = EV_ACC["with evidence"]["accuracy"] - EV_ACC["without evidence"]["accuracy"]
finish(fig, "s42_evidence", f"With the sandbox result in front of them, skeptics were right {abs(d):.0%} "
       f"{'more' if d >= 0 else 'less'} often", "the places of the fixed plan's run 0, the same batches, three skeptics each way; "
       "accuracy against the answer key")

#%% md
**Evidence. Reading FIG {{figures.s42_evidence}} (s42_evidence).** Left: with evidence, skeptics were right in {{evidence_card.acc_with|.2f}} of their verdicts; without it, in {{evidence_card.acc_without|.2f}}. The two failure modes move separately: with evidence, a planted bug was called real {{evidence_card.tpr_with|.2f}} of the time and a non-planted place {{evidence_card.fpr_with|.2f}} of the time; without evidence, {{evidence_card.tpr_without|.2f}} and {{evidence_card.fpr_without|.2f}}. Right: the same accuracy split by what the sandbox saw. Where the call raised or returned something other than the finder expected, the evidence is a strong hint; where it agreed, it is a strong hint the other way; where nothing could be run, the evidence line says so and the skeptic is on its own. H6 in S50 turns this card into a pre-registered test.

#%% code
save_exp("evidence_card", {"acc_with": EV_ACC["with evidence"]["accuracy"], "acc_without": EV_ACC["without evidence"]["accuracy"],
                           "tpr_with": EV_ACC["with evidence"]["tpr"], "fpr_with": EV_ACC["with evidence"]["fpr"],
                           "tpr_without": EV_ACC["without evidence"]["tpr"], "fpr_without": EV_ACC["without evidence"]["fpr"],
                           "by_status": BY_STATUS, "verdicts": len(WITH_EV), "places": len(C0_CANDS)})
results = []
expect("the verdict table has one row per place per sample", len(tiny) == 4)
expect("the with-evidence verdicts are the fixed plan's own, answered by the ledger at no cost",
       all(r.cached for t in VERDICT_RUNS["s42-with-evidence"].threads for r in t.replies))
expect("both arms judged the same places the same number of times", len(WITH_EV) == len(WITHOUT_EV) == 3 * len(C0_CANDS))
