#%% md
# Part VII. Experiments, registered before they are run

**Where this sits.** Parts III to VI produced numbers: baselines, a fixed plan, the lead's own plans, nine feature cards. Numbers from runs of language models are noisy, and the person who builds a system is the person most tempted to read its numbers kindly. This Part guards against that in the way experimental science does. First the hypotheses and the rules that decide them are written down and fingerprinted. Then the comparisons are run. Then the rules are applied by code, and the verdicts are whatever the code says.

**By the end of this Part you can**

- write a pre-registration with rules a program can apply, and prove later that it was not changed;
- compare five designs of the same job run several times each, with intervals instead of single numbers;
- predict the wall clock of a plan you have not run, with a simulator checked against runs you have;
- turn feature measurements into verdicts, and explain every missed bug by the stage that lost it.

![part7](attachment:part7_map.png)

#%% md
## S50 - Pre-registration

**Theory.** A **pre-registration** fixes, before the data that decides them exists, three things: the claims, the measurements, and the rule that turns measurements into a verdict. It protects against the most common way honest people fool themselves, which is choosing the test after seeing the result. Ours is a Python dictionary written to a file, with a SHA-256 fingerprint printed here. Every later section that applies a rule reads the file again and checks the fingerprint, so a rule changed after the fact would fail loudly.

Two limits are worth saying plainly. The rules below were written into the plan of this notebook before any paid call was made, but the fixed plan's runs (S32) and the lead's first plan (S39) already exist when this cell runs, so this is a pre-registration of the *comparisons*, not of every measurement. And a fingerprint proves the file did not change during a run of the notebook, not that it was not edited between runs; the committed history of the repository is the record for that.

**In plain terms.** We write down what we expect and how we will decide, lock it with a fingerprint, and only then look at the comparisons.

**For teams.** Before an evaluation that will decide a launch, write the success rule in a file, get it reviewed, and have the evaluation code read the rule from that file. Arguments about the rule then happen before the results, not after.

#%% code
PREREG = {
    "title": "Dynamic workflows against one agent and against a fixed plan, on a 72-bug planted audit",
    "arms": {"A": "one agent alone with tools, 150 turns (S17), three runs",
             "A2": "one agent alone with as many turns as the median dynamic run's cents buy, two runs",
             "B": "a lead calling helpers one at a time (S19), one run",
             "C": "the fixed plan: three lenses, three skeptics with evidence, report (S32), three runs",
             "D": "the dynamic workflow: the lead writes a new plan program for each run (S39 and S52), three runs"},
    "metrics": {"recall": "planted bugs matched by the final report / 72",
                "precision": "distinct matched places / (distinct matched + distinct unmatched places)",
                "spread": "max minus min recall over an arm's runs",
                "cost": "cents at full price, counting calls the ledger answered",
                "wall clock": "seconds from a run's first to its last event, as recorded when it was paid for"},
    "statistics": "95% percentile bootstrap intervals, 2,000 resamples, over planted bugs for recall and over reported places "
                  "for precision, runs resampled within each arm, seed 42",
    "hypotheses": [
        {"id": "H1", "claim": "the dynamic workflow finds more planted bugs than one agent alone",
         "rule": "min recall(D) > max recall(A) and the interval of mean recall(D) - mean recall(A) excludes 0"},
        {"id": "H1b", "claim": "the same holds against one agent given the same budget",
         "rule": "min recall(D) > max recall(A2) and the interval of mean recall(D) - mean recall(A2) excludes 0"},
        {"id": "H2", "claim": "the dynamic workflow is more consistent from run to run",
         "rule": "spread(D) < spread(A)"},
        {"id": "H3", "claim": "the dynamic workflow is not much less precise than one agent",
         "rule": "the lower bound of the interval of mean precision(D) - mean precision(A) is at least -0.10"},
        {"id": "H4", "claim": "verification buys precision at little cost in recall",
         "rule": "for 2 of 3 skeptics against no verification: the lower bound of the precision gain is at least 0.15 "
                 "and the upper bound of the recall loss is at most 0.05"},
        {"id": "H5", "claim": "a second round of scanning finds more planted bugs",
         "rule": "adding the next fixed-plan run's scan to a run's scan adds at least 3 planted bugs at the scan stage, "
                 "in at least 2 of the 3 runs"},
        {"id": "H6", "claim": "executable evidence makes skeptics more accurate",
         "rule": "the lower bound of the interval of accuracy with evidence - accuracy without is above 0"},
        {"id": "H7", "claim": "a pipeline finishes sooner than a barrier for the same calls",
         "rule": "simulated pipeline wall clock <= 0.8 x simulated barrier wall clock for the fixed plan, from recorded latencies"},
        {"id": "H8", "claim": "a crashed run resumes without paying twice",
         "rule": "after a cancel and a resume, the final report equals that of an uninterrupted run and no call was paid twice"},
        {"id": "H9", "claim": "one agent grading a long list gets worse further down; the workflow does not",
         "rule": "the interval of one agent's accuracy-against-position slope is below 0, and the workflow's includes 0 (Part VIII)"},
        {"id": "H10", "claim": "on a tiny job, the workflow is no better and costs more",
         "rule": "workflow accuracy <= one agent's accuracy + 0.02 and workflow cost > one agent's cost (Part VIII)"},
    ],
    "verdicts": "SUPPORTED when the rule holds, NOT SUPPORTED when it does not, REPORTED when the data the rule needs does not exist",
}
PREREG_PATH = ART / "preregistration.json"
PREREG_PATH.write_text(json.dumps(PREREG, indent=1, sort_keys=True), encoding="utf-8")
PREREG_SHA = hashlib.sha256(PREREG_PATH.read_bytes()).hexdigest()
print(f"[prereg] {len(PREREG['hypotheses'])} hypotheses, {len(PREREG['arms'])} arms, written to {rel(PREREG_PATH)}")
print(f"[prereg] fingerprint {PREREG_SHA}")
for h in PREREG["hypotheses"]:
    print(f"  {h['id']:<4} {h['claim']}")

