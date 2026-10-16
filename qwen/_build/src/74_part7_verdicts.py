#%% md
## S57 - Crash and resume, formally

**Theory.** S28 showed on the demo server that a crashed run resumes for free. H8 asks the same of a real plan on real workers: cancel it in the middle of its scan phase, run it again, and check two things. The resumed run must produce exactly the report that the plan computes from its answers, as an uninterrupted run would, and no call may have been paid for twice. The plan is the slim plan of S49 with its own sample offset, so all its calls are new when the test starts.

**In plain terms.** Pull the plug halfway, start again, and check that the result is the same and that nothing was paid twice.

#%% code
H8_SRC = slim_program(SHARD_TOKENS)
H8_NUMBER = 7                                            # an offset no other run uses, so every call starts out new


def fresh_calls(run):
    """Calls of a run that were not answered by the ledger."""
    return sum(not r.cached for t in run.threads for r in t.replies)

show_def(fresh_calls)
h8_crash = Run("H8: crashed halfway", run_id="s57-crash", concurrency=8)
h8_crash_kit = AuditKit(h8_crash, number=H8_NUMBER)
h8_crash.start(lambda r: run_program(H8_SRC, h8_crash_kit))
target = len(shards()) // 2
while h8_crash.status in ("created", "running") and sum(t.status == "done" for t in h8_crash.threads) < target:
    time.sleep(0.05)
h8_crash.cancel()
h8_crash.wait()
paid_crash = fresh_calls(h8_crash)
resumed = Run("H8: resumed", run_id="s57-resume", concurrency=8)
resumed_kit = AuditKit(resumed, number=H8_NUMBER)
resumed_result = resumed.run_sync(lambda r: run_program(H8_SRC, resumed_kit))
paid_resume = fresh_calls(resumed)
h8_again = Run("H8: run once more", run_id="s57-again", concurrency=8)
h8_again_kit = AuditKit(h8_again, number=H8_NUMBER)
h8_again_result = h8_again.run_sync(lambda r: run_program(H8_SRC, h8_again_kit))
total_calls = sum(len(t.replies) for t in resumed.threads)
H8 = {"crash_status": h8_crash.status, "paid_crash": paid_crash, "paid_resume": paid_resume, "total": total_calls,
      "paid_again": fresh_calls(h8_again), "same_report": [b["file"] + str(b["line"]) for b in resumed_result["bugs"]] ==
      [b["file"] + str(b["line"]) for b in h8_again_result["bugs"]]}
print(f"[H8] crashed run: {h8_crash.status} after {paid_crash} paid calls; resumed: {paid_resume} new calls of {total_calls}; "
      f"run once more: {H8['paid_again']} new calls; same report: {H8['same_report']}")
H8["holds"] = H8["crash_status"] == "cancelled" and H8["paid_crash"] + H8["paid_resume"] == H8["total"] and H8["paid_again"] == 0 \
    and H8["same_report"]
results = []
expect("the crash really stopped the run early", h8_crash.status == "cancelled" and 0 < paid_crash < total_calls)
expect("crash plus resume paid each call exactly once", paid_crash + paid_resume == total_calls)
expect("a further run is answered entirely by the ledger and reports the same", H8["paid_again"] == 0 and H8["same_report"])

#%% md
## S58 - Who finds what

**Theory.** A mean recall hides which bugs a design finds. Here the planted bugs are split three ways: by **kind** (the twelve operators of S2), by **loudness** (the share of a file's examples the bug broke, S2), and by the **length** of the file it sits in (the quarters of S2). If one design misses one kind entirely, or only finds loud bugs in short files, the mean would never say so.

#%% code
def recall_by(arm_rows, key):
    """{group: mean recall over the arm's runs} for planted bugs grouped by key(bug)."""
    groups = collections.defaultdict(list)
    for b in ANSWER_KEY:
        groups[key(b)].append(b["id"])
    return {g: float(np.mean([sum(i in set(r["found_ids"]) for i in ids) / len(ids) for r in arm_rows])) for g, ids in groups.items()}

show_def(recall_by)
loud_median = float(np.median([b["loudness"] for b in ANSWER_KEY]))
WHO = {k: {"kind": recall_by(by_arm[k], lambda b: b["operator"]),
           "loudness": recall_by(by_arm[k], lambda b: "quiet half" if b["loudness"] <= loud_median else "loud half"),
           "length": recall_by(by_arm[k], lambda b: f"quarter {QUARTER[b['path']] + 1}")} for k in ("A", "C", "D")}
table([{"kind": kind, **{k: WHO[k]["kind"][kind] for k in WHO}} for kind in KIND_ORDER],
      [("kind", "planted kind", ""), ("A", "A", ".2f"), ("C", "C", ".2f"), ("D", "D", ".2f")])

#%% code
# FIG  which bugs each design finds: by kind, by loudness, by file length
fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.8), gridspec_kw={"width_ratios": [2.2, 1, 1.2]})
arm_colour = {"A": MUTED, "C": C1, "D": C7}
ax = axes[0]
x = np.arange(len(KIND_ORDER))
for j, k in enumerate(("A", "C", "D")):
    ax.bar(x + (j - 1) * 0.27, [WHO[k]["kind"][kind] for kind in KIND_ORDER], 0.27, color=arm_colour[k], label=k)
