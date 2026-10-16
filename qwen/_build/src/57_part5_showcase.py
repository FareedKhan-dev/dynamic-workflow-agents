#%% md
## S39 - The showcase run, end to end

**Theory.** This section runs the whole idea once, start to finish, the way it is meant to be used:

1. the **scout** writes the page about the job;
2. the **lead** writes a plan program for it;
3. the program passes the **whitelist** and the **dry run**, which prices it;
4. the **approval gate** decides, and a person is asked if the price calls for one;
5. the plan **runs in the background** on the runtime of Part IV, under a **job budget** carved out of the session budget, while the lead is free;
6. one **combined result** comes back, and the lead writes a **memo** about it for the people who asked.

A **job budget** is a share of the session budget with its own cap. A call must fit both. The session budget pauses at its cap and waits for a person to raise it (S26); a job budget **refuses** instead, because an automated run inside a job has nobody standing by to raise anything, and a run that waits forever is worse than one that stops and says why.

**In plain terms.** The lead plans, a checker and a rehearsal approve the plan, the work runs on its own, and the lead reads one result and writes a short report about it.

**For teams.** This is the shape to copy: plan, check, price, approve, run in the background, collect one result, summarise. Every step leaves a record: the page, the program, the estimate, the decision, the events, the threads, the result and the memo.

#%% code
class JobBudget(Budget):
    """A job's share of a parent budget: a call must fit both; at the job's own cap it is refused, not paused."""

    def __init__(self, parent, cap):
        super().__init__(cap)
        self.parent, self.refused = parent, 0

    def admit(self, cost, who=""):
        with self.cond:
            if self.spent + self.reserved + cost > self.cap + 1e-9:
                self.refused += 1
                raise SpendRefused(f"the job budget of {self.cap:.0f} Magicubes is used up")
            self.reserved += cost
        try:
            self.parent.admit(cost, who)                 # the session cap may still pause this call
        except BaseException:
            with self.cond:
                self.reserved -= cost
            raise

    def settle(self, reserved, actual):
        Budget.settle(self, reserved, actual)
        self.parent.settle(reserved, actual)


def job_door(cap):
    """A front door that shares the ledger and client of FRONT_DOOR but charges a job budget of `cap`."""
    door = LLM(FRONT_DOOR.mode, FRONT_DOOR.ledger, FRONT_DOOR.client, FRONT_DOOR.scripted)
    door.budget = JobBudget(FRONT_DOOR.budget or Budget(CAP_MAGICUBES), cap)
    return door

show_def(JobBudget, job_door)
jb = JobBudget(Budget(10.0), 1.0)
jb.admit(0.6)
jb.settle(0.6, 0.6)
try:
    jb.admit(0.6)
    refused = False
except SpendRefused as e:
    refused = True
    print(f"[job budget] {e}; the parent spent {jb.parent.spent:.1f} and still has its cap of {jb.parent.cap:.0f}")

#%% md
**Steps 1 to 4: page, program, gates, decision.** The job budget is 150 Magicubes. The lead writes the program with sample 0. If the gate holds the plan, the notebook plays the person: its standing rule, written here before the estimate is known, is to approve any plan whose estimate is at most half the job budget.

#%% code
SHOW_BUDGET = 150
SHOW_READ_FROM = len(LEAD.read)                       # everything the lead reads for this job is counted from here
SHOW_PAGE = scout_text(scout(SHOW_BUDGET))
SHOW = LEAD.write_program(JOB, SHOW_PAGE, sample=0, budget_mc=SHOW_BUDGET)
print(SHOW["src"])
SHOW_EST = SHOW["estimate"]
DECISION, WHY = approve(SHOW_EST, SHOW_BUDGET)
if DECISION == "held":
    DECISION, WHY = approve(SHOW_EST, SHOW_BUDGET, person=lambda est: est["magicubes"] <= SHOW_BUDGET / 2)
print(f"\n[showcase] valid after {SHOW['tries']} attempt(s); estimate {SHOW_EST['agents']} workers, {SHOW_EST['calls']} calls, "
      f"{SHOW_EST['magicubes']:.1f} MC, about {SHOW_EST['minutes']:.0f} min; gate: {DECISION} ({WHY})")

#%% md
**Step 5: run it in the background.** The run starts on its own thread. The notebook's thread is the lead now: it prints the status line at every new phase and every few seconds, and in between it drafts the parts of its memo that do not depend on the result.

