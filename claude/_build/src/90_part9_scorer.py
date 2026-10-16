#%% md
# Part IX. Checking our own work

**Where this sits.** Every number so far came from code we wrote: a scorer, judges, a planting procedure, a sandbox. Each of them can be wrong in ways that make the results look better, or worse, than they are. This Part turns the same scepticism on the notebook itself. It audits the scorer with executable evidence, measures every model that served as a judge against the key, probes whether the models simply remember the library, looks for real bugs we did not plant, lists the bugs we made while building all this, and ends with the claims that survive and the questions that stay open.

**By the end of this Part you can**

- audit an automatic scorer without reading its decisions by hand, by running the code;
- tell whether a benchmark measures reasoning or memory;
- write a threats-to-validity section that names numbers, not just categories.

![part9](attachment:part9_map.png)

#%% md
## S63 - Was the scorer right?

**Theory.** The scorer of S4 decides that a finding "matches" a planted bug when it names the same file, the same function, and a line within five of the bug. That rule can be wrong both ways. A finding can match by position and be about something else in the same function, and a finding can describe the planted bug exactly while pointing at a line further away. Reading hundreds of decisions by hand would be slow and subjective. There is a better witness: the code itself. Every finding carries a failing call. Run that call on the **original** file and on the **audited** file. If the two disagree, the call exposes the planted change, and the finding is about the planted bug whatever line it named. If they agree, the call cannot see the planted change.

**`run_call_in(root, path, expr)`** is the sandbox of S15 pointed at a chosen tree. It is a tool for the auditor, never given to an agent, because the original tree holds the answer.

**In plain terms.** For each finding, run its example on the code before and after the bug was planted. If the answers differ, the finding really was about the planted bug.

**For teams.** When an automatic metric decides what counts, audit it with a second, independent signal. Executable checks are the cheapest independent signal there is.

