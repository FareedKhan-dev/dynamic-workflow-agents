#%% md
## S37 - Dry run, cost estimate and the approval gate

**Theory.** A data plan's size can be read off the page (S32). A program's cannot: it has loops whose length depends on results, conditions, and functions that start workers. The reliable way to know what a program will do is to **run it**, and the cheap way to run it is against a stand-in model. A **dry run** executes the plan, unchanged, on a scripted model that answers instantly and for free, and counts what the plan asked for: workers, calls, phases, cents at the real prices.

The stand-in used here is deliberately **blind**. Unlike the scripted model of the smoke run, it never looks at the answer key. A scan worker reports the measured average number of findings per call, at made-up places in the files it was given; a skeptic calls about two in five of them real. The estimate therefore follows one plausible path through the plan, with realistic volumes, and knows nothing the real run would not.

The estimate then goes to an **approval gate**. A plan whose estimate is small, both in cents and as a share of the job's budget, is approved automatically. A larger one is held until a person has read the estimate and said yes. A plan that the dry run caught hitting a limit, or that would cost more than the whole budget, is refused outright.

**In plain terms.** Before spending anything, the plan is run against a free fake model to count how many calls it would make. Small plans go ahead; big ones wait for a person to say yes.

**For teams.** Never let generated code spend money on its first run. Rehearse it against a stub, price the rehearsal, and put a human in the loop above a threshold you chose in advance. The threshold is policy: write it down next to the code.

#%% code
DRY = ScriptedModel()


@DRY.register
def _dry_scan(model, messages, params):
    if not messages[0]["content"].startswith("You are reviewing Python code for behaviour bugs"):
        return None
    text = messages[-1]["content"]
    if text.startswith("Your answer does not match"):
        return '{"findings": []}'
    paths = re.findall(r"^### (\S+)$", text, re.M)
    seed = zlib.crc32((text[:300] + str(params.get("sample", 0))).encode())
    k = int(SCAN_STATS[0]) + (seed % 3) - 1
    out = []
    for j in range(max(0, k)):
        p = paths[(seed + 7 * j) % len(paths)] if paths else "unknown.py"
        out.append({"file": p, "line": 5 + (seed >> (j % 16)) % 60, "claim": "a made-up finding", "confidence": 0.5})
    return json.dumps({"findings": out})


@DRY.register
def _dry_skeptic(model, messages, params):
    if not messages[0]["content"].startswith("You check bug reports"):
        return None
    n = len(re.findall(r"^--- report \d+ ---$", messages[-1]["content"], re.M))
    seed = zlib.crc32((messages[-1]["content"][:200] + str(params.get("sample", 0))).encode())
    return json.dumps({"verdicts": [{"report": i, "real": (seed >> i) % 5 < 2} for i in range(1, n + 1)]})


DRY.register(_report)
show_def(_dry_scan, _dry_skeptic)
print(f"[dry] the blind stand-in answers scans with about {SCAN_STATS[0]:.1f} made-up findings and calls 40% of them real")

#%% md
**`dry_run(src, budget_cents)`** checks the program against the names of the job's kit (the audit kit unless another is given), then runs it on the blind stand-in in a background thread with a time limit, with its own throwaway ledger, so nothing it does is stored or paid. The run sees the same budget the real run will see, because a plan may decide things from `budget()`. A plan that does not finish within the limit is refused: rules cannot bound a program's running time in general, but a clock can. **`estimate_of(run)`** turns the rehearsal into numbers.