#%% code
SHOW_RUN = Run("showcase: the lead's own plan", JOB, run_id="d-showcase-0", llm=job_door(SHOW_BUDGET), concurrency=32)
SHOW_KIT = AuditKit(SHOW_RUN, number=0)
assert DECISION == "approved", "the showcase plan was not approved"
SHOW_RUN.start(lambda r: run_program(SHOW["src"], SHOW_KIT))
memo_draft, last_phase, last_t = [f"Job: {JOB}", f"Plan: {len(SHOW['src'].splitlines())} lines, {SHOW_EST['agents']} workers estimated."], None, -99.0
while SHOW_RUN.status in ("created", "running"):
    now = SHOW_RUN.elapsed()
    if len(SHOW_RUN.phases) != last_phase or now - last_t >= 30:
        print("  " + SHOW_RUN.statusline())
        last_phase, last_t = len(SHOW_RUN.phases), now
    time.sleep(0.2)
SHOW_RESULT = SHOW_RUN.wait()
SHOW_KIT.save()
print("  " + SHOW_RUN.statusline())
SHOW_OUT = outcome(SHOW_RESULT, SHOW_KIT)
SHOW_FULL = full_price(SHOW_RUN)
print(f"[showcase] {SHOW_RUN.status}: {SHOW_OUT['bugs_reported']} bugs reported; scored against the hidden key: recall {SHOW_OUT['recall']:.2f}, "
      f"precision {(SHOW_OUT['precision'] or 0):.2f}")
print(f"[showcase] {SHOW_OUT['calls']} calls worth {SHOW_FULL:.1f} MC at full price against an estimate of {SHOW_EST['magicubes']:.1f}; "
      f"{SHOW_OUT['magicubes']:.1f} MC paid now, the rest answered by the ledger; the job budget refused {SHOW_RUN.llm.budget.refused} calls")

#%% md
**Step 6: the memo.** The lead reads the combined result, never the code and never the answer key, and writes a memo for the team that asked: what was found, how sure the audit is, what it did not cover, and what to do next. The memo instruction asks for plain language and no claims the result cannot support.

#%% code
MEMO_SYSTEM = """You are the lead of a code audit that has just finished. Write a memo of at most 220 words for the engineers who own the library.

Say what was found, ranked by severity, naming the most important files and functions. Say how the findings were checked. Say what the audit did not cover. End with two or three concrete next steps. Use plain sentences, no headings beyond 'Found', 'How it was checked', 'Not covered' and 'Next', and no claims the result below does not support."""


@method_of(Lead)
def memo(self, job, result, stats, sample=0):
    bugs = "\n".join(f"- [{b['severity']}] {b['file']}:{b['line']} {b['function']}: {b['title'] or b['claim']}"[:220]
                     for b in (result or {}).get("bugs", [])[:60])
    user = (f"THE JOB\n{job}\n\nTHE RESULT\n{len((result or {}).get('bugs', []))} confirmed bugs:\n{bugs}\n\nNot covered: "
            f"{'; '.join((result or {}).get('not_covered', [])) or 'nothing reported'}\nSummary from the report: {(result or {}).get('summary', '')}"
            f"\n\nTHE RUN\n{stats['agents']} workers, {stats['calls']} calls, {stats['full_price']:.1f} Magicubes at full price, "
            f"every file read: {stats['coverage'] == 1.0}; findings were confirmed by independent skeptics with sandbox evidence.")
    r = self.ask([{"role": "system", "content": MEMO_SYSTEM}, {"role": "user", "content": user}], f"lead:memo#{sample}", sample, max_tokens=3000)
    return r.text.strip()


@SCRIPTED.register
def _memo(model, messages, params):
    if not messages[0]["content"].startswith("You are the lead of a code audit that has just finished"):
        return None
    n = re.search(r"(\d+) confirmed bugs", messages[-1]["content"])
    return (f"Found\nThe audit confirmed {n.group(1) if n else 'several'} bugs. (This memo was written by the scripted stand-in.)\n\n"
            "How it was checked\nIndependent skeptics with sandbox evidence.\n\nNot covered\nNothing reported.\n\nNext\nFix the high-severity bugs first.")

show_def(Lead.memo, _memo)
SHOW_MEMO = LEAD.memo(JOB, SHOW_RESULT, dict(SHOW_OUT, full_price=SHOW_FULL))   # full price: the same in a paid run and a replay
print(SHOW_MEMO)
print(f"\n[memo] {len(SHOW_MEMO.split())} words")

