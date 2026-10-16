#%% md
## S61 - When not to use it

**Theory.** A tool that is always used is a habit, not a judgement. Fanning out costs calls, adds a planning call and a report call, and adds places where things can go wrong. It pays when the work is too large for one worker, or the answer too long for one reply, or when independent second looks are worth their price. Two jobs below have none of those properties, and the workflow should lose on both.

1. **A tiny job**: grade five homework solutions. One worker reads all five comfortably and writes five verdicts. **H10** predicted that a forced workflow would be no more accurate and would cost more.
2. **A strictly sequential job**, "follow the transfers": 200 records, each saying how to change a balance and which record comes next, shuffled, with decoys that are never reached. The answer depends on following the chain one record at a time from the start. No split into independent pieces exists, because nobody knows which records are on the chain until they have followed it. The only decomposition is a relay of workers, each taking over where the last stopped, and that is slower and dearer than one worker.

**In plain terms.** If one person can do the job in one go, or the job is one long chain of steps, sending a crowd only adds cost.

**For teams.** Before fanning out, ask two questions: is the input or the output too big for one worker, and can the pieces be done without each other? If both answers are no, do not fan out.

#%% md
**The tiny job.** Six stacks of five solutions each, taken from the 600, each graded once by one worker and once by a forced workflow: a grader, then a second look at every flagged solution through the three lenses, then a merge. Accuracy is pooled over the 30 solutions.

#%% code
TINY_SETS = [HW_ORDER[k * 5:(k + 1) * 5] for k in range(0, 60, 10)][:6]
tiny_one, tiny_wf, cost_one, cost_wf = [], [], 0.0, 0.0
for k, ids in enumerate(TINY_SETS):
    r1 = Run(f"tiny job {k}: one worker", run_id=f"tiny-one-{k}", concurrency=4)
    k1 = HomeworkKit(r1, number=k)
    tiny_one += r1.run_sync(lambda r: k1.grade(ids))
    cost_one += full_price(r1)
    r2 = Run(f"tiny job {k}: forced workflow", run_id=f"tiny-wf-{k}", concurrency=8)
    k2 = HomeworkKit(r2, number=k)

    def forced(run, k2=k2, ids=ids):
        first = k2.grade(ids)
        flagged = [g["id"] for g in first if g["wrong"] or CALC_FLAGS[g["id"]]]
        second = flatten(run.parallel([lambda l=l: k2.recheck(flagged, l) for l in HW_LENS_TEXT])) if flagged else []
        return merge_grades(first + second)
    tiny_wf += r2.run_sync(forced)
    cost_wf += full_price(r2)
acc = lambda gs: sum(g["wrong"] == HW_KEY[g["id"]]["wrong"] for g in gs if g["wrong"] is not None) / max(1, len(gs))
TINY = {"one_acc": acc(tiny_one), "wf_acc": acc(tiny_wf), "one_cost": cost_one, "wf_cost": cost_wf, "items": len(tiny_one)}
TINY["h10"] = TINY["wf_acc"] <= TINY["one_acc"] + 0.02 and TINY["wf_cost"] > TINY["one_cost"]
print(f"[tiny] one worker: accuracy {TINY['one_acc']:.2f} for {cost_one:.1f}¢; forced workflow: accuracy {TINY['wf_acc']:.2f} "
      f"for {cost_wf:.1f}¢, over {TINY['items']} solutions in {len(TINY_SETS)} stacks of five")

#%% md
**What the lead plans for it.** The same lead, the same homework kit, a page that says five solutions and a budget of 5 cents.

#%% code
TINY_PAGE = (f"THE WORK\n- 5 solutions, about {est_tokens(render_items(TINY_SETS[0])):,} tokens in all.\n\nPRICES AND LIMITS\n"
             f"- Prices in dollars per million tokens: {price_text(('worker', 'judge', 'lead'))}. Billing is per token.\n- Budget for this job: 5 cents.")


@SCRIPTED.register
def _lead_tiny(model, messages, params):
    if "lead of a homework-grading job" not in messages[0]["content"][:200] or "5 solutions" not in messages[1]["content"]:
        return None
    return '```python\nphase("Grade")\ngrades = grade(items[:5])\nresult = {"grades": grades, "report": "five solutions, one worker"}\n```'

show_def(_lead_tiny)
TINY_PLAN = LEAD.write_program("Grade 5 homework solutions.", TINY_PAGE, sample=0, budget_cents=5, system=LEAD_HW_SYSTEM,
                               kit_class=HomeworkKit, stand_in=DRY_HW)
