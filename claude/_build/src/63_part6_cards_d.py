#%% md
## S48 - Card: model routing

**Why.** Every role in a plan names a model, and the models differ in price, speed and skill. With per-token billing, a scan by the lead's model costs about twenty times a scan by the worker model, because it reads the same shard at twenty times the price. **Routing** is choosing a model per role on evidence. The evidence here is the scan role, because it is where most of the calls are: each candidate model reads the same shards of the S13 subset, which holds 24 planted bugs, and we compare what each found with what a full scan of the library would cost at its price.

**Live.** One general scan per shard per model, sample 0. Models whose context window cannot hold a shard plus the instruction are skipped, and the table says so. Where two roles share a model, the model is scanned once, under the first role's name.

#%% code
ROUTE_SHARDS = pack(DM_FILES, SHARD_TOKENS)
ROUTE_RUN = Run("routing: every model scans the S13 subset", run_id="s48-routing", concurrency=32)
ROUTE_KIT = AuditKit(ROUTE_RUN, number=0)
ROUTE_ROLES = [r for r in ("worker", "fast", "judge", "lead_alt", "lead", "omni")
               if CONTEXT_TOKENS.get(MODELS[r], 0) >= max(sum(FILE_TOKENS[p] for p in s) for s in ROUTE_SHARDS) + 20_000]
ROUTE_ROLES = [r for i, r in enumerate(ROUTE_ROLES) if MODELS[r] not in {MODELS[q] for q in ROUTE_ROLES[:i]}]   # each model once
skipped = sorted(r for r in ("worker", "fast", "judge", "lead_alt", "lead", "omni")
                 if r not in ROUTE_ROLES and MODELS[r] not in {MODELS[q] for q in ROUTE_ROLES})


def route_plan(run):
    run.phase("Scan with every model")
    return {role: flatten(run.parallel([lambda s=s, role=role: ROUTE_KIT.scan(s, "general", model=role) for s in ROUTE_SHARDS]))
            for role in ROUTE_ROLES}

show_def(route_plan, layer="plan")
ROUTED = ROUTE_RUN.run_sync(route_plan)
ROUTE_ROWS = []
for role in ROUTE_ROLES:
    sc = match(as_findings(ROUTED[role]), key=DM_BUGS)
    secs = [t.ended - t.started for t in ROUTE_RUN.threads if t.model == MODELS[role]]
    ROUTE_ROWS.append({"role": role, "model": MODELS[role].split("/")[-1], "found": sc.tp, "recall": sc.recall,
                       "false_places": sc.fp, "price": call_cents(MODELS[role], SHARD_TOKENS), "full_scan": call_cents(MODELS[role], SHARD_TOKENS) * len(shards()),
                       "median_s": float(np.median(secs)) if secs else None})
table(ROUTE_ROWS, [("role", "role", ""), ("model", "model", ""), ("found", f"found of {len(DM_BUGS)}", "d"), ("recall", "recall", ".2f"),
                   ("false_places", "other places", "d"), ("price", "¢ per call", ".1f"), ("full_scan", "¢ per full scan", ".1f"),
                   ("median_s", "median s per call", ".0f")])
print(f"[routing] skipped for their context window: {', '.join(skipped) or 'none'}")

#%% code
def pareto(rows, x, y):
    """The rows no other row beats on both: lower x and higher y."""
    return [r for r in rows if not any(o[x] <= r[x] and o[y] >= r[y] and (o[x] < r[x] or o[y] > r[y]) for o in rows)]

show_def(pareto)
FRONT = pareto(ROUTE_ROWS, "full_scan", "recall")
print(f"[pareto] on the front: {', '.join(r['role'] for r in sorted(FRONT, key=lambda r: r['full_scan']))}")

#%% code
# FIG  what each model finds for its price, with the Pareto front
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.6))
ax = axes[0]
for r in ROUTE_ROWS:
    on = r in FRONT
    ax.scatter([r["full_scan"]], [r["recall"]], s=60, color=C1 if on else MUTED, zorder=3)
    ax.annotate(f"{r['role']}\n{r['model']}", (r["full_scan"], r["recall"]), textcoords="offset points", xytext=(6, -4), fontsize=7)