#%% code
# FIG  the showcase run, drawn from its events
portrait(SHOW_RUN, name="s39_portrait", title=f"The lead's own plan, run end to end: {SHOW_OUT['agents']} workers in {len(SHOW_RUN.phases)} phases",
         sub=f"recall {SHOW_OUT['recall']:.2f} and precision {(SHOW_OUT['precision'] or 0):.2f} against the hidden key; "
             f"{SHOW_FULL:.1f} Magicubes at full price, of a job budget of {SHOW_BUDGET}")

#%% md
**Reading FIG {{figures.s39_portrait}} (s39_portrait).** The portrait of the lead's own plan, drawn from its events like every run since S30. Each lane is one of its {{showcase.agents}} workers, coloured by phase. The plan used {{showcase.features}}. It reported {{showcase.bugs_reported}} bugs, and scored against the hidden key it reached a recall of {{showcase.recall|.2f}} and a precision of {{showcase.precision|.2f}}. Its calls were worth {{showcase.full_price|.1f}} Magicubes at full price, against an estimate of {{showcase.estimate|.1f}}; {{showcase.magicubes|.1f}} of them were paid in this run, because calls the plan shared with earlier runs came from the ledger.

#%% md
**What the lead had to read.** One agent alone (S17) carried the code it read in its own context, and its context grew turn after turn until compaction erased detail. The lead read three things: the scout's page, its own plan attempts, and the combined result. The figure puts the two side by side.

#%% code
LEAD_TOKENS = LEAD.read[SHOW_READ_FROM:]
solo_ctx = [t.context_tokens for t in SOLO[0].turns]
solo_total = sum(t.prompt_tokens for t in SOLO[0].turns)
print(f"[context] the lead read {sum(n for _, n in LEAD_TOKENS):,} tokens in {len(LEAD_TOKENS)} calls; one agent alone read "
      f"{solo_total:,} prompt tokens in {len(solo_ctx)} turns, with up to {max(solo_ctx):,} in context at once")

#%% code
# FIG  what the lead read, against what one agent alone had to carry
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.4), gridspec_kw={"width_ratios": [1.6, 1]})
ax = axes[0]
ax.plot(range(1, len(solo_ctx) + 1), solo_ctx, color=MUTED, lw=1.5, label="one agent alone: context at each turn")
ax.axhline(max(n for _, n in LEAD_TOKENS), color=C7, lw=2, label="the lead: largest single call")
ax.set_xlabel("turn of the single agent")
ax.set_ylabel("tokens in context")
ax.legend(fontsize=7.5)
panel(ax, "context over time")
ax = axes[1]
vals = [solo_total, sum(n for _, n in LEAD_TOKENS)]
ax.bar(["one agent alone,\nall turns", "the lead,\nall calls"], vals, color=[MUTED, C7])
ax.set_yscale("log")
ax.set_ylabel("tokens read in total (log scale)")
for i, v in enumerate(vals):
    ax.text(i, v * 1.15, f"{v:,}", ha="center", fontsize=8)
panel(ax, "everything read")
finish(fig, "s39_lead_context", f"The lead read {vals[1] / max(vals[0], 1):.1%} of what one agent alone read, and never the code",
       "the lead's calls: plan attempts and the memo; one agent alone: run 1 of S17")

#%% md
**Reading FIG {{figures.s39_lead_context}} (s39_lead_context).** Left: one agent alone carried more and more code in its context, turn after turn, and was cut back by compaction; the lead's largest single call is the horizontal line. Right: in total, the lead read {{showcase.lead_tokens}} tokens, against {{showcase.solo_tokens}} for one agent alone, and none of them were code. This is the structural reason the workflow scales where one agent stalls. The lead's context holds the plan and the result; the reading happens in the workers' fresh contexts, each the size S13 measured.

#%% code
SHOW_FEATURES = features(SHOW["src"])
save_exp("showcase", {**{k: v for k, v in SHOW_OUT.items() if k != "found_ids"}, "found_ids": SHOW_OUT["found_ids"], "full_price": SHOW_FULL,
                      "estimate": SHOW_EST["magicubes"], "estimate_agents": SHOW_EST["agents"], "decision": DECISION, "why": WHY,
                      "tries": SHOW["tries"], "features": ", ".join(SHOW_FEATURES) or "nothing a data plan could not say",
                      "program": SHOW["src"], "memo": SHOW_MEMO, "memo_words": len(SHOW_MEMO.split()),
                      "lead_tokens": sum(n for _, n in LEAD_TOKENS), "solo_tokens": solo_total, "budget": SHOW_BUDGET})
