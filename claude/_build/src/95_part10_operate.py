#%% md
# Part X. Operating it

**Where this sits.** The engine is built, measured and checked. This last Part is for the person who wants to run it: where the money and the time went, how to point the engine at a job of your own, what to switch on first, how to reproduce every number here, and the manifest that records the settings behind them.

![part10](attachment:part10_map.png)

## S71 - Where the calls, cents and time went

Every call this notebook made is in the ledger, with its role, phase, model and price. The accounts below are read straight from it.

#%% code
by_role = FRONT_DOOR.ledger.accounts("role")
by_model = FRONT_DOOR.ledger.accounts("model")
table(by_role, [("group", "role", ""), ("calls", "calls", "d"), ("cents", "cents", ".1f")])
SPENT = sum(r["cents"] for r in by_role)
print(f"[accounts] {sum(r['calls'] for r in by_role):,} calls in the ledger; {SPENT:.1f} cents paid "
      f"({'smoke run: the stand-in is free' if DW_MODE == 'smoke' else f'of a cap of {CAP_CENTS}'})")

#%% code
# FIG  where the calls went, and how long each model took
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6))
ax = axes[0]
top_roles = sorted(by_role, key=lambda r: -r["calls"])[:10]
ax.barh([r["group"] or "(none)" for r in top_roles], [r["calls"] for r in top_roles], color=C1)
ax.invert_yaxis()
ax.set_xlabel("calls")
panel(ax, "calls by role")
ax = axes[1]
lat = [(m.split("/")[-1], [s for (s,) in FRONT_DOOR.ledger.query("SELECT seconds FROM calls WHERE model = ? AND seconds > 0", (m,))]) for m in MODELS.values()]
lat = [(m, xs) for m, xs in lat if xs]
if lat:
    ax.boxplot([xs for _, xs in lat], orientation="horizontal", tick_labels=[m for m, _ in lat], showfliers=False)
ax.set_xlabel("seconds per call")
panel(ax, "latency by model")
finish(fig, "s71_accounts", f"{sum(r['calls'] for r in by_role):,} calls in all; the most went to the role '{top_roles[0]['group']}'",
       "read from the ledger: every call this notebook made, by role, and the latency of each model")
save_exp("accounts", {"calls": sum(r["calls"] for r in by_role), "paid": SPENT, "top": top_roles[0]["group"], "top_calls": top_roles[0]["calls"],
                      "second": top_roles[1]["group"], "second_calls": top_roles[1]["calls"], "by_role": by_role, "by_model": by_model,
                      "dear_model": max(by_model, key=lambda r: (r["cents"] or 0) / max(r["calls"], 1))["group"].split("/")[-1] if by_model else "",
                      "dear_calls": max(by_model, key=lambda r: (r["cents"] or 0) / max(r["calls"], 1))["calls"] if by_model else 0,
                      "dear_cents": max(by_model, key=lambda r: (r["cents"] or 0) / max(r["calls"], 1))["cents"] or 0 if by_model else 0})

#%% md
**Reading FIG {{figures.s71_accounts}} (s71_accounts).** Left: calls by role. The most went to *{{accounts.top}}* ({{accounts.top_calls}} calls), then *{{accounts.second}}* ({{accounts.second_calls}}). Roles that read the library are called many times over, because the experiments read it again for every arm and every run. Right: each model's latency per call. This number sets the wall clock of every phase, because a phase waits for its slowest call. Billing is per token, so the cheapest plan is the one that sends the fewest tokens, which mostly means reading each piece of code as few times as it can. The fastest plan is the one whose phases wait least for their slowest call. These are usually different plans. The dearest model per call was {{accounts.dear_model}}: {{accounts.dear_calls}} calls cost {{accounts.dear_cents|.0f}} cents in all, nearly all of them scans for the routing card of S48.

## S72 - Use it on your own task