#%% code
def estimate_of(run):
    """Workers, calls, cents at real prices, phases and a rough duration, from a finished dry run."""
    by_model = collections.Counter(t.model for t in run.threads for _ in t.replies)
    minutes = 0.0
    for p in run.phases:
        roles = collections.Counter(t.role for t in run.threads if t.phase == p["name"])
        role = roles.most_common(1)[0][0] if roles else "scan"
        minutes += math.ceil(p["agents"] / 32) * (median_seconds(role) or 60) / 60     # waves of 32 at the median latency
    return {"agents": len(run.threads), "calls": sum(by_model.values()),
            "cents": round(sum(price_of(t.model, Reply(prompt_tokens=r.prompt_tokens, completion_tokens=max(r.completion_tokens, TYPICAL_ANSWER)))
                               for t in run.threads for r in t.replies), 1),
            "phases": {p["name"]: p["agents"] for p in run.phases}, "dropped": len(run.dropped), "minutes": round(minutes, 1),
            "status": run.status}


def dry_run(src, budget_cents=300, timeout_s=60, kit_class=None, stand_in=None):
    """(estimate or None, problems): check the program, then rehearse it on the blind stand-in, for free."""
    kit_class, stand_in = kit_class or AuditKit, stand_in or DRY
    llm = LLM("smoke", Ledger(Path(tempfile.mkdtemp()) / "dry.sqlite"), scripted=stand_in)
    llm.budget = Budget(cap=budget_cents)                       # what budget() will say in the real run
    run = Run("dry run", run_id=f"dry-{hashlib.sha256(src.encode()).hexdigest()[:8]}", llm=llm, concurrency=64)
    kit = kit_class(run)
    problems = check_program(src, kit.names())
    if problems:
        return None, problems
    worker = threading.Thread(target=lambda: run.run_sync(lambda r: run_program(src, kit)), daemon=True)
    worker.start()
    worker.join(timeout_s)
    if worker.is_alive():
        run.cancel()
        return None, [f"line 1: the dry run did not finish within {timeout_s} s; the plan probably loops without end"]
    if run.status != "completed":
        why = f"{len(run.dropped)} workers refused by the agent limit" if run.dropped else run.error
        return None, [f"line 1: the dry run ended {run.status}: {why}"]
    return estimate_of(run), []

show_def(estimate_of, dry_run)

#%% md
**The five good programs of S36, rehearsed.** Each estimate below cost nothing. The loop's number of rounds and the triage's number of dropped places come from the stand-in's answers, so for those two programs the estimate is one plausible path, not a bound.

#%% code
ESTIMATES = {}
for name, src in GOOD.items():
    t0 = time.perf_counter()
    est, probs = dry_run(src)
    ESTIMATES[name] = est
    print(f"[dry] {name:<26} {('%d workers, %d calls, %.1f¢, about %.0f min' % (est['agents'], est['calls'], est['cents'], est['minutes'])) if est else probs[0]}"
          f"   ({time.perf_counter() - t0:.1f} s to rehearse)")
table([{"plan": n, **{k: e[k] for k in ("agents", "calls", "cents", "minutes")},
        "phases": " / ".join(f"{p} {a}" for p, a in e["phases"].items())} for n, e in ESTIMATES.items() if e],
      [("plan", "plan", ""), ("agents", "workers", "d"), ("calls", "calls", "d"), ("cents", "cents", ".1f"),
       ("minutes", "minutes (rough)", ".0f"), ("phases", "workers per phase", "")])

#%% md
**A runaway plan, rehearsed.** This program passes every rule of S36: a bounded `for` loop, a number under the limit, only names of the language. It would still start a million workers. The dry run meets the agent limit of S29, which cancels the run once the plan has asked for twice its limit, and the plan is refused before a single cent is at stake.

#%% code
RUNAWAY = """phase("Scan")
for i in range(1000000):
    agent("look again", model="worker", label=f"again#{i}")
result = report([])"""
print(f"[check] {check_program(RUNAWAY) or 'passes every rule'}")
t0 = time.perf_counter()
RUNAWAY_EST, RUNAWAY_PROBS = dry_run(RUNAWAY)
print(f"[dry] refused after {time.perf_counter() - t0:.1f} s: {RUNAWAY_PROBS[0] if RUNAWAY_PROBS else 'NOT REFUSED'}")