print(TINY_PLAN["src"])
print(f"\n[plan] {TINY_PLAN['estimate']['agents'] if TINY_PLAN['estimate'] else '?'} worker(s) for the tiny job")

#%% md
**Follow the transfers.** **`transfer_chain(seed)`** writes 200 records. Sixty of them form the chain from the first record to the last; the other 140 are decoys that point among themselves and are never reached. The records are shuffled, so following the chain means looking each next record up. The exact final balance is computed as the chain is written.

#%% code
def transfer_chain(seed, n=200, steps=60, start=100):
    """(records text, first record, exact final balance) of a shuffled chain of `steps` records among `n`."""
    rng_ = random.Random(seed)
    ids = rng_.sample(range(100, 1000), n)
    chain, decoys = ids[:steps], ids[steps:]
    lines, balance = [], start
    for k, rid in enumerate(chain):
        amount = rng_.randint(1, 60)
        op = "add" if balance < 200 or rng_.random() < 0.5 else "subtract"
        balance += amount if op == "add" else -amount
        tail = f"then go to R{chain[k + 1]}" if k + 1 < len(chain) else "this is the last record"
        lines.append(f"R{rid}: {op} {amount}, {tail}.")
    for rid in decoys:
        lines.append(f"R{rid}: {rng_.choice(['add', 'subtract'])} {rng_.randint(1, 60)}, then go to R{rng_.choice(decoys)}.")
    rng_.shuffle(lines)
    return "\n".join(lines), f"R{chain[0]}", balance

show_def(transfer_chain)
CHAIN_SYSTEM = """You follow a chain of records. Each record changes a balance and names the record that comes next. Start at the record you are given, with the balance you are given; apply each record's change and go to the record it names, until a record says it is the last, or until you have followed the number of records you are asked to follow. Answer with one JSON object and nothing else: {"record": "<the record you would go to next, or LAST>", "balance": <the balance>}."""
example, first, final = transfer_chain(SEED)
print(f"[chain] 200 records, the chain starts at {first}; exact final balance {final}. The first five lines as shuffled:\n  "
      + "\n  ".join(example.splitlines()[:5]))

#%% code
@SCRIPTED.register
def _chain(model, messages, params):
    if not messages[0]["content"].startswith("You follow a chain of records"):
        return None
    text = messages[-1]["content"]
    recs = dict(re.findall(r"^(R\d+): (.*)$", text, re.M))
    at = re.search(r"Start at (R\d+) with a balance of (-?\d+)", text)
    limit = int((re.search(r"[Ff]ollow (\d+) records", text) or [0, "1000"])[1])
    cur, bal = at.group(1), int(at.group(2))
    for step in range(limit):
        op, amount, nxt = re.match(r"(add|subtract) (\d+), (?:then go to (R\d+)|this is the last record)", recs[cur]).groups()
        bal += int(amount) if op == "add" else -int(amount)
        if zlib.crc32(f"{cur}:{params.get('sample', 0)}".encode()) % 100 < 1:
            bal += 10                                           # the stand-in slips about once in a hundred steps
        if nxt is None:
            return json.dumps({"record": "LAST", "balance": bal})
        cur = nxt
    return json.dumps({"record": cur, "balance": bal})

show_def(_chain)

#%% code
def chain_one(records, first, sample=0):
    """One worker follows the whole chain in one call."""
    run = Run("chain: one worker", run_id=f"chain-one-{sample}", concurrency=1)
    obj = run.run_sync(lambda r: r.agent(data=f"Start at {first} with a balance of 100.\n\n{records}", system=CHAIN_SYSTEM,
                                         schema={"type": "object", "required": ["balance"]}, model="worker", label="follow", role="chain",
                                         sample=sample))
    return (obj or {}).get("balance"), full_price(run), run


def chain_relay(records, first, legs=6, per_leg=10, sample=0):
    """A relay: each worker follows `per_leg` records and hands over; the only way to split a chain."""
    run = Run("chain: relay", run_id=f"chain-relay-{sample}", concurrency=1)

    def relay(r):
        cur, bal = first, 100
        for leg in range(legs):
            obj = r.agent(data=f"Start at {cur} with a balance of {bal}. Follow {per_leg} records at most.\n\n{records}", system=CHAIN_SYSTEM,
                          schema={"type": "object", "required": ["balance", "record"]}, model="worker", label=f"leg {leg + 1}",
                          role="chain", sample=sample)
            if not obj:
                return None
            cur, bal = obj["record"], obj["balance"]
            if cur == "LAST":
                break
        return bal
    return run.run_sync(relay), full_price(run), run

