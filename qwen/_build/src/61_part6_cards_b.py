#%% md
## S43 - Card: adversarial verify, and how many skeptics

**Why.** Most findings are false alarms; S35 counted them. A verification stage removes them, but each skeptic is itself noisy, and every skeptic is a call. One skeptic per finding is cheap and noisy; five with a majority vote are expensive and steady. The vote threshold trades the two errors against each other: requiring more agreement removes more false alarms and also more real bugs.

**Build.** Nothing new: `vote` from S31 with different thresholds.

**Live.** The places of run 0 get two more skeptics with evidence (samples 3 and 4), so every place has five independent verdicts. Every combination of *k* skeptics (the first *k* samples) and *need* agreeing votes is then scored for free, plus the point with no verification at all.

#%% code
MORE_EV = verdict_table(C0_CANDS, [3, 4], with_evidence=True, run_id="s43-more-skeptics")
FIVE = WITH_EV + MORE_EV
real_votes = collections.defaultdict(list)
for r in sorted(FIVE, key=lambda r: r["sample"]):
    real_votes[r["key"]].append(r["real"] is True)


def vote_point(k, need):
    """Precision of the kept places and recall against all planted bugs, keeping places with >= need real votes among the first k."""
    kept = [key for key, vs in real_votes.items() if sum(vs[:k]) >= need]
    tp = sum(C0_TRUTH[key] for key in kept)
    return {"k": k, "need": need, "kept": len(kept), "precision": tp / max(1, len(kept)), "recall": tp / len(ANSWER_KEY), "calls": k}

show_def(vote_point)
VOTE_ROWS = [{"k": 0, "need": 0, "kept": len(C0_CANDS), "precision": sum(C0_TRUTH.values()) / max(1, len(C0_CANDS)),
              "recall": sum(C0_TRUTH.values()) / len(ANSWER_KEY), "calls": 0}]
VOTE_ROWS += [vote_point(k, need) for k in (1, 3, 5) for need in range(1, k + 1)]
table(VOTE_ROWS, [("k", "skeptics", "d"), ("need", "keep if at least", "d"), ("kept", "places kept", "d"),
                  ("precision", "precision", ".2f"), ("recall", "recall", ".2f")])

#%% code
# FIG  precision against recall for every number of skeptics and every vote threshold
fig, ax = plt.subplots(figsize=(7.4, 4.2))
for k, colour in ((1, C4), (3, C1), (5, C7)):
    pts = [r for r in VOTE_ROWS if r["k"] == k]
    ax.plot([r["recall"] for r in pts], [r["precision"] for r in pts], "o-", color=colour, label=f"{k} skeptic{'s' if k > 1 else ''}")
    for r in pts:
        ax.annotate(f"{r['need']} of {k}", (r["recall"], r["precision"]), textcoords="offset points", xytext=(4, 4), fontsize=7.5)
nv = VOTE_ROWS[0]
ax.scatter([nv["recall"]], [nv["precision"]], marker="X", s=80, color=C8, label="no verification", zorder=3)
ax.set_xlabel("recall (share of all planted bugs kept)")
ax.set_ylabel("precision (share of kept places that are planted bugs)")
ax.legend(fontsize=8)
fixed = next(r for r in VOTE_ROWS if r["k"] == 3 and r["need"] == 2)
finish(fig, "s43_skeptics", f"Verification lifted precision from {nv['precision']:.2f} to {fixed['precision']:.2f} at 2 of 3 skeptics, "
       f"keeping recall from {nv['recall']:.2f} to {fixed['recall']:.2f}", "the places of the fixed plan's run 0, five skeptics with evidence each; "
       "every point is scored from the same verdicts")