#%% md
**How good is the estimate?** The fixed plan ran three times for real in S32, and the lead's first JSON plan once in S34. Their dry-run estimates can be put next to what they actually made and spent.

#%% code
def full_price(run):
    """Cents a run's calls cost at full price, counting calls the ledger answered for free."""
    return round(sum(price_of(t.model, r) for t in run.threads for r in t.replies), 2)

show_def(full_price)
FIXED_EST, _ = dry_run(FIXED_PROGRAM)
DJSON_EST, _ = dry_run(compile_plan(D_JSON))
EST_ROWS = [{"plan": "C, the fixed plan (mean of 3)", "est_calls": FIXED_EST["calls"], "calls": np.mean([c["calls"] for c in C_RUNS]),
             "est_cents": FIXED_EST["cents"], "mc": np.mean([full_price(run) for run, _, _ in C_OBJS])},
            {"plan": "the lead's JSON plan 0", "est_calls": DJSON_EST["calls"], "calls": D_JSON_OUT["calls"],
             "est_cents": DJSON_EST["cents"], "mc": full_price(d_run)}]
for r in EST_ROWS:
    r["error"] = r["est_cents"] / max(r["mc"], 1e-9) - 1
table(EST_ROWS, [("plan", "plan", ""), ("est_calls", "estimated calls", "d"), ("calls", "actual calls", ".0f"),
                 ("est_cents", "estimated¢", ".1f"), ("mc", "actual¢ at full price", ".1f"), ("error", "estimate error", "+.0%")])

#%% md
**`approve(estimate, budget_cents, person)`** is the gate. Its policy is two numbers, written down here: a plan is approved automatically when its estimate is at most 80 cents *and* at most a third of the job's budget. Above that, it is held for a person. The person is a function, so a notebook can pass a widget's answer, a test can pass a rule, and a script with nobody watching passes nothing and gets `held`. The table applies the gate to every rehearsed plan twice: with the job's budget of 300 cents, and with a tighter budget of 200, where the automatic limit drops to 67.

#%% code
AUTO_APPROVE = {"max_cents": 80.0, "max_share": 1 / 3}


def approve(est, budget_cents, person=None):
    """(decision, reason): approved, held for a person, or refused."""
    if est is None:
        return "refused", "the plan failed its check or its dry run"
    if est["cents"] > budget_cents:
        return "refused", f"estimated {est['cents']:.1f}¢ is more than the whole budget of {budget_cents:.0f}"
    limit = min(AUTO_APPROVE["max_cents"], AUTO_APPROVE["max_share"] * budget_cents)
    if est["cents"] <= limit:
        return "approved", f"estimated {est['cents']:.1f}¢ is under the automatic limit of {limit:.1f}"
    if person is None:
        return "held", f"estimated {est['cents']:.1f}¢ is over the automatic limit of {limit:.1f}; a person must approve it"
    yes = bool(person(est))
    return ("approved" if yes else "refused"), f"a person {'approved' if yes else 'refused'} it after reading the estimate of {est['cents']:.1f}¢"

show_def(approve)
GATE = []
for name, est in list(ESTIMATES.items()) + [("runaway", RUNAWAY_EST)]:
    (d150, why150), (d45, why45) = approve(est, 300), approve(est, 200)
    GATE.append({"plan": name, "decision": d150, "why": why150, "tight": d45, "why_tight": why45})
table(GATE, [("plan", "plan", ""), ("decision", "budget 300", ""), ("tight", "budget 200", ""), ("why_tight", "why, at 200", "")])
held = next((g["plan"] for g in GATE if g["tight"] == "held"), None)
if held:
    print(f"\n[gate] at a budget of 200, '{held}' was held. A person reads the estimate and decides:")
    print("  " + str(approve(ESTIMATES[held], 200, person=lambda est: est["cents"] <= 150)))