show_def(chain_one, chain_relay)
CHAIN_ROWS = []
for k in range(5):
    records, first, final = transfer_chain(SEED + k)
    b1, c1, r1 = chain_one(records, first, sample=k)
    b2, c2, r2 = chain_relay(records, first, sample=k)
    CHAIN_ROWS.append({"chain": k, "truth": final, "one": b1, "relay": b2, "one_ok": b1 == final, "relay_ok": b2 == final,
                       "one_cost": c1, "relay_cost": c2, "one_s": recorded_seconds(r1.run_id) or 0, "relay_s": recorded_seconds(r2.run_id) or 0})
table(CHAIN_ROWS, [("chain", "chain", "d"), ("truth", "exact", "d"), ("one", "one worker", ""), ("relay", "relay of six", ""),
                   ("one_cost", "¢ one", ".1f"), ("relay_cost", "¢ relay", ".1f")])
CHAIN = {"one_acc": float(np.mean([r["one_ok"] for r in CHAIN_ROWS])), "relay_acc": float(np.mean([r["relay_ok"] for r in CHAIN_ROWS])),
         "one_cost": sum(r["one_cost"] for r in CHAIN_ROWS), "relay_cost": sum(r["relay_cost"] for r in CHAIN_ROWS),
         "one_s": float(np.mean([r["one_s"] for r in CHAIN_ROWS])), "relay_s": float(np.mean([r["relay_s"] for r in CHAIN_ROWS]))}
print(f"[chain] one worker right on {CHAIN['one_acc']:.0%} of chains for {CHAIN['one_cost']:.1f}¢; the relay on {CHAIN['relay_acc']:.0%} "
      f"for {CHAIN['relay_cost']:.1f}¢")

#%% code
# FIG  two jobs where fanning out is the wrong answer
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.4))
for ax, (name, d, a_key, b_key, la, lb) in zip(axes, (("five solutions", TINY, "one_acc", "wf_acc", "one worker", "forced workflow"),
                                                    ("a chain of transfers", CHAIN, "one_acc", "relay_acc", "one worker", "relay of six"))):
    costs = [d["one_cost"], d["wf_cost"] if "wf_cost" in d else d["relay_cost"]]
    accs = [d[a_key], d[b_key]]
    ax.bar([la, lb], accs, color=[C3, C8], alpha=0.8)
    for x, (a, c) in enumerate(zip(accs, costs)):
        ax.text(x, a + 0.02, f"{c:.1f}¢", ha="center", fontsize=8)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("accuracy")
    panel(ax, name)
finish(fig, "s61_controls", f"On the tiny job the forced workflow cost {TINY['wf_cost'] / max(TINY['one_cost'], 1e-9):.1f}x as much for "
       f"{TINY['wf_acc'] - TINY['one_acc']:+.2f} accuracy", "labels above the bars: cents at full price over all the stacks or chains")

#%% md
**Reading FIG {{figures.s61_controls}} (s61_controls).** Left: on five solutions at a time, one worker reached an accuracy of {{controls.tiny_one|.2f}} for {{controls.tiny_one_cost|.1f}} cents, and the forced workflow {{controls.tiny_wf|.2f}} for {{controls.tiny_wf_cost|.1f}}; H10 is decided on exactly these numbers. Right: one worker following each chain of transfers in a single call was right on {{controls.chain_one|.0%}} of the chains; a relay of six workers, the only way to split a chain, was right on {{controls.chain_relay|.0%}} and cost {{controls.chain_relay_cost|.1f}} cents against {{controls.chain_one_cost|.1f}}. Given the tiny job's page, the lead did not plan a single worker: it wrote the same grade, recheck and report plan it wrote for the 600, and the dry run counted {{controls.tiny_plan_agents}} workers for it, so the check below fails. Whether a second look was worth about {{controls.tiny_ratio|.0f}} times the price on five solutions is a judgement for the person paying; the engine's job is to show both numbers before the money is spent, which the dry run of S37 does.

#%% code
save_exp("controls", {"tiny_one": TINY["one_acc"], "tiny_wf": TINY["wf_acc"], "tiny_one_cost": TINY["one_cost"], "tiny_wf_cost": TINY["wf_cost"],
                      "h10": TINY["h10"], "chain_one": CHAIN["one_acc"], "chain_relay": CHAIN["relay_acc"], "chain_one_cost": CHAIN["one_cost"],
                      "chain_relay_cost": CHAIN["relay_cost"], "tiny_plan_agents": TINY_PLAN["estimate"]["agents"] if TINY_PLAN["estimate"] else None,
                      "tiny_plan": TINY_PLAN["src"], "tiny_ratio": TINY["wf_cost"] / max(TINY["one_cost"], 1e-9), "chain_rows": CHAIN_ROWS})