results = []
expect("a job budget refuses at its own cap and leaves the parent untouched", refused and jb.parent.spent == 0.6)
expect("the showcase plan passed both gates and the approval", SHOW["valid"] and DECISION == "approved")
expect("the showcase run completed in the background", SHOW_RUN.status == "completed")
expect("the showcase read every file", SHOW_OUT["coverage"] == 1.0)
lead_texts = [FRONT_DOOR.ledger._unblob(m["content"][len("blob:"):]) or "" for (req,) in
              FRONT_DOOR.ledger.query("SELECT request FROM calls WHERE role = 'lead' AND phase = 'planning'") for m in json.loads(req)["messages"]]
expect("the lead never read the code: none of its messages holds a numbered code line",
       len(lead_texts) > 0 and not any(re.search(r"^ {0,4}\d+\| ", t, re.M) for t in lead_texts))
expect("the memo exists and stays near its word limit", 0 < len(SHOW_MEMO.split()) <= 300)

#%% md
## S40 - Same task, smaller budget

**Theory.** A lead that plans from a page of facts should change its plan when the facts change. The cleanest fact to change is the budget. Here the lead writes a plan for the same job with the same sample index three times, with job budgets of 20, 60 and 150 Magicubes. The 150 plan is the showcase. The other two are checked, rehearsed and run under their job budgets. A good lead spends less when it has less, and the interesting question is what it gives up first.

**In plain terms.** Give the lead less money and see whether its plan shrinks sensibly.

**For teams.** Put the budget on the planner's page. A plan that ignores the budget is a plan that will be refused at the gate or stopped at the cap.

#%% code
BUDGET_ROWS = []
for cap in (20, 60, SHOW_BUDGET):
    if cap == SHOW_BUDGET:
        w, run, out = SHOW, SHOW_RUN, SHOW_OUT
    else:
        w = LEAD.write_program(JOB, scout_text(scout(cap)), sample=0, budget_mc=cap)
        decision, why = approve(w["estimate"], cap, person=lambda est, cap=cap: est["magicubes"] <= cap / 2)
        if not (w["valid"] and decision == "approved"):
            BUDGET_ROWS.append({"budget": cap, "valid": w["valid"], "decision": decision})
            continue
        run, kit, result, out = run_plan(w["src"], f"d-budget-{cap}", number=0, llm=job_door(cap), title=f"the lead's plan for {cap} MC")
    BUDGET_ROWS.append({"budget": cap, "valid": w["valid"], "decision": "approved", "estimate": w["estimate"]["magicubes"],
                        "workers": out["agents"], "magicubes": out["magicubes"], "full_price": full_price(run),
                        "recall": out["recall"], "precision": out["precision"],
                        "features": ", ".join(features(w["src"])) or "-", "status": out["status"], "src": w["src"]})
table(BUDGET_ROWS, [("budget", "job budget", "d"), ("estimate", "estimate MC", ".1f"), ("full_price", "MC at full price", ".1f"),
                    ("magicubes", "MC paid now", ".1f"),
                    ("workers", "workers", "d"), ("recall", "recall", ".2f"), ("precision", "precision", ".2f"), ("features", "uses", "")])
for r in BUDGET_ROWS:
    if "src" in r and r["budget"] != SHOW_BUDGET:
        print(f"\n--- the plan for {r['budget']} Magicubes\n{r['src']}")