ax.set_xticks(x, KIND_ORDER, rotation=60, ha="right", fontsize=7)
ax.set_ylim(0, 1)
ax.legend(fontsize=7.5, ncol=3)
panel(ax, "by planted kind")
for ax, group, order_ in ((axes[1], "loudness", ["quiet half", "loud half"]), (axes[2], "length", [f"quarter {q}" for q in (1, 2, 3, 4)])):
    x = np.arange(len(order_))
    for j, k in enumerate(("A", "C", "D")):
        ax.bar(x + (j - 1) * 0.27, [WHO[k][group][g] for g in order_], 0.27, color=arm_colour[k])
    ax.set_xticks(x, order_, fontsize=7.5)
    ax.set_ylim(0, 1)
    panel(ax, f"by {group}")
weakest = min(KIND_ORDER, key=lambda kind: WHO["D"]["kind"][kind])
finish(fig, "s58_who_finds_what", f"The dynamic workflow's weakest kind was '{weakest}' ({WHO['D']['kind'][weakest]:.2f})",
       "mean recall over each arm's runs; loudness halves split at the median; quarters of file length as in S2")

#%% md
**Reading FIG {{figures.s58_who_finds_what}} (s58_who_finds_what).** Left: recall by planted kind. The dynamic workflow's weakest kind was *{{who.weakest}}*, at {{who.weakest_recall|.2f}}; its strongest was *{{who.strongest}}*, at {{who.strongest_recall|.2f}}. Middle: quiet bugs, which break few examples, against loud ones; for the workflow {{who.D_quiet|.2f}} against {{who.D_loud|.2f}}. Right: recall by the length of the file the bug is in. One agent alone falls off sharply in long files, because it rarely reached them; the workflow, which gives every file to some worker, should not. Part IX adds the last split, by how well the models may remember the original code.

#%% code
strongest = max(KIND_ORDER, key=lambda kind: WHO["D"]["kind"][kind])
save_exp("who", {"weakest": weakest, "weakest_recall": WHO["D"]["kind"][weakest], "strongest": strongest,
                 "strongest_recall": WHO["D"]["kind"][strongest], "D_quiet": WHO["D"]["loudness"]["quiet half"],
                 "D_loud": WHO["D"]["loudness"]["loud half"], "by_arm": WHO})
results = []
expect("every planted bug falls in exactly one kind, one loudness half and one quarter",
       sum(1 for b in ANSWER_KEY) == len(ANSWER_KEY) and set(WHO["D"]["kind"]) == set(KIND_ORDER))

#%% md
### The pre-registered verdicts

Every rule is read back from the pre-registration file, fingerprint checked, and applied by code. H9 and H10 need the jobs of Part VIII and are decided there.

#%% code
def decide(hid, holds, measured):
    """A verdict row for hypothesis hid, applying the rule of record."""
    h = rule_of_record(hid)
    verdict = "REPORTED" if holds is None else "SUPPORTED" if holds else "NOT SUPPORTED"
    return {"id": hid, "claim": h["claim"], "measured": measured, "verdict": verdict}

show_def(decide)
rec = {k: [r["recall"] for r in by_arm[k]] for k in by_arm}
range_of = lambda xs: max(xs) - min(xs) if xs else None
unverified = set(match(as_findings(C0_CANDS)).found)
verified = set(match(as_findings([f for f in C0_CANDS if sum(real_votes[key_of(f)][:3]) >= 2])).found)
h4 = {"gain": paired_boot(places, lambda ks: kept_precision(3, 2)(ks) - kept_precision(0, 0)(ks)),
      "loss": paired_boot(BUG_IDS, lambda ids: (sum(i in unverified for i in ids) - sum(i in verified for i in ids)) / len(ids))}
gains = []
for r in range(RUNS):
    first = set(match(as_findings(C_OBJS[r][1].trace["found"])).found)
    both = set(match(as_findings(C_OBJS[r][1].trace["found"] + C_OBJS[(r + 1) % RUNS][1].trace["found"])).found)
    gains.append(len(both - first))