results = []
expect("every chain's exact answer comes from the chain as written", all(isinstance(r["truth"], int) for r in CHAIN_ROWS))
expect("the forced workflow cost more than one worker on the tiny job", TINY["wf_cost"] > TINY["one_cost"])
expect("the lead planned a single worker for the tiny job", TINY_PLAN["valid"] and TINY_PLAN["estimate"]["agents"] <= 2)

#%% md
## S62 - Four plans, side by side

**Theory.** The same lead wrote four plans in this notebook, for four jobs, with the same plan language and four different kits. Side by side they show what "dynamic" means in practice, and where it stops: the shape of the plan follows the shape of the job, up to a point. The audit fans out wide and then narrows through verification; the homework job fans out, then sends only the flagged items to a second look; the customer-questions job fans out twice with a tree of merges between; for the tiny job the lead was expected not to fan out, and S61 showed that it reused the homework plan instead.

#%% code
FOUR = {"audit (S39)": SHOW["src"], "homework (S59)": HW_PLAN["src"], "customer questions (S60)": INTENT_PLAN["src"], "five solutions (S61)": TINY_PLAN["src"]}
FOUR_EST = {"audit (S39)": SHOW_EST, "homework (S59)": HW_PLAN["estimate"], "customer questions (S60)": INTENT_PLAN["estimate"],
            "five solutions (S61)": TINY_PLAN["estimate"]}
for name, src in FOUR.items():
    est = FOUR_EST[name] or {}
    print(f"--- {name}: {len(src.splitlines())} lines, {est.get('agents', '?')} workers, {est.get('cents', 0):.1f}¢ estimated; "
          f"uses {', '.join(features(src)) or 'nothing beyond a data plan'}")

#%% code
# FIG  the lead's four plans, drawn as the workers each phase starts
fig, axes = plt.subplots(1, 4, figsize=(11.0, 3.6), sharey=True)
for ax, (name, est) in zip(axes, FOUR_EST.items()):
    phases_ = list((est or {}).get("phases", {}).items())
    ax.barh(range(len(phases_)), [n for _, n in phases_], color=PALETTE[: len(phases_)])
    ax.set_yticks(range(len(phases_)), [p[:22] for p, _ in phases_], fontsize=7.5)
    ax.invert_yaxis()
    ax.set_xscale("symlog")
    ax.set_xlabel("workers (dry run)")
    panel(ax, name)
finish(fig, "s62_four_plans", "Four jobs, four plans from the same lead: the shape of each plan follows the shape of its job",
       "workers per phase from each plan's dry run; logarithmic scale")

#%% md
**Reading FIG {{figures.s62_four_plans}} (s62_four_plans).** Each panel is one plan, each bar one phase, and its length the number of workers the dry run counted. The audit plan is wide everywhere. The homework plan is wide once and narrower for the second look. The customer-questions plan is wide twice, with a handful of merge workers in between. The tiny job's plan has the same phases as the homework plan, although it grades five solutions instead of 600: the lead did not shrink its plan to the job. None of these shapes was coded into the engine; each came from the lead reading a page about its job.

**Part VIII recap.** The same runtime and the same lead did four jobs:

- a homework benchmark with three kinds of planted error, a leak test passed at AUROC {{homework.leak.characters|.2f}} at most, and a calculator that catches slips for free and almost nothing else;
- one grader working down 600 solutions changed accuracy by {{hw_run.slope_single|+.3f}} per 100 items; fresh workers by {{hw_run.slope_wf|+.3f}};
- ten thousand customer messages, which one call could only partly label, which the workflow's tree of merges collapsed into {{intents.topics}} topics with {{intents.unsorted}} messages unsorted, an ARI of {{intents.ari|.2f}} against 77 hidden intents;
- two jobs where the right plan was not to fan out, and a lead that still planned a grade and recheck workflow for the tiny one ({{controls.tiny_plan_agents}} workers by the dry run).

**Try it yourself.**

1. Add a fourth error kind to S59, for example a unit mix-up (minutes for hours), with its own plausibility rule and its own lens. Does the lead's plan pick up the new lens?
2. In S60, run the tree merge with groups of 100 and of 1,000 labels. How do the number of merge calls, the unmapped labels and the ARI move?
3. Make the chain of S61 branch: some records name two next records and a rule for choosing. Is there now any useful way to split the work?