#%% md
**Evidence. Reading FIG {{figures.s43_skeptics}} (s43_skeptics).** The red cross is no verification: every place the scans reported is kept, with a precision of {{skeptics.none_precision|.2f}}. Each line is a number of skeptics, and its points are the vote thresholds. The fixed plan's choice, 2 of 3, kept a precision of {{skeptics.p23|.2f}} at a recall of {{skeptics.r23|.2f}}; 1 of 1 gave {{skeptics.p11|.2f}} at {{skeptics.r11|.2f}}; 3 of 5 gave {{skeptics.p35|.2f}} at {{skeptics.r35|.2f}}. Moving up and to the left is the usual price of caution. H4 in S50 asks whether verification as a whole is worth it under a rule fixed in advance.

#%% code
pick = lambda k, need: next(r for r in VOTE_ROWS if r["k"] == k and r["need"] == need)
save_exp("skeptics", {"rows": VOTE_ROWS, "none_precision": nv["precision"], "none_recall": nv["recall"],
                      "p23": pick(3, 2)["precision"], "r23": pick(3, 2)["recall"], "p11": pick(1, 1)["precision"], "r11": pick(1, 1)["recall"],
                      "p35": pick(5, 3)["precision"], "r35": pick(5, 3)["recall"]})
results = []
expect("every place has five verdicts", all(len(v) == 5 for v in real_votes.values()))
expect("asking for more agreement never keeps more places", all(pick(k, n)["kept"] >= pick(k, n + 1)["kept"] for k in (3, 5) for n in range(1, k)))

#%% md
## S44 - Card: a judge from another generation

**Why.** The scan workers are one model. If the skeptics are the same model, they share its habits: the same misreadings, the same blind spots, perhaps a soft spot for its own kind of claim. A **cross-generation judge**, a model from another generation, is less likely to make the same mistake as the finder at the same time. The fixed plan already uses one: its skeptics are the `judge` role, an earlier generation than the `worker` that scans.

**Live.** The same batches, with evidence, judged three times by the worker model itself. We compare accuracy against the key, and how often each judge agrees with the other (Cohen's kappa on the majority verdict per place). The interesting number is the false-positive rate: does the same-generation judge wave through more of its own generation's false alarms?

#%% code
SAME_GEN = verdict_table(C0_CANDS, [0, 1, 2], model="worker", with_evidence=True, run_id="s44-same-generation")
GEN_ACC = {f"{MODELS['judge'].split('/')[-1]} (other generation)": accuracy(WITH_EV),
           f"{MODELS['worker'].split('/')[-1]} (same as the finders)": accuracy(SAME_GEN)}
table([{"judge": k, **v} for k, v in GEN_ACC.items()],
      [("judge", "skeptic model", ""), ("n", "verdicts", "d"), ("accuracy", "accuracy", ".2f"), ("tpr", "planted called real", ".2f"),
       ("fpr", "not planted called real", ".2f")])


def majority(rows):
    """{place: True/False} majority verdict of the rows (ties count as not real)."""
    votes = collections.defaultdict(list)
    for r in rows:
        votes[r["key"]].append(r["real"] is True)
    return {k: sum(v) * 2 > len(v) for k, v in votes.items()}

show_def(majority)
m_other, m_same = majority(WITH_EV), majority(SAME_GEN)
keys = sorted(m_other)
GEN_KAPPA = kappa([m_other[k] for k in keys], [m_same[k] for k in keys])
disagree = [k for k in keys if m_other[k] != m_same[k]]
print(f"[judges] kappa between the two judges' majority verdicts: {GEN_KAPPA:.2f}; they disagree on {len(disagree)} of {len(keys)} places; "
      f"on those, the other generation was right {sum(m_other[k] == C0_TRUTH[k] for k in disagree)} times and the same generation "
      f"{sum(m_same[k] == C0_TRUTH[k] for k in disagree)} times")

#%% code
# FIG  the finders' own model as a judge, against a model from another generation
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.4))
ax = axes[0]
names = list(GEN_ACC)
x = np.arange(3)
for j, (name, colour) in enumerate(zip(names, (C1, C2))):
    a = GEN_ACC[name]
    ax.bar(x + (j - 0.5) * 0.36, [a["accuracy"], a["tpr"], a["fpr"]], 0.36, color=colour, label=name)