The engine needs three things from you: a **kit** (your job's words for plans, as in S31, S59 and S60), a **page** (the facts a lead plans from, as in S33), and a **stand-in** for the dry run. Everything else, the runtime, the checks, the dry run, the gate, the budget, the events, is shared. The smallest complete example: a kit with one step that asks a worker to summarise each of three short texts, a page, and the lead's plan for it, run end to end.

#%% code
TEXTS = {1: "The library adds lenses to scan workers.", 2: "A budget pauses work at the cap.", 3: "Plans are checked before they run."}


class SummaryKit:
    """The smallest kit: one step, summarise(ids), for three short texts."""

    def __init__(self, run, number=0):
        self.run = run

    def summarise(self, ids):
        obj = self.run.agent(data="\n".join(f"{i}: {TEXTS[i]}" for i in ids), system="Summarise each text in five words. "
                             'Answer with one JSON object: {"summaries": [{"id": 1, "summary": "..."}]}.',
                             schema={"type": "object", "required": ["summaries"]}, model="fast", label="summarise", thinking=False)
        return {s.get("id"): s.get("summary") for s in (obj or {}).get("summaries", []) if isinstance(s, dict)}

    def names(self):
        return {"phase": self.run.phase, "log": self.run.log, "parallel": self.run.parallel, "texts": sorted(TEXTS), "summarise": self.summarise}


@SCRIPTED.register
def _summaries(model, messages, params):
    if not messages[0]["content"].startswith("Summarise each text in five words"):
        return None
    return json.dumps({"summaries": [{"id": int(i), "summary": t[:30]} for i, t in re.findall(r"^(\d+): (.*)$", messages[-1]["content"], re.M)]})

show_def(SummaryKit, _summaries)
own_src = 'phase("Summarise")\nresult = summarise(texts)'
own_run = Run("your own task", run_id="s72-own-task", concurrency=2)
own_result = own_run.run_sync(lambda r: run_program(own_src, SummaryKit(own_run)))
print(f"[own task] {own_run.status}: {own_result}")
results = []
expect("a new kit with one step runs on the unchanged engine", own_run.status == "completed" and len(own_result or {}) == 3)

#%% md
## S73 - Adopting it: what to switch on first

Two guards are worth switching on whatever the measurements say:

- a cap where the spending happens, with pause and resume (S26);
- a dry run with an approval gate before any generated plan may spend (S37).

They cost almost nothing, and they prevent the expensive mistakes. For everything else, the order below is computed from the ablation ledger of S55: features whose removal measurably hurt come first. A NEUTRAL feature is not proven useless. It is not proven useful on this job, and it costs calls, so measure it on your own job before you pay for it.

#%% code
rank = {"KEPT": 0, "NEUTRAL": 1, "REPORTED": 2, "HARMFUL": 3}
ADOPT = sorted([{"feature": r["feature"], "verdict": r["verdict"], "evidence": f"{r['est']:+.3f} {r['metric']} when removed", "order": r["est"]}
                for r in ABLATION] + [{"feature": d["feature"], "verdict": d["verdict"], "evidence": f"{d['metric']}: {d['value']}", "order": 0.0}
                                      for d in DESCRIBED], key=lambda r: (rank.get(r["verdict"], 3), r["order"]))
table(ADOPT, [("feature", "feature", ""), ("verdict", "verdict", ""), ("evidence", "evidence", "")])
print(f"[adopt] switch on first: {', '.join(r['feature'] for r in ADOPT if r['verdict'] == 'KEPT') or 'nothing beyond the two guards'}")

#%% md
For long lists of small items, S59 measured how one grader's accuracy moved as it read down the stack: {{hw_run.slope_single|+.3f}} per 100 items, against {{hw_run.slope_wf|+.3f}} for the workflow's fresh workers. And leave the workflow off for a job that one worker can do in one call, or a job that is a chain of dependent steps (S61).

## S74 - Reproducing this notebook

The notebook is built from the sources in `_build/src/` and runs in three modes:

| command | what it does | network | cost |
|---|---|---|---|
| `.venv/bin/python _build/run.py smoke` | every section on a free scripted stand-in; checks that all code runs; numbers are invented | none | free |
| `CLAUDE_API_KEY=... .venv/bin/python _build/run.py collect` | real models for anything the ledger lacks; writes the ledger and the notebook | the model provider | cents, capped at 2,500 |
| `.venv/bin/python _build/run.py replay` | every answer from the committed ledger; produces the same notebook offline | none | free |

`_build/checks.py` then checks the style rules, the placeholders, the figures and that the API key appears in no file. Part I's data is rebuilt from the snapshot on every run and is byte-identical between runs (S1).

## S75 - The manifest

#%% code
KNOBS = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float, str, bool)) and not k.startswith("_")
         and k not in ("API_KEY",) and len(str(v)) < 120}
MANIFEST = {"mode": DW_MODE, "models": MODELS, "prices": {m: PRICE.get(m) for m in MODELS.values()}, "knobs": KNOBS,
            "prereg_sha256": PREREG_SHA, "answer_key_bugs": len(ANSWER_KEY), "corpus_files": len(CORPUS),
            "homework_sha256": HW_SHA, "figures": len(FIG_NUMBERS), "ledger_calls": sum(r["calls"] for r in by_role), "paid_cents": SPENT}
(ART / "manifest.json").write_text(json.dumps(MANIFEST, indent=1, default=str), encoding="utf-8")
print(f"[manifest] {len(KNOBS)} settings, {len(MODELS)} model roles, {MANIFEST['figures']} figures; written to {rel(ART / 'manifest.json')}")
for k in ("CAP_CENTS", "SEED", "RUNS", "SHARD_TOKENS", "TEMPERATURE", "MAX_AGENTS_PER_RUN"):
    print(f"  {k:<20} {KNOBS.get(k)}")
leaky = [p for p in [ART / "manifest.json", PREREG_PATH] if API_KEY and API_KEY in p.read_text(encoding="utf-8")] if API_KEY else []
results = []
expect("the manifest holds no API key", not leaky)

#%% md
Done.