#%% code
def run_call_in(root, path, expr, timeout=8):
    """The sandbox of S15, run against the file in `root` (an auditor's tool; agents only ever reach the audited tree)."""
    src = (Path(root) / path).read_text(encoding="utf-8")
    names = {n.name for n in ast.parse(src).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    try:
        check_call(expr, names)
    except (CallRejected, SyntaxError):
        return {"ok": False, "error": "rejected"}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = subprocess.run([sys.executable, *CLEAN_FLAGS, "-c", CALL_RUNNER, str(Path(root).resolve()), path], input=expr,
                               capture_output=True, text=True, timeout=timeout, env=CLEAN_ENV, cwd=tmp, preexec_fn=_limits)
            return json.loads((p.stdout.strip().splitlines() or ['{"ok": false, "error": "no output"}'])[-1])
        except (subprocess.TimeoutExpired, ValueError):
            return {"ok": False, "error": "timeout or unreadable"}


def exposes_change(f):
    """True when the finding's failing call behaves differently on the original and the audited file; None when it cannot run."""
    if not f.get("failing_call") or f["file"] not in CORPUS:
        return None
    a, b = run_call_in(ORIGINAL, f["file"], f["failing_call"]), run_call_in(AUDITED, f["file"], f["failing_call"])
    if a.get("error") == "rejected" or b.get("error") == "rejected":
        return None
    return (a.get("value"), a.get("error", "")[:40]) != (b.get("value"), b.get("error", "")[:40])

show_def(run_call_in, exposes_change)
print(f"[audit] the planted bug of S31 through its hidden example: exposes the change: {exposes_change(good_finding)}")
print(f"[audit] a correct function's own example: exposes a change: {exposes_change(wrong_finding)}")

#%% md
**The audit.** Every distinct place reported by the dynamic workflow's runs, in the file of a planted bug, is checked: matched places, and unmatched places within twenty lines of a bug. A matched place whose call exposes the change confirms the scorer; an unmatched place whose call exposes the change is a detection the scorer missed. Places whose calls cannot run (no call, or a call the fence refuses) are counted apart.

#%% code
def audit_places(kits):
    """One row per distinct reported place in a planted file: scorer decision against the executable witness."""
    bug_files = {b["path"]: b for b in ANSWER_KEY}
    rows, seen = [], set()
    for kit in kits:
        for f in dedupe(kit.trace["found"]):
            b = bug_files.get(f["file"])
            if b is None or key_of(f) in seen or abs(int(f.get("line") or 0) - b["line"]) > 20:
                continue
            seen.add(key_of(f))
            rows.append({"place": key_of(f), "matched": bool(match(as_findings([f]), key=[b]).tp), "witness": exposes_change(f),
                         "distance": abs(int(f.get("line") or 0) - b["line"])})
    return rows

show_def(audit_places)
AUDIT = audit_places([k for _, k, _ in [o for o in D_OBJS if o]])
cm = collections.Counter((r["matched"], r["witness"]) for r in AUDIT)
AUDIT_SUM = {"places": len(AUDIT), "matched_confirmed": cm[(True, True)], "matched_silent": cm[(True, False)], "matched_unrunnable": cm[(True, None)],
             "missed_by_scorer": cm[(False, True)], "unmatched_silent": cm[(False, False)], "unmatched_unrunnable": cm[(False, None)]}
table([{"decision": "matched by the scorer", "exposes": cm[(True, True)], "silent": cm[(True, False)], "cannot run": cm[(True, None)]},
       {"decision": "not matched (within 20 lines)", "exposes": cm[(False, True)], "silent": cm[(False, False)], "cannot run": cm[(False, None)]}],
      [("decision", "scorer said", ""), ("exposes", "call exposes the planted change", "d"), ("silent", "call cannot see it", "d"),
       ("cannot run", "call cannot run", "d")])

#%% md
**Sensitivity.** The other half of the audit: how much the recall depends on the window. **`sensitivity`** from S4 re-scores the dynamic workflow's final reports under windows from 0 to 10 lines, under "same function, any line", and under "within 5 lines, any function".

#%% code
SENS = {f"D run {row['run']}": sensitivity(as_findings(objs[2]["bugs"])) for objs, row in zip(D_OBJS, D_RUNS) if objs}
first_key = next(iter(SENS))
table([{"rule": r["rule"], **{k: v[i]["recall"] for k, v in SENS.items()}} for i, r in enumerate(SENS[first_key])],
      [("rule", "matching rule", "")] + [(k, k, ".3f") for k in SENS])

#%% code
# FIG  auditing the scorer: by running the code, and by moving the window
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6), gridspec_kw={"width_ratios": [1, 1.4]})
ax = axes[0]
cats = [("matched,\nexposes", cm[(True, True)], C3), ("matched,\nsilent", cm[(True, False)], C4), ("unmatched,\nexposes", cm[(False, True)], C8),
        ("unmatched,\nsilent", cm[(False, False)], MUTED)]
ax.bar([c[0] for c in cats], [c[1] for c in cats], color=[c[2] for c in cats])
ax.set_ylabel("distinct reported places")
panel(ax, "scorer against the executable witness")
ax = axes[1]
for (name, rows), colour in zip(SENS.items(), (C7, C1, C2)):
    ws = [r for r in rows if r["rule"].startswith("same function, within")]
    ax.plot([int(r["rule"].split("within ")[1].split(" ")[0]) for r in ws], [r["recall"] for r in ws], "o-", color=colour, label=name, ms=4)
ax.axvline(5, color=INK2, ls=":", lw=1)
ax.text(5, 0.02, " the rule used", fontsize=7.5, color=INK2)
ax.set_xlabel("line window (same function)")
ax.set_ylabel("recall")
ax.set_ylim(0, 1)
ax.legend(fontsize=7.5)
panel(ax, "recall under other windows")
finish(fig, "s63_scorer_audit", f"Of {AUDIT_SUM['places']} reported places near planted bugs, the scorer missed {AUDIT_SUM['missed_by_scorer']} "
       f"that the code says were real detections", "left: distinct places of the dynamic workflow's runs within 20 lines of a planted bug; "
       "right: recall of its final reports under windows from 0 to 10 lines")

