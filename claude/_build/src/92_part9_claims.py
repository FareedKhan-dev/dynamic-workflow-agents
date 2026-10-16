#%% md
## S67 - Bugs that produced reassuring wrong answers

Every one of these happened while this notebook was being built, and every one of them made the results look *fine*. That is what makes them dangerous: a bug that crashes gets fixed; a bug that produces a plausible number gets published. Each was caught by a test or a measurement written for something else.

| what went wrong | how it looked | what caught it | the fix |
|---|---|---|---|
| bugs were planted by picking edits uniformly, so long files got most of them | a normal-looking benchmark | the leak test of S3: file length alone predicted a bug at AUROC 0.70 | pick a file first, balance length quarters (S2) |
| the API key variable and the answer key shared one name, `KEY` | nothing at all, until the scorer read the key | a test that the answer key had 72 entries | `API_KEY` and `ANSWER_KEY`, everywhere |
| a file's examples drew unseeded random numbers, so it passed on some runs only | every build looked healthy on its own | two builds compared byte for byte: the planted bugs had moved | seed the runner (S1) |
| `python -I` silently ignored the hash seed | the same as above | the same comparison | `-s -P -B` and an explicit environment (S1) |
| a CPU-time limit decided which files were too slow | the same as above, but only on a busy machine | a build under four busy processes against a quiet one | no decision from timing at all (S1) |
| duplicates were merged by whichever worker finished first | identical results, different ledger keys | a test that checks were answered by the ledger | ties broken by content (S31) |
| hedged duplicates got the same emulated delay as the original | hedging "never helped" | a test that hedging never made the slowest call slower | a fresh draw for a repeated request (S6) |
| a second function named `compact` replaced the single agent's | nothing until an agent's context filled up | arm A2, the first long single-agent run after S31 | `compact_findings` (S31) |
| a stand-in scanner answered the single agent's turns too | arm A2 "found nothing" | a smoke run of S52 | stand-ins recognise only their own requests |
| a planted operation error kept the old result when it was written as `$15,000` | a key that called a visible slip an "operation" error | the calculator flagged "operation" items more often than correct ones | read and write thousands commas (S59) |
| the report model grouped dozens of different bugs under one heading by kind of mistake, such as "returns the wrong variable" | the reported recall of two fixed-plan runs fell to 2 or 3 bugs, although 86 were confirmed | comparing the confirmed count with the reported count of every run | split any group that spans functions (S31), and a clearer instruction |

**In plain terms.** The bugs that hurt are the ones that give believable numbers. The defence is many small, independent checks, each of which knows what the answer must be.

#%% md
## S68 - Threats to validity

**Construct validity: do the measures measure what we say?** Recall counts planted bugs; real bugs differ from one-line mutations. The scorer's line rule was audited in S63, where {{scorer_audit.missed_by_scorer}} detections were found outside it. Precision counts unplanted places as false, although S66 found {{unplanted.candidates}} candidates that may be real.

**Internal validity: could something other than the design explain the differences?** All arms used the same worker model, the same library and the same scorer, and the guard of S51 counted {{guard.leaks}} messages that mention the hidden key. The fixed and dynamic plans share some calls through the ledger, which makes their comparison sharper rather than biased: identical questions got identical answers. The single agent read only the files it chose to open (S17); how much one reader can cover is the design difference under test, not a confound.

**External validity: does it carry over?** One library, one model family, one provider. The library is public, and S65 measured how much of it the worker remembers. Part VIII gives three more jobs on the same engine, which is evidence of generality for the engine, not for the numbers.

**Statistical validity.** Three runs per arm is few. Every comparison carries a bootstrap interval, and the pre-registered rules of S50 decided the verdicts. Smoke runs of this notebook use a scripted stand-in; no number from a smoke run is ever reported.

#%% md
## S69 - The claims that survive

Every pre-registered hypothesis, with its verdict as computed in S58 and Part VIII. H9 and H10 are decided here from the measurements of S59 and S61.

#%% code
CLAIMS = list(VERDICTS) + [
    decide("H9", H9_HOLDS, f"single grader {SLOPE_SINGLE[0]:+.3f} per 100 items ({SLOPE_SINGLE[1]:+.3f} to {SLOPE_SINGLE[2]:+.3f}); "
                           f"workflow {SLOPE_WF[0]:+.3f} ({SLOPE_WF[1]:+.3f} to {SLOPE_WF[2]:+.3f})"),
    decide("H10", TINY["h10"], f"accuracy {TINY['wf_acc']:.2f} against {TINY['one_acc']:.2f}; cost {TINY['wf_cost']:.1f} against {TINY['one_cost']:.1f}¢"),
]
table(CLAIMS, [("id", "", ""), ("claim", "claim", ""), ("verdict", "verdict", "")])

#%% code
# FIG  the scorecard: every pre-registered claim and its verdict
fig, ax = plt.subplots(figsize=(10.4, 0.42 * len(CLAIMS) + 1.2))
vc = {"SUPPORTED": C3, "NOT SUPPORTED": C8, "REPORTED": MUTED}
for i, c in enumerate(CLAIMS):
    ax.add_patch(plt.Rectangle((0, i - 0.38), 1, 0.76, color=vc[c["verdict"]], alpha=0.85))
    ax.text(0.5, i, c["verdict"], ha="center", va="center", fontsize=7.5, color="white", weight="bold")
    ax.text(1.1, i, f"{c['id']}  {c['claim']}", va="center", fontsize=8.2)
ax.set_xlim(0, 9)
ax.set_ylim(len(CLAIMS) - 0.5, -0.5)
ax.axis("off")
n_sup = sum(c["verdict"] == "SUPPORTED" for c in CLAIMS)
finish(fig, "s69_claims", f"{n_sup} of {len(CLAIMS)} pre-registered claims SUPPORTED by rules fixed before the runs",
       "green: supported; red: not supported; grey: reported (the data the rule needed did not exist in this mode)")

#%% md
**Reading FIG {{figures.s69_claims}} (s69_claims).** {{claims.supported}} of {{claims.total}} claims were SUPPORTED, {{claims.not_supported}} NOT SUPPORTED and {{claims.reported}} REPORTED. Each verdict came from a rule written in S50 and applied by code; none was chosen after looking.

#%% md
## S70 - What is still open

Ranked by what the measurements say would move the results most:

1. **The stage that loses the most bugs** (S56): for the dynamic workflow, *{{errors.D_worst}}*, {{errors.D_worst_n|.1f}} bugs per run. Better readings there would move recall most.
2. **Memory** (S65): how much of the recall is recall from training. An unseen library, written for the purpose, would settle it.
3. **More runs**: three per arm gives wide intervals; ten would make NEUTRAL verdicts decisive one way or the other.
4. **Other model families**: every worker here came from one provider. The engine is model-agnostic; the numbers may not be.
5. **Real bugs**: S66's candidates deserve a person's review and, where real, a report upstream.

#%% code
save_exp("claims", {"rows": CLAIMS, "supported": n_sup, "total": len(CLAIMS), "not_supported": sum(c["verdict"] == "NOT SUPPORTED" for c in CLAIMS),
                    "reported": sum(c["verdict"] == "REPORTED" for c in CLAIMS)})
results = []
expect("every claim of the pre-registration has a verdict", {c["id"] for c in CLAIMS} == {h["id"] for h in PREREG["hypotheses"]})