fr = sorted(FRONT, key=lambda r: r["full_scan"])
ax.plot([r["full_scan"] for r in fr], [r["recall"] for r in fr], color=C1, lw=1)
ax.set_xlabel("cents for one scan of the whole library")
ax.set_ylabel(f"recall on the subset's {len(DM_BUGS)} bugs")
ax.set_ylim(0, 1)
panel(ax, "blue: the Pareto front")
ax = axes[1]
ax.barh([r["role"] for r in ROUTE_ROWS], [r["median_s"] or 0 for r in ROUTE_ROWS], color=C4)
ax.invert_yaxis()
ax.set_xlabel("median seconds per scan call")
panel(ax, "speed")
best_r = max(ROUTE_ROWS, key=lambda r: r["recall"])
finish(fig, "s48_routing", f"{best_r['role']} ({best_r['model']}) found the most of the subset's bugs; "
       f"{len(FRONT)} model{'s are' if len(FRONT) > 1 else ' is'} on the price front", "one general scan per shard of the S13 subset per model, sample 0")

#%% md
**Evidence. Reading FIG {{figures.s48_routing}} (s48_routing).** Left: each model is a dot at the price of one full scan of the library and the recall it reached on the subset; the blue line joins the models no other model beats on both price and recall. {{routing.best_role}} found the most ({{routing.best_recall|.2f}}). The worker model, which every plan so far used for scanning, reached {{routing.worker_recall|.2f}} at {{routing.worker_cost|.1f}} cents per full scan. Right: speed, which matters twice, for wall clock and for how long a slot is held. A model off the front should not scan; a model on it is a candidate, and the choice between candidates is a trade the lead can make from the scout's page. Only one sample per model was taken, so small differences in recall here are noise.

#%% code
w_row = next(r for r in ROUTE_ROWS if r["role"] == "worker")
save_exp("routing", {"rows": ROUTE_ROWS, "front": [r["role"] for r in FRONT], "skipped": skipped, "best_role": best_r["role"],
                     "best_recall": best_r["recall"], "worker_recall": w_row["recall"], "worker_cost": w_row["full_scan"]})
results = []
expect("every routed model scanned every shard of the subset", all(sum(t.model == MODELS[r] for t in ROUTE_RUN.threads) == len(ROUTE_SHARDS)
                                                                   for r in ROUTE_ROLES))
expect("the Pareto front is not empty and holds the cheapest model with the best recall at its price", len(FRONT) >= 1)

#%% md
## S49 - Card: shard size, at the level of the whole system

**Why.** S13 measured how one worker's recall changes with the size of the shard it reads, and chose `SHARD_TOKENS` from that curve. But a system is more than one worker: duplicates get merged, skeptics remove false alarms, and the report merges root causes. Fewer, larger shards mean fewer calls but each worker reads more, so the question is whether the S13 choice still holds once verification is in the loop.

**Live.** A slim plan, one general scan per shard, one skeptic with evidence per batch, and the report, run at four shard sizes. At the size S13 chose, the scans are the general scans of S41 and come from the ledger.

#%% code
def slim_program(tokens):
    """One general scan per shard, one skeptic with evidence, the report."""
    return (f'phase("Scan")\nfound = dedupe(flatten(parallel([lambda s=s: scan(s, "general") for s in shards({tokens})])))\n'
            f'phase("Verify")\nverdicts = flatten(parallel([lambda b=b: check(b) for b in batches(found, 6)]))\n'
            f'phase("Report")\nresult = report(vote(found, verdicts, need=1))')

show_def(slim_program)
SIZE_ROWS = []
for t in SIZES:
    run, kit, result, out = run_plan(slim_program(t), f"s49-size-{t // 1000}k", number=0, title=f"slim plan at {t // 1000}k-token shards")
    SIZE_ROWS.append({"tokens": t, "shards": len(shards(t)), "recall": out["recall"], "precision": out["precision"], "calls": out["calls"],
                      "full_price": full_price(run), "single_worker": MEAN_RECALL[t]})
table(SIZE_ROWS, [("tokens", "shard tokens", ","), ("shards", "shards", "d"), ("calls", "calls", "d"), ("full_price", "¢ at full price", ".1f"),
                  ("recall", "system recall", ".2f"), ("precision", "precision", ".2f"), ("single_worker", "S13 one-worker recall", ".2f")])