#%% md
**Reading FIG {{figures.s63_scorer_audit}} (s63_scorer_audit).** Left: of the {{scorer_audit.places}} distinct places the workflow reported near a planted bug, {{scorer_audit.matched_confirmed}} were matched by the scorer and confirmed by their own call, which behaved differently on the original and the audited file. {{scorer_audit.missed_by_scorer}} were not matched but their call exposed the planted change: those are detections the line rule missed, and they bound how much the reported recall could be too low. {{scorer_audit.matched_silent}} were matched although their call could not see the change; a call that does not reach the bug does not make the finding wrong, but it is the place to look for lucky matches. Right: recall under every window from 0 to 10 lines. The curve is flat around the rule's 5 lines, so the results do not hang on that choice.

#%% code
save_exp("scorer_audit", {**AUDIT_SUM, "sensitivity": SENS})
results = []
expect("the witness confirms the planted bug's hidden example and clears a correct function's", exposes_change(good_finding) is True
       and exposes_change(wrong_finding) is False)
expect("every audited place was put in exactly one cell", sum(cm.values()) == len(AUDIT))

#%% md
## S64 - Judges that must earn their votes

**Theory.** Several models served as judges in this notebook: the skeptics of the audit, the second readers of the homework, the finders' own model when it judged itself. A judge's vote is only worth what its accuracy is, and accuracy can only be known against a key. Here every judge used so far is measured on the same footing: the share of its verdicts that the key agrees with, its rate of calling a wrong thing right and a right thing wrong, and its agreement with the other judges beyond chance.

**In plain terms.** Before trusting a model as a referee, check its record on cases where the answer is known.

#%% code
JUDGES = [{"judge": f"audit skeptic, {MODELS['judge'].split('/')[-1]}, with evidence", **accuracy(WITH_EV)},
          {"judge": f"audit skeptic, {MODELS['judge'].split('/')[-1]}, no evidence", **accuracy(WITHOUT_EV)},
          {"judge": f"audit skeptic, {MODELS['worker'].split('/')[-1]} (the finders' model)", **accuracy(SAME_GEN)}]
for lens in HW_LENS_TEXT:
    rows = [{"key": g["id"], "real": g["wrong"], "planted": HW_KEY[g["id"]]["wrong"]} for g in HW_KIT.trace["rechecked"]
            if g.get("lens") == lens and g.get("wrong") is not None]
    if rows:
        JUDGES.append({"judge": f"homework second look, {lens} lens", **accuracy(rows)})
table(JUDGES, [("judge", "judge", ""), ("n", "verdicts", "d"), ("accuracy", "accuracy", ".2f"), ("tpr", "wrong called wrong", ".2f"),
               ("fpr", "right called wrong", ".2f")])

#%% code
# FIG  every judge's record against the key
fig, ax = plt.subplots(figsize=(9.6, 3.4))
y = np.arange(len(JUDGES))
ax.barh(y - 0.2, [j["accuracy"] for j in JUDGES], 0.4, color=C1, label="accuracy")
ax.barh(y + 0.2, [j["fpr"] for j in JUDGES], 0.4, color=C8, label="false alarms (right called wrong)")
ax.set_yticks(y, [j["judge"] for j in JUDGES], fontsize=7.5)
ax.invert_yaxis()
ax.set_xlim(0, 1)
ax.legend(fontsize=7.5, loc="lower right")
best_j = max(JUDGES, key=lambda j: j["accuracy"])
finish(fig, "s64_judges", f"The most accurate judge was the {best_j['judge']} ({best_j['accuracy']:.2f})",
       "every verdict each judge gave in this notebook, against the answer keys of the audit and the homework")

#%% md
**Reading FIG {{figures.s64_judges}} (s64_judges).** Each pair of bars is one judge: accuracy in blue, false alarms in red. The most accurate was the {{judge_record.best}} ({{judge_record.best_acc|.2f}}). Accuracy alone can flatter a judge: the homework lens saw only solutions the calculator had flagged, most of them really wrong, and in the live run it called every one of them wrong, right ones included, so its false-alarm rate was 1.00. A judge whose false-alarm rate is high wastes the work of everything downstream, because the items it wrongly calls bad are the ones the next step spends calls on. Judges without a measured record like this should not get a vote.

#%% code
save_exp("judge_record", {"rows": JUDGES, "best": best_j["judge"], "best_acc": best_j["accuracy"]})