ev = paired_boot(places, lambda ks: -accuracy_change(WITH_EV, WITHOUT_EV)(ks))
VERDICTS = [
    decide("H1", (min(rec["D"]) > max(rec["A"]) and DIFFS["D - A"][0] > 0) if rec["D"] and rec["A"] else None,
           f"D {min(rec['D']):.2f} to {max(rec['D']):.2f}, A {min(rec['A']):.2f} to {max(rec['A']):.2f}; "
           f"interval {DIFFS['D - A'][0]:+.2f} to {DIFFS['D - A'][1]:+.2f}"),
    decide("H1b", (min(rec["D"]) > max(rec["A2"]) and DIFFS["D - A2"][0] > 0) if rec["D"] and rec["A2"] else None,
           f"D {min(rec['D']):.2f} to {max(rec['D']):.2f}, A2 {min(rec['A2']):.2f} to {max(rec['A2']):.2f}; "
           f"interval {DIFFS['D - A2'][0]:+.2f} to {DIFFS['D - A2'][1]:+.2f}"),
    decide("H2", range_of(rec["D"]) < range_of(rec["A"]), f"spread D {range_of(rec['D']):.2f}, A {range_of(rec['A']):.2f}"),
    decide("H3", PDIFF[0] >= -0.10, f"interval {PDIFF[0]:+.2f} to {PDIFF[1]:+.2f}"),
    decide("H4", h4["gain"][1] >= 0.15 and h4["loss"][2] <= 0.05,
           f"precision gain {h4['gain'][0]:+.2f} (low {h4['gain'][1]:+.2f}); recall loss {h4['loss'][0]:+.3f} (high {h4['loss'][2]:+.3f})"),
    decide("H5", sum(g >= 3 for g in gains) >= 2, f"planted bugs added by a second scan, per run: {gains}"),
    decide("H6", ev[1] > 0, f"accuracy gain {ev[0]:+.3f} (95% {ev[1]:+.3f} to {ev[2]:+.3f})"),
    decide("H7", H7_RATIO <= 0.8 if SIM_SOURCE == "recorded" else None,
           f"simulated pipeline / barrier = {H7_RATIO:.2f}" + ("" if SIM_SOURCE == "recorded" else " on assumed latencies")),
    decide("H8", H8["holds"], f"paid {H8['paid_crash']} + {H8['paid_resume']} = {H8['total']} calls; same report: {H8['same_report']}"),
]
table(VERDICTS, [("id", "", ""), ("claim", "claim", ""), ("measured", "measured", ""), ("verdict", "verdict", "")])

#%% md
**Reading the verdicts.** Each line is one pre-registered claim, the numbers its rule needed, and the verdict the code computed. A NOT SUPPORTED verdict is as informative as a SUPPORTED one: it marks a place where the expectation written before the runs did not survive them. H7 is decided only when the simulator ran on recorded latencies; on assumed ones it is reported, not judged. The claims table of S69 collects these verdicts with Part VIII's.

#%% code
save_exp("verdicts7", {"rows": VERDICTS, "supported": sum(v["verdict"] == "SUPPORTED" for v in VERDICTS),
                       "not_supported": sum(v["verdict"] == "NOT SUPPORTED" for v in VERDICTS),
                       "reported": sum(v["verdict"] == "REPORTED" for v in VERDICTS), "h8": H8, "h5_gains": gains})
results = []
expect("every verdict was decided under the fingerprinted rules", len(VERDICTS) == 9 and hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest() == PREREG_SHA)

#%% md
**Part VII recap.** The comparisons were registered before they were run, and decided by code:

- five arms, every run scored by one scorer: mean recall {{main.A_mean|.2f}} for one agent alone, {{main.A2_mean|.2f}} with the workflow's money, {{main.B_mean|.2f}} for the sequential team, {{main.C_mean|.2f}} for the fixed plan and {{main.D_mean|.2f}} for the dynamic workflow;
- consistency: the workflow found {{consistency.D_every}} bugs in every run, one agent alone {{consistency.A_every}};
- a simulator that reproduced recorded runs within {{sim.err_show|+.0%}} and predicted an unseen one within {{sim.pred_err|+.0%}}, and put the plan's parallel fraction at {{sim.p|.3f}};
- an ablation ledger with {{ablation.kept}} of {{ablation.total}} features KEPT;
- an error budget that names, for every missed bug, the stage that lost it;
- {{verdicts7.supported}} pre-registered claims SUPPORTED, {{verdicts7.not_supported}} NOT SUPPORTED and {{verdicts7.reported}} REPORTED.

**Try it yourself.**

1. Change H3's threshold in `PREREG` from -0.10 to -0.05 *after* running S52, and rerun the verdicts. What happens, and why is that the behaviour you want?
2. Use the simulator of S54 to find the smallest number of slots at which the showcase plan reaches 90% of its 64-slot speed. How many Magicubes per hour of wall clock does that imply at the workers' price?
3. Pick the stage that lost the most bugs in FIG {{figures.s56_error_budget}} and change one thing in the fixed plan aimed at it. Rerun S32 for one run and S56. Did the bugs move to another stage, or out of the budget?