ax.set_xticks(x, ["accuracy", "planted called real", "not planted called real"], fontsize=8)
ax.set_ylim(0, 1)
ax.legend(fontsize=7)
panel(ax, "every verdict, against the key")
ax = axes[1]
cm = np.array([[sum(m_other[k] == a and m_same[k] == b for k in keys) for b in (True, False)] for a in (True, False)])
ax.imshow(cm, cmap="Blues")
ax.grid(False)
for i in range(2):
    for j in range(2):
        ax.text(j, i, cm[i, j], ha="center", va="center", fontsize=11)
ax.set_xticks([0, 1], ["real", "not real"])
ax.set_yticks([0, 1], ["real", "not real"])
ax.set_xlabel("same generation says")
ax.set_ylabel("other generation says")
panel(ax, f"majority per place; kappa {GEN_KAPPA:.2f}")
finish(fig, "s44_judges", f"The other generation judged {GEN_ACC[names[0]]['accuracy']:.0%} of verdicts right, "
       f"the finders' own model {GEN_ACC[names[1]]['accuracy']:.0%}", "the places of the fixed plan's run 0, three skeptics each, with evidence")

#%% md
**Evidence. Reading FIG {{figures.s44_judges}} (s44_judges).** Left: the judge from the other generation was right in {{judges.acc_other|.2f}} of its verdicts and the finders' own model in {{judges.acc_same|.2f}}; the false-positive rates were {{judges.fpr_other|.2f}} and {{judges.fpr_same|.2f}}. Right: the two judges' majority verdicts per place agree with a kappa of {{judges.kappa|.2f}}. Where they disagreed, the other generation was right on {{judges.other_right}} places and the same generation on {{judges.same_right}}. A low kappa with similar accuracy would mean the two judges make *different* mistakes, which is the condition under which using both would pay; a high kappa means a second judge adds little.

#%% code
save_exp("judges", {"acc_other": GEN_ACC[names[0]]["accuracy"], "acc_same": GEN_ACC[names[1]]["accuracy"],
                    "fpr_other": GEN_ACC[names[0]]["fpr"], "fpr_same": GEN_ACC[names[1]]["fpr"], "kappa": GEN_KAPPA,
                    "disagree": len(disagree), "other_right": sum(m_other[k] == C0_TRUTH[k] for k in disagree),
                    "same_right": sum(m_same[k] == C0_TRUTH[k] for k in disagree)})
results = []
expect("both judges judged every place three times", len(SAME_GEN) == len(WITH_EV))
expect("kappa is computed on the same places for both judges", set(m_other) == set(m_same))

#%% md
## S45 - Card: loop until dry

**Why.** One pass over the library misses bugs that a second look would catch: a different sample, a different lens, a different moment of the model's attention. A loop keeps scanning while scanning still pays and stops when it does not. The stopping rule is the whole design: stop too early and bugs are left, stop too late and calls are wasted.

**Build.** **`stop_point(curve, min_new)`** applies the simplest rule, *stop after the first round that adds fewer than* `min_new` *new places*, to a discovery curve.

**Live.** No new calls. Six full scans of the library already exist: the three lens scans of the fixed plan's three runs, and the three general scans of S41. Read in that order as six rounds, they form the discovery curve of a loop. For each threshold we see where the rule would stop and what it would have found by then.

#%% code
ROUNDS = [C_OBJS[r][1].trace["found"] for r in range(RUNS)] + GENERAL
ROUND_CALLS = [3 * len(shards())] * RUNS + [len(shards())] * 3
CURVE = discovery(ROUNDS)
for c, n in zip(CURVE, ROUND_CALLS):
    c["calls"] = n


def stop_point(curve, min_new):
    """Index of the round after which the rule 'stop when a round adds fewer than min_new new places' stops."""
    for i, c in enumerate(curve):
        if i > 0 and c["new_places"] < min_new:
            return i
    return len(curve) - 1