#%% code
# FIG  the cost of each plan, known before a single paid call
fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.6), gridspec_kw={"width_ratios": [1.5, 1]})
ax = axes[0]
names = [n for n, e in ESTIMATES.items() if e]
colours = {"approved": C3, "held": C4, "refused": C8}
dec = {g["plan"]: g["decision"] for g in GATE}
ax.barh(range(len(names)), [ESTIMATES[n]["cents"] for n in names], color=[colours[dec[n]] for n in names])
limit = min(AUTO_APPROVE["max_cents"], AUTO_APPROVE["max_share"] * 300)
ax.axvline(limit, color=INK2, ls="--", lw=1)
ax.text(limit, len(names) - 0.4, f" automatic limit {limit:.0f}", fontsize=7.5, color=INK2)
ax.set_yticks(range(len(names)), names, fontsize=8)
ax.invert_yaxis()
ax.set_xlabel("estimated cents (dry run)")
panel(ax, "green: approved; amber: held for a person")
ax = axes[1]
x = np.arange(len(EST_ROWS))
ax.bar(x - 0.18, [r["est_cents"] for r in EST_ROWS], 0.36, color=C1, label="estimated")
ax.bar(x + 0.18, [r["mc"] for r in EST_ROWS], 0.36, color=MUTED, label="actual")
ax.set_xticks(x, ["fixed plan", "lead's JSON plan"], fontsize=8.5)
ax.set_ylabel("cents")
ax.set_ylim(0, 1.3 * max(max(r["est_cents"], r["mc"]) for r in EST_ROWS))
ax.legend(fontsize=7.5, loc="upper left", ncol=2)
panel(ax, "estimate against the real runs")
finish(fig, "s37_estimates", f"Every plan priced before it ran; the estimate missed the fixed plan's real cost by {EST_ROWS[0]['error']:+.0%}",
       "left: dry-run estimates of the five good programs of S36 at a budget of 300; right: estimate against actual")

#%% md
**Reading FIG {{figures.s37_estimates}} (s37_estimates).** Left: each good program of S36, priced by its dry run. A plan under the automatic limit of {{dryrun.auto_limit|.0f}} cents would start at once and the others wait for a person; in this run every one of the five was priced above that limit, so all five would be held. Right: the estimate against the real cost of the plans that have already run. For the fixed plan the estimate was off by {{dryrun.fixed_error|+.0%}}; the scan phase is priced exactly, and the error comes from the verify phase, whose size depends on how many places the real workers reported. An estimate within a few tens of percent is what an approval gate needs: it separates a 30-cent plan from a 300-cent one, which is the decision that matters.

#%% code
save_exp("dryrun", {"estimates": ESTIMATES, "runaway_refused": RUNAWAY_EST is None, "runaway_reason": (RUNAWAY_PROBS or [""])[0],
                    "fixed_error": EST_ROWS[0]["error"], "json_error": EST_ROWS[1]["error"], "auto_limit": limit,
                    "gate": GATE, "estimate_rows": EST_ROWS})
results = []
expect("every good program completes its dry run", all(e is not None for e in ESTIMATES.values()))
expect("the runaway plan passes the rules but is refused by its dry run", not check_program(RUNAWAY) and RUNAWAY_EST is None)
expect("the dry run of the fixed plan prices its scan phase exactly", FIXED_EST["phases"]["Scan"] == FIXED_COUNTS["Scan"])
expect("dry runs spend nothing: the main ledger gained no rows from them",
       not FRONT_DOOR.ledger.query("SELECT key FROM calls WHERE run_id LIKE 'dry-%'"))
expect("at the tight budget at least one plan is held for a person", held is not None)
expect("a held plan is approved when a person says yes, and refused when a person says no",
       held is not None and approve(ESTIMATES[held], 200, person=lambda e: True)[0] == "approved"
       and approve(ESTIMATES[held], 200, person=lambda e: False)[0] == "refused")