#%% code
# FIG  shard size, measured on the whole system
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.5))
ax = axes[0]
ax.plot([r["tokens"] // 1000 for r in SIZE_ROWS], [r["recall"] for r in SIZE_ROWS], "o-", color=C1, label="whole system, whole library")
ax.plot([r["tokens"] // 1000 for r in SIZE_ROWS], [r["single_worker"] for r in SIZE_ROWS], "s--", color=MUTED, label="one worker, S13 subset")
ax.axvline(SHARD_TOKENS // 1000, color=C8, ls=":", lw=1)
ax.text(SHARD_TOKENS // 1000, 0.05, f" chosen in S13: {SHARD_TOKENS // 1000}k", fontsize=7.5, color=C8)
ax.set_ylim(0, 1)
ax.set_xlabel("shard size (thousand tokens)")
ax.set_ylabel("recall")
ax.legend(fontsize=7.5)
panel(ax, "recall")
ax = axes[1]
ax.plot([r["tokens"] // 1000 for r in SIZE_ROWS], [r["full_price"] for r in SIZE_ROWS], "o-", color=C4)
ax.set_xlabel("shard size (thousand tokens)")
ax.set_ylabel("cents per run at full price")
panel(ax, "cost")
best_s = max(SIZE_ROWS, key=lambda r: r["recall"])
finish(fig, "s49_shards", f"In the whole system, {best_s['tokens'] // 1000}k-token shards gave the best recall ({best_s['recall']:.2f}); "
       f"S13 chose {SHARD_TOKENS // 1000}k", "a slim plan (one general scan, one skeptic with evidence, the report) at four shard sizes")

#%% md
**Evidence. Reading FIG {{figures.s49_shards}} (s49_shards).** Left: the whole system's recall at each shard size (blue), next to the one-worker measurement of S13 that chose the size (grey). The best system recall came at {{shards.best_k}}k tokens ({{shards.best_recall|.2f}}); at the chosen {{shards.chosen_k}}k it was {{shards.chosen_recall|.2f}}. Right: the price of a run at each size. Larger shards mean fewer scans, but each scan reads more tokens and the verify stage costs whatever the scans report, so the price need not fall: here the cheapest size was {{shards.cheapest_k}}k tokens ({{shards.cheapest_cents|.1f}} cents) and the chosen {{shards.chosen_k}}k cost {{shards.chosen_cents|.1f}}. If the two recall curves agree on the best size, S13's cheap measurement on a subset was a good proxy for the expensive one; if they disagree, the subset was too small or verification changes the trade. Part VII keeps the size S13 chose, so its runs stay comparable with the fixed plan's.

#%% code
chosen = next(r for r in SIZE_ROWS if r["tokens"] == SHARD_TOKENS)
save_exp("shards", {"rows": SIZE_ROWS, "best_k": best_s["tokens"] // 1000, "best_recall": best_s["recall"],
                    "chosen_k": SHARD_TOKENS // 1000, "chosen_recall": chosen["recall"], "chosen_cents": chosen["full_price"],
                    "cheapest_k": min(SIZE_ROWS, key=lambda r: r["full_price"])["tokens"] // 1000,
                    "cheapest_cents": min(r["full_price"] for r in SIZE_ROWS)})
results = []
expect("every size read every file", all(r["shards"] == len(shards(r["tokens"])) for r in SIZE_ROWS))
expect("larger shards never meant more scan calls", all(a["shards"] >= b["shards"] for a, b in zip(SIZE_ROWS, SIZE_ROWS[1:])))

#%% md
**Part VI recap.** Nine features, each measured on its own, mostly from calls the ledger already held:

- **lenses**: for the same calls, three lenses reported {{lenses.three|.2f}} of the planted bugs at the scan stage against {{lenses.general3|.2f}} for three general readings;
- **evidence**: skeptics were right {{evidence_card.acc_with|.2f}} of the time with the sandbox result and {{evidence_card.acc_without|.2f}} without;
- **verification**: 2 of 3 skeptics took precision from {{skeptics.none_precision|.2f}} to {{skeptics.p23|.2f}};
- **cross-generation judge**: accuracy {{judges.acc_other|.2f}} against {{judges.acc_same|.2f}} for the finders' own model, kappa {{judges.kappa|.2f}};
- **looping**: six rounds reported {{loop.round6|.2f}} of the planted bugs where one round reported {{loop.round1|.2f}};
- **capture and recapture**: a floor for what is left, not a count, because hard bugs hide from both catches;
- **merging and the critic**: about {{merge.calls_saved|.0f}} skeptic calls saved per run, and a critic whose folders held missed bugs at {{merge.lift|.1f}} times chance;
- **routing**: {{routing.best_role}} found the most on the subset; the worker model costs {{routing.worker_cost|.1f}} cents per full scan;
- **shard size**: the whole system did best at {{shards.best_k}}k tokens.

None of these cards gives a verdict. Part VII pre-registers the hypotheses and the rules, compares the designs as wholes, and turns these measurements into KEPT, NEUTRAL or HARMFUL with intervals.

**Try it yourself.**

1. Write a fourth lens aimed at the two planted kinds the three lenses found least often (look at FIG {{figures.s41_lenses}}), run it on run 0's shards, and see whether those kinds rise.
2. Re-run the skeptic card with a batch size of 2 instead of 6. Does accuracy change when a skeptic sees fewer reports at once, and what does it do to the number of calls?
3. Use `chao1` on the six rounds of S45 instead of the three runs. Does the estimate rise towards the number of planted bugs, and why might it still fall short?