#%% code
# FIG  the same job at three budgets: what the plan spent and what it found
ran = [r for r in BUDGET_ROWS if "recall" in r]
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.4))
ax = axes[0]
ax.plot([r["budget"] for r in ran], [r["full_price"] for r in ran], "o-", color=C1, label="cost at full price")
ax.plot([r["budget"] for r in ran], [r["estimate"] for r in ran], "s--", color=C7, label="estimated")
ax.plot([0, max(r["budget"] for r in ran)], [0, max(r["budget"] for r in ran) / 2], ":", color=INK2, lw=1, label="half the budget")
ax.set_xlabel("job budget (Magicubes)")
ax.set_ylabel("Magicubes")
ax.legend(fontsize=7.5)
panel(ax, "the plan's cost follows the budget")
ax = axes[1]
ax.plot([r["budget"] for r in ran], [r["recall"] for r in ran], "o-", color=C3, label="recall")
ax.plot([r["budget"] for r in ran], [r["precision"] or 0 for r in ran], "s-", color=C4, label="precision")
ax.set_ylim(0, 1)
ax.set_xlabel("job budget (Magicubes)")
ax.legend(fontsize=7.5)
panel(ax, "what the money bought")
finish(fig, "s40_budgets", f"With {ran[0]['budget']} Magicubes the lead's plan cost {ran[0]['full_price']:.1f} and found {ran[0]['recall']:.0%}; "
       f"with {ran[-1]['budget']} it cost {ran[-1]['full_price']:.1f} and found {ran[-1]['recall']:.0%}",
       "the same job, the same sample index, three job budgets on the scout's page")

#%% md
**Reading FIG {{figures.s40_budgets}} (s40_budgets).** Left: the lead's plans cost {{budgets.spent_small|.1f}}, {{budgets.spent_mid|.1f}} and {{budgets.spent_big|.1f}} Magicubes at full price at job budgets of 20, 60 and 150, each estimated before it ran. Right: what that bought, a recall of {{budgets.recall_small|.2f}}, {{budgets.recall_mid|.2f}} and {{budgets.recall_big|.2f}}. The plans printed above show what the lead gave up first when money was short. Nothing in the engine forced these choices: the only thing that changed was one line on the scout's page.

#%% code
by_cap = {r["budget"]: r for r in BUDGET_ROWS}
save_exp("budgets", {"rows": [{k: v for k, v in r.items() if k != "src"} for r in BUDGET_ROWS],
                     "spent_small": by_cap.get(20, {}).get("full_price"), "spent_mid": by_cap.get(60, {}).get("full_price"),
                     "spent_big": by_cap[SHOW_BUDGET]["full_price"], "recall_small": by_cap.get(20, {}).get("recall"),
                     "recall_mid": by_cap.get(60, {}).get("recall"), "recall_big": by_cap[SHOW_BUDGET]["recall"]})
results = []
expect("a plan was written and approved at every budget", all(r.get("decision") == "approved" for r in BUDGET_ROWS))
expect("every plan stayed within its job budget, even at full price", all(r["full_price"] <= r["budget"] for r in ran))
expect("a smaller budget never produced a costlier plan", all(a["estimate"] <= b["estimate"] + 1e-9 for a, b in zip(ran, ran[1:])))

#%% md
**Part V recap.** The lead now writes the plan:

- a **kit** gives a plan its words for one job, and each word was tested alone;
- a plan as **data** is easy to check and draw, and the fixed plan built from it is baseline C: recall {{fixed.recall_mean|.2f}} for {{fixed.magicubes_mean|.1f}} Magicubes per run;
- the **scout** gave the lead a page of {{scout_page.tokens}} tokens instead of a job of {{scout_page.job_tokens}};
- three ideas a data plan **cannot express** were measured on records we already had;
- a plan as a **program** is checked by a whitelist that refused all {{programs.hostile}} hostile programs, **rehearsed** for free, **priced**, and held for a person above a written limit;
- the lead wrote valid programs {{lead_program.valid_final}} times in 10 after repair, and its own plan ran end to end: recall {{showcase.recall|.2f}} for {{showcase.magicubes|.1f}} Magicubes, with a memo at the end;
- with less money, it wrote smaller plans.

What Part V does not settle is which of the kit's features earn their calls. Part VI measures them one at a time, and Part VII compares the whole designs under a pre-registered protocol.

**Try it yourself.**

1. Add a fourth lens to `LENS_TEXT`, for example one about recursion, and let the lead know about it in `LEAD_PROGRAM_SYSTEM`. Does it use the new lens, and does the dry run price the plan correctly?
2. Write a hostile plan program that the whitelist of S36 does *not* refuse, then add the rule that refuses it. Keep the five good programs accepted.
3. Change `AUTO_APPROVE` so the showcase plan is held, and replace the notebook's standing rule with a widget that asks you. What would you want to see on the screen before saying yes?

#%% code
save_exp("scout_page", {"tokens": est_tokens(SCOUT_TEXT), "job_tokens": SCOUT["tokens"]})