#%% md
**`rule_of_record(hid)`** is how every later section gets a rule: it re-reads the file, checks the fingerprint, and returns the hypothesis. If anyone edits the file while the notebook runs, every verdict after that point fails instead of quietly using the new rule.

#%% code
def rule_of_record(hid):
    """The pre-registered hypothesis `hid`, read from the file after checking its fingerprint."""
    data = PREREG_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != PREREG_SHA:
        raise RuntimeError("the pre-registration file changed after it was fingerprinted")
    return next(h for h in json.loads(data)["hypotheses"] if h["id"] == hid)

show_def(rule_of_record)
print(f"[prereg] H4 as read back: {rule_of_record('H4')['rule']}")
saved = PREREG_PATH.read_bytes()
PREREG_PATH.write_bytes(saved.replace(b"0.15", b"0.05"))              # a quiet edit, made on purpose
try:
    rule_of_record("H4")
    tamper_caught = False
except RuntimeError as e:
    tamper_caught = True
    print(f"[prereg] after a one-character edit: {e}")
PREREG_PATH.write_bytes(saved)
results = []
expect("an edited pre-registration is refused", tamper_caught)
expect("the restored file passes its fingerprint again", rule_of_record("H1")["id"] == "H1")
save_exp("prereg", {"sha256": PREREG_SHA, "hypotheses": len(PREREG["hypotheses"]), "arms": list(PREREG["arms"])})

#%% md
## S51 - The runner and the contamination guard

**Theory.** A comparison between arms is only fair if no arm had an advantage the others lacked, and the most dangerous advantage in a planted-bug benchmark is a glimpse of the answer key. Three things are checked here. Every instruction any arm used is listed with its fingerprint, so a reader can see exactly what each arm was told. No request sent to any model contains the path of the hidden folder or the name of the key file. And every shard a scan worker read is, character for character, the audited files rendered with line numbers, so the workers saw exactly the code the scorer assumes they saw.

**In plain terms.** Before comparing, we check that nobody peeked: what each arm was told, and what each worker was shown.

**For teams.** Fingerprint your prompts and log them with your results. When two runs disagree, the first question is whether they were asked the same thing.

#%% code
INSTRUCTIONS = {"A, A2": {"solo system": SOLO_SYSTEM}, "B": {"sequential lead": LEAD_SEQ_SYSTEM},
                "C, D": {"scan": SCAN_SYSTEM, **{f"lens {l}": LENS_TEXT[l] for l in LENSES}, "skeptic": SKEPTIC_SYSTEM, "report": REPORT_SYSTEM},
                "D": {"lead program": LEAD_PROGRAM_SYSTEM, "memo": MEMO_SYSTEM}}
INSTR_ROWS = [{"arm": arm, "instruction": name, "tokens": est_tokens(text), "sha256": hashlib.sha256(text.encode()).hexdigest()[:16]}
              for arm, d in INSTRUCTIONS.items() for name, text in d.items()]
table(INSTR_ROWS, [("arm", "arms", ""), ("instruction", "instruction", ""), ("tokens", "tokens", "d"), ("sha256", "fingerprint", "")])

#%% md
**`request_texts(roles)`** reads back, from the ledger's blob store, every message we sent under the given roles: the instructions and the user turns, including every tool result an agent was shown. The models' own replies are left out, because an agent that *asks* for a hidden file is not a leak; the path guard refuses it, and the refusal is what the next user turn contains.

#%% code
def request_texts(roles):
    """Every message we sent (system and user, not the models' own replies) for calls of these roles, from the blob store."""
    marks = ",".join("?" * len(roles))
    out = []
    for (req,) in FRONT_DOOR.ledger.query(f"SELECT request FROM calls WHERE role IN ({marks})", tuple(roles)):
        for m in json.loads(req)["messages"]:
            if m["role"] != "assistant":
                out.append(FRONT_DOOR.ledger._unblob(m["content"][len("blob:"):]) or "")
    return out


def shard_is_audited(text):
    """True when a scan request's shard is exactly the audited files it names, rendered with line numbers."""
    paths = re.findall(r"^### (\S+)$", text, re.M)
    return bool(paths) and all(p in CORPUS for p in paths) and text.strip() == render_shard(paths).strip()

show_def(request_texts, shard_is_audited)
FINDER_ROLES = ["scan", "solo", "skeptic", "report", "lead", "critic"]
texts = request_texts(FINDER_ROLES)
leaks = [t for t in texts if "/hidden/" in t or "answer_key" in t or "clean_hidden" in t]
scan_users = [t for t in set(request_texts(["scan"])) if t.lstrip().startswith("###")]
bad_shards = [t for t in scan_users if not shard_is_audited(t)]
print(f"[guard] {len(texts):,} messages checked across roles {', '.join(FINDER_ROLES)}: {len(leaks)} mention the hidden folder or the key")
print(f"[guard] {len(scan_users)} distinct shards sent to scan workers: {len(bad_shards)} differ from the audited files")
results = []
expect("no message to any model mentions the hidden folder or the answer key", not leaks)
expect("every shard a scan worker read is exactly the audited code", not bad_shards and len(scan_users) > 0)
expect("the arms' instructions are fingerprinted", len(INSTR_ROWS) == sum(len(d) for d in INSTRUCTIONS.values()))
save_exp("guard", {"messages": len(texts), "leaks": len(leaks), "shards": len(scan_users), "bad_shards": len(bad_shards),
                   "instructions": INSTR_ROWS})