show_def(stop_point)
fake_curve = [{"new_places": n} for n in (50, 20, 8, 2, 1)]
print(f"[test] on new places 50, 20, 8, 2, 1: min_new 10 stops after round {stop_point(fake_curve, 10) + 1}, "
      f"min_new 3 after round {stop_point(fake_curve, 3) + 1}")
STOP_ROWS = []
for min_new in (3, 5, 10, 20, 40):
    i = stop_point(CURVE, min_new)
    STOP_ROWS.append({"min_new": min_new, "rounds": i + 1, "calls": sum(c["calls"] for c in CURVE[:i + 1]), "scan_recall": CURVE[i]["scan_recall"]})
table(CURVE, [("round", "round", "d"), ("calls", "calls", "d"), ("new_places", "new places", "d"), ("new_bugs", "new planted bugs", "d"),
              ("scan_recall", "planted bugs reported so far", ".2f")])
table(STOP_ROWS, [("min_new", "stop below this many new places", "d"), ("rounds", "rounds run", "d"), ("calls", "scan calls", "d"),
                  ("scan_recall", "scan-stage recall at the stop", ".2f")])

#%% code
# FIG  the discovery curve of a loop, and where each stopping rule would stop
fig, ax = plt.subplots(figsize=(8.6, 3.8))
cum_calls = np.cumsum([c["calls"] for c in CURVE])
ax.plot(cum_calls, [c["scan_recall"] for c in CURVE], "o-", color=C3, label="planted bugs reported so far")
ax2 = ax.twinx()
ax2.bar(cum_calls, [c["new_places"] for c in CURVE], width=[c["calls"] * 0.6 for c in CURVE], color=C1, alpha=0.25, label="new places")
for r in STOP_ROWS:
    ax.axvline(r["calls"], color=INK2, ls=":", lw=0.8)
    ax.text(r["calls"], 0.03 + 0.07 * STOP_ROWS.index(r), f" stop < {r['min_new']}", fontsize=7, color=INK2)
ax.set_ylim(0, 1)
ax.set_xlabel("scan calls so far")
ax.set_ylabel("share of planted bugs reported")
ax2.set_ylabel("new places in the round")
ax.legend(fontsize=7.5, loc="lower right")
finish(fig, "s45_loop", f"Six rounds of scanning reported {CURVE[-1]['scan_recall']:.0%} of the planted bugs; one round {CURVE[0]['scan_recall']:.0%}",
       "rounds 1 to 3: the fixed plan's three lens scans; rounds 4 to 6: the general scans of S41; dotted lines: where each rule stops")

#%% md
**Evidence. Reading FIG {{figures.s45_loop}} (s45_loop).** The green line is the share of planted bugs reported by all rounds so far, against the calls spent; the blue bars are the new places each round added. The first round reported {{loop.round1|.2f}} of the planted bugs and six rounds {{loop.round6|.2f}}. Rounds 2 to 6 added {{loop.later_places}} new places, of which {{loop.later_bugs}} were planted bugs; every new place that is not a bug still costs skeptic calls in the verify stage, so the two bars have to be read together. The dotted lines show where each stopping rule would end the loop; the rule *stop when a round adds fewer than 10 new places* stops after {{loop.rounds_10}} rounds at {{loop.recall_10|.2f}}. H5 in S50 asks whether rounds after the first add at least three planted bugs in most runs.

#%% code
rule10 = next(r for r in STOP_ROWS if r["min_new"] == 10)
save_exp("loop", {"curve": CURVE, "stops": STOP_ROWS, "round1": CURVE[0]["scan_recall"], "round6": CURVE[-1]["scan_recall"],
                  "later_places": sum(c["new_places"] for c in CURVE[1:]), "later_bugs": sum(c["new_bugs"] for c in CURVE[1:]),
                  "rounds_10": rule10["rounds"], "recall_10": rule10["scan_recall"]})
results = []
expect("the stop rule works on a hand-made curve", stop_point(fake_curve, 10) == 2 and stop_point(fake_curve, 3) == 3)
expect("the discovery curve never goes down", all(a["scan_recall"] <= b["scan_recall"] for a, b in zip(CURVE, CURVE[1:])))
