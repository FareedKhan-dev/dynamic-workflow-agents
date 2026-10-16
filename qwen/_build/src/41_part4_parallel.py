#%% md
## S23 - `parallel()`: a phase of workers at once, and the price of waiting

**Theory.** A **phase** is a set of workers that can run at the same time because none of them needs another's result. `parallel()` starts them all, lets the run's slots and the model gates decide how many are actually in flight, and returns their results in the order the work was given, with `None` for any that failed. It is a **barrier**: it returns only when the last worker is done. That is exactly what a phase needs when the next step requires *all* the results together, for example to remove duplicates across every finding before verifying any of them.

A barrier has a cost, the **straggler tax**. Workers finish at different times, because shards differ and models think for different lengths, and every worker that finishes early then sits idle until the slowest one is done. We measure it as the share of worker-time spent waiting: zero when everyone finishes together, approaching one when a single slow worker holds up a phase of fast ones.

**In plain terms.** Everyone in the phase starts together, and the phase is over when the last one is done. Whoever finishes early waits.

**For teams.** Ask of every barrier in a design: does the next step really need *all* of these results, or would each result be useful on its own? S24 is the alternative for the second case.

#%% code
@method_of(Run)
def parallel(self, thunks):
    """Run every thunk at once; results in order, None for failures. A barrier: returns when all are done."""
    thunks = list(thunks)
    if len(thunks) > MAX_ITEMS_PER_CALL:
        cut = [f"item {i}" for i in range(MAX_ITEMS_PER_CALL, len(thunks))]
        with self.lock:
            self.dropped.extend(cut)                      # counted in run.ended, like a dropped agent
        self.bus.emit("run.dropped", what="parallel items", count=len(cut), limit=MAX_ITEMS_PER_CALL)
        thunks = thunks[:MAX_ITEMS_PER_CALL]
    out, aborts = [None] * len(thunks), []
    if not thunks:
        return out
    with cf.ThreadPoolExecutor(max(1, min(len(thunks), 64))) as pool:
        futures = {pool.submit(fn): i for i, fn in enumerate(thunks)}
        for f in cf.as_completed(futures):
            try:
                out[futures[f]] = f.result()
            except ABORT as e:
                aborts.append(e)
                self.cancelled.set()                       # stop work that has not started yet
            except Exception as e:
                self.log(f"a parallel task failed: {type(e).__name__}: {e}")
    if aborts:
        raise aborts[0]
    return out

show_def(Run.parallel)

#%% md
**Twelve real workers.** One phase, twelve shards of the corpus (the twelve that hold the most planted bugs), twelve scan workers at once. The run's record keeps the true timeline, which the figure below draws as **lanes**: one bar per worker, from the moment it started to the moment it finished.

#%% code
bugs_per = {i: sum(b["path"] in s for b in ANSWER_KEY) for i, s in enumerate(SHARDS)}
TWELVE = sorted(sorted(bugs_per, key=lambda i: -bugs_per[i])[:12])
par_run = Run("twelve workers in one phase", run_id="s23-parallel", concurrency=12)


def twelve(run):
    run.phase("Scan")
    outs = run.parallel([lambda i=i: run.agent(**scan_task(SHARDS[i]), schema=FINDINGS_SCHEMA, label=f"scan#{i}") for i in TWELVE])
    return [f for i, o in zip(TWELVE, outs) for f in findings_of(o, f"scan#{i}")]

show_def(twelve, layer="plan")
par_found = par_run.run_sync(twelve)
LANES = timeline(par_run)
span = max(e for _, _, _, e, _ in LANES) - min(s for _, _, s, _, _ in LANES)
phase_end = max(e for _, _, _, e, _ in LANES)
idle = sum(phase_end - e for _, _, _, e, _ in LANES)
STRAGGLER_TAX = idle / (len(LANES) * span) if span > 0 else 0.0
par_score = match(par_found, key=[b for b in ANSWER_KEY if any(b["path"] in SHARDS[i] for i in TWELVE)])
print(f"[parallel] {len(LANES)} workers, {sum(ok for *_, ok in LANES)} succeeded; the phase took {span:.1f}s "
      f"(the fastest worker {min(e - s for _, _, s, e, _ in LANES):.1f}s, the slowest {max(e - s for _, _, s, e, _ in LANES):.1f}s)")
print(f"[parallel] straggler tax: {STRAGGLER_TAX:.0%} of worker-time was spent waiting for the slowest")
bugs_here = sum(1 for b in ANSWER_KEY if any(b["path"] in SHARDS[i] for i in TWELVE))
print(f"[parallel] {len(par_found)} findings; {par_score.tp} of the {bugs_here} planted bugs in these shards found; "
      f"cost {cost_of('s23-parallel')['magicubes']:.1f} Magicubes")

#%% code
# FIG  twelve workers in one phase, and the barrier at the end
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6), gridspec_kw={"width_ratios": [1.6, 1]})
ax = axes[0]
for k, (label, ph, s, e, ok) in enumerate(LANES):
    ax.barh(k, e - s, left=s, color=C1 if ok else C8, height=0.62)
    ax.barh(k, phase_end - e, left=e, color=GRID, height=0.62)
ax.axvline(phase_end, color=INK, ls="--", lw=1)
ax.text(phase_end, len(LANES) - 0.4, " barrier", fontsize=8)
ax.set_yticks(range(len(LANES)), [l for l, *_ in LANES], fontsize=7.5)
ax.invert_yaxis()
ax.set_xlabel("seconds since the run started")
panel(ax, "blue: working; grey: finished, waiting for the slowest")
ax = axes[1]
durs = sorted(e - s for _, _, s, e, _ in LANES)
ax.bar(range(len(durs)), durs, color=[C1] * (len(durs) - 1) + [C8], width=0.7)
ax.set_xlabel("workers, fastest to slowest")
ax.set_ylabel("seconds of work")
panel(ax, f"the slowest took {durs[-1] / max(durs[0], 1e-9):.1f} times as long as the fastest")
finish(fig, "s23_lanes", f"Twelve workers ran at once; {STRAGGLER_TAX:.0%} of their time went to waiting for the slowest",
       f"one phase of real scan workers, {SHARD_TOKENS // 1000}k-token shards; timeline as recorded when the calls were made")

#%% md
**Reading FIG {{figures.s23_lanes}} (s23_lanes).** Each row in the left panel is one worker: the blue bar is the time it spent working, and the grey bar is the time it spent finished but waiting for the phase to end. All twelve started within moments of each other, which is the point of a phase: twelve shards took {{parallel.span|.0f}} s instead of the {{parallel.serial|.0f}} s they would take one after another. The grey bars are the straggler tax, {{parallel.tax|.0%}} of all worker-time here. The right panel shows where it comes from. Work times are uneven, the slowest worker took {{parallel.spread|.1f}} times as long as the fastest, and with a barrier the slowest one sets the pace for everybody.

#%% md
## S24 - `pipeline()`: letting each item move on as soon as it is ready

**Theory.** Many plans have stages that apply to each item on its own: scan a shard, then verify that shard's findings. Verifying shard 3 needs only shard 3's findings, not everyone's. A barrier between the stages would make shard 3's verification wait for the slowest scan anywhere. **`pipeline(items, stage1, stage2, ...)`** removes that wait. Each item flows through all the stages on its own, so one item can be in stage 2 while another is still in stage 1. The total time becomes the slowest single **item's** chain, instead of the sum of the slowest of each **stage**. A stage receives the previous stage's result, the original item and its index, and if a stage returns `None` that item stops there.

To measure the difference fairly we need the same work done twice, once each way, with the same latencies. Real model calls cannot give us that: the second run would come from the ledger in no time, and two live runs would have different latencies. So this comparison runs on the local server from S6, with every call delayed by a latency drawn from the **distribution we actually measured** on real scan workers in S13, scaled down forty times so the demo takes seconds instead of minutes. The delay of each request depends only on its text, so both plans see exactly the same latencies.

**In plain terms.** Do not make every item wait at every step for the slowest item; let each one go on as soon as its own previous step is done.

**For teams.** Draw your plan as stages and ask, for each arrow between stages, whether it is per item or needs everything. Most arrows are per item.

#%% code
@method_of(Run)
def pipeline(self, items, *stages):
    """Each item flows through every stage on its own; no barrier between stages. Results in item order."""
    items = list(items)

    def flow(i, item):
        value = item
        for stage in stages:
            value = stage(value, item, i)
            if value is None:
                return None
        return value
    return self.parallel([lambda i=i, it=it: flow(i, it) for i, it in enumerate(items)])

show_def(Run.pipeline)

#%% md
**The emulation.** `LATENCY_TRACE` holds the measured seconds of real scan calls, from the ledger. In a smoke run there are none yet, so it falls back to a log-normal distribution with a 40-second median, and says so. `trace_delay(text)` maps each request to one quantile of the trace, deterministically. The demo server uses it, and `demo_llm()` returns a front door wired to that server with a fresh, private ledger, so every demo run pays only in demo calls and never touches the real accounts.

#%% code
LATENCY_TRACE = sorted(s for (s,) in LEDGER.query("SELECT seconds FROM calls WHERE role = 'scan' AND seconds > 1"))
TRACE_SOURCE = f"{len(LATENCY_TRACE)} measured scan calls"
if len(LATENCY_TRACE) < 20:
    LATENCY_TRACE = sorted(np.exp(np.random.default_rng(SEED).normal(np.log(40), 0.6, 400)).tolist())
    TRACE_SOURCE = "an assumed log-normal (median 40 s), because no live scans exist in this mode"
TIME_SCALE = 1 / 40


def trace_delay(text):
    """A latency drawn from the measured distribution, fixed by the request's text, scaled down."""
    q = (zlib.crc32(text.encode()) % 10_000) / 10_000
    return LATENCY_TRACE[int(q * (len(LATENCY_TRACE) - 1))] * TIME_SCALE


DEMO_SERVER = FakeModelServer(capacity=256, delay_fn=trace_delay, json_fn=lambda body: {"answer": "ok"})
for m in ("fake-worker", "fake-judge"):
    PRICE[m] = 0.2
    CAN[m] = {"answers", "JSON mode", "thinking off"}
DEMO_SCHEMA = {"type": "object", "required": ["answer"]}


def demo_llm(gate=None):
    """A front door to the demo server with a fresh ledger: free, live, and the same in every mode.
    gate=None: the learning gate of S10, starting at 32 calls in flight; an integer: a fixed number of slots."""
    factory = (lambda m: AIMDGate(32, 256)) if gate is None else (lambda m: FixedGate(gate))
    client = ModelClient("ms-demo-key-not-real-000000", endpoint=DEMO_SERVER.endpoint, gate_factory=factory)
    return LLM("collect", Ledger(Path(tempfile.mkdtemp()) / "demo.sqlite"), client)

show_def(trace_delay, demo_llm)
print(f"[trace] latencies from {TRACE_SOURCE}: median {np.median(LATENCY_TRACE):.1f}s, 90th percentile "
      f"{np.percentile(LATENCY_TRACE, 90):.1f}s, slowest {max(LATENCY_TRACE):.1f}s; demo time is 1/{int(1 / TIME_SCALE)} of that")

#%% md
**The comparison.** Twenty-four items, two stages each: a "scan" and a "verify". The barrier plan runs all scans in one phase and all verifies in a second. The pipeline plan sends each item through both stages on its own. Both make exactly the same 48 calls with exactly the same latencies.

#%% code
N_ITEMS = 24


def barrier_plan(run):
    run.phase("Scan")
    run.parallel([lambda i=i: run.agent(f"scan item {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"scan#{i}") for i in range(N_ITEMS)])
    run.phase("Verify")
    return run.parallel([lambda i=i: run.agent(f"verify item {i}", schema=DEMO_SCHEMA, model="fake-judge", label=f"verify#{i}")
                         for i in range(N_ITEMS)])


def pipeline_plan(run):
    run.phase("Scan, then verify, per item")
    return run.pipeline(range(N_ITEMS),
                        lambda _, it, i: run.agent(f"scan item {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"scan#{i}", phase="Scan"),
                        lambda _, it, i: run.agent(f"verify item {i}", schema=DEMO_SCHEMA, model="fake-judge", label=f"verify#{i}", phase="Verify"))

show_def(barrier_plan, pipeline_plan)
calls_before = DEMO_SERVER.calls
DEMO_SERVER.reset_seen()                 # both plans see the same latencies for the same requests
BAR = Run("barrier", run_id="s24-barrier", llm=demo_llm(), concurrency=64)
BAR.run_sync(barrier_plan)
DEMO_SERVER.reset_seen()
PIPE = Run("pipeline", run_id="s24-pipeline", llm=demo_llm(), concurrency=64)
PIPE.run_sync(pipeline_plan)
bar_s = max(t.ended for t in BAR.threads)
pipe_s = max(t.ended for t in PIPE.threads)
print(f"[pipeline] barrier: {bar_s:.2f}s, pipeline: {pipe_s:.2f}s for the same {len(BAR.threads)} and {len(PIPE.threads)} calls "
      f"({DEMO_SERVER.calls - calls_before} reached the server); pipeline saves {1 - pipe_s / bar_s:.0%}")
ideal_bar = max(trace_delay(f"scan item {i}") for i in range(N_ITEMS)) + max(trace_delay(f"verify item {i}") for i in range(N_ITEMS))
ideal_pipe = max(trace_delay(f"scan item {i}") + trace_delay(f"verify item {i}") for i in range(N_ITEMS))
print(f"[pipeline] theory: barrier = slowest scan + slowest verify = {ideal_bar:.2f}s; pipeline = slowest single chain = {ideal_pipe:.2f}s")

#%% code
# FIG  the same 48 calls, with and without a barrier between the stages
fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.8), sharex=True)
for ax, run, name in ((axes[0], BAR, "barrier between stages"), (axes[1], PIPE, "pipeline, no barrier")):
    for k in range(N_ITEMS):
        for t in run.threads:
            if t.label in (f"scan#{k}", f"verify#{k}"):
                ax.barh(k, t.ended - t.started, left=t.started, color=C1 if t.label.startswith("scan") else C7, height=0.7)
    end = max(t.ended for t in run.threads)
    ax.axvline(end, color=INK, ls="--", lw=1)
    ax.text(end, -1.2, f" {end:.1f}s", fontsize=8)
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.set_xlabel("seconds (demo time)")
    panel(ax, name)
axes[0].set_ylabel("item")
finish(fig, "s24_pipeline", f"Without the barrier the same work finished {1 - pipe_s / bar_s:.0%} sooner",
       f"blue: scan, violet: verify; latencies drawn from {TRACE_SOURCE}, scaled 1/{int(1 / TIME_SCALE)}")

#%% md
**Reading FIG {{figures.s24_pipeline}} (s24_pipeline).** Each row is one item; blue is its scan and violet its verify. On the left, no verify starts before the slowest scan has finished, so the plan pays the slowest scan plus the slowest verify: {{pipeline.barrier_s|.1f}} s of demo time. On the right, each item's verify starts the moment its own scan is done, and the plan finishes when the slowest single item does: {{pipeline.pipeline_s|.1f}} s, {{pipeline.saving|.0%}} sooner, for exactly the same calls. The theory predicted {{pipeline.ideal_barrier|.1f}} s and {{pipeline.ideal_pipeline|.1f}} s. Pipelines are the default for the rest of the notebook; a barrier is used only where a step needs every result at once.

#%% md
## S25 - Hedged requests: an answer for the stragglers

**Theory.** When one request in a large batch is slow, the batch is slow. Large web services met this problem first and use a simple answer: if a request has not answered by the time most requests would have, send a **duplicate** and take whichever answer arrives first. This is called **hedging**. It trades a few extra calls for a much shorter tail. The question is the threshold. Hedging after the median duplicates half of all calls; hedging after the 95th percentile duplicates few but saves little. With per-call billing every duplicate costs a full call, so the trade is explicit, and we measure it.

`hedged()` starts the call, waits up to `after` seconds, and if no answer has come, starts a second call with a different sample index. It returns the first answer to arrive and records that two calls were made. The losing call is not cancelled: an HTTP request already sent cannot be taken back, and its answer still lands in the ledger.

**In plain terms.** If one worker is taking much longer than usual, start a second worker on the same job and take whichever finishes first.

**For teams.** Hedge where latency matters and calls are cheap compared with waiting. Measure the threshold; do not guess it.

#%% code
import queue


def hedged(ask, sample, after):
    """First answer of the call, or of a duplicate started if the call has not answered after `after` seconds."""
    box = queue.Queue()

    def go(s):
        try:
            box.put(("ok", ask(s)))
        except BaseException as e:
            box.put(("error", e))
    threading.Thread(target=go, args=(sample,), daemon=True).start()
    try:
        kind, value = box.get(timeout=after)
        copies = 1
    except queue.Empty:
        threading.Thread(target=go, args=(sample + 1000,), daemon=True).start()
        kind, value = box.get()
        copies = 2
    if kind == "error":
        raise value
    value.copies = copies
    return value

show_def(hedged)

#%% md
**The measurement.** Sixty calls at once on the demo server, whose latencies follow the measured distribution, are run without hedging and then with hedging at four thresholds: the 50th, 75th, 90th and 95th percentile of that distribution. For each setting we record the median call, the slowest call, which is what a barrier waits for, and the number of extra calls.

Hedging has a hidden requirement: **spare capacity**. A duplicate that has to queue for a slot starts late and rarely wins, and while it waits it may hold back calls that have not started at all. So the experiment runs under three gates. With **256 fixed slots** every duplicate leaves at once. With **40 fixed slots** the sixty calls already overflow the gate, and duplicates queue behind them in arrival order. With the **learning gate** of S10, which starts at 32 slots and lets any waiting call take a freed slot, duplicates compete with the calls they were meant to rescue.

#%% code
def hedge_trial(after_q, gate=256):
    DEMO_SERVER.reset_seen()             # every setting gets the same first latencies; only duplicates draw new ones
    name = "learning gate" if gate is None else f"{gate} fixed slots"
    run = Run(f"hedge {after_q}, {name}", run_id=f"s25-hedge-{after_q}-{gate or 'learning'}", llm=demo_llm(gate=gate), concurrency=128)
    after = None if after_q is None else float(np.percentile(LATENCY_TRACE, after_q)) * TIME_SCALE

    def plan(r):
        r.phase("Calls")
        return r.parallel([lambda i=i: r.agent(f"hedge item {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"call#{i}",
                                               hedge_after=after) for i in range(60)])
    run.run_sync(plan)
    durs = [t.ended - t.started for t in run.threads]
    extra = sum(getattr(r, "copies", 1) - 1 for t in run.threads for r in t.replies)
    return {"setting": "no hedging" if after_q is None else f"hedge after p{after_q}", "gate": name, "median": float(np.median(durs)),
            "p90": float(np.percentile(durs, 90)), "slowest": max(durs), "extra_calls": extra, "durations": durs}

show_def(hedge_trial)
HEDGE = [hedge_trial(q) for q in (None, 50, 75, 90, 95)]
TIGHT = [hedge_trial(q, gate=40) for q in (None, 50)]
LEARNING = [hedge_trial(q, gate=None) for q in (None, 50)]
table(HEDGE + TIGHT + LEARNING, [("gate", "gate", ""), ("setting", "setting", ""), ("median", "median s", ".2f"),
                                 ("p90", "90th pct s", ".2f"), ("slowest", "slowest s", ".2f"), ("extra_calls", "extra calls (of 60)", "d")])


def verdict(before, after, tol=0.05):
    """How a slowest-call time changed, in words."""
    d = after / max(before, 1e-9) - 1
    if abs(d) <= tol:
        return f"about the same slowest call ({d:+.0%})"
    return f"a slowest call {abs(d):.0%} {'slower' if d > 0 else 'faster'}"

show_def(verdict)
for rows in (TIGHT, LEARNING):
    print(f"[hedge] {rows[0]['gate']}: hedging after p50 took the slowest call from {rows[0]['slowest']:.2f}s to {rows[1]['slowest']:.2f}s "
          f"({verdict(rows[0]['slowest'], rows[1]['slowest'])})")

#%% code
# FIG  what hedging buys, and what it costs
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5))
ax = axes[0]
for h, colour in zip(HEDGE, [MUTED, C4, C1, C7, C3]):
    d = sorted(h["durations"])
    ax.plot(d, np.linspace(0, 1, len(d)), color=colour, lw=2 if h is HEDGE[0] else 1.5, label=h["setting"])
ax.set_xlabel("seconds per call (demo time)")
ax.set_ylabel("share of calls finished")
ax.legend(fontsize=7.5)
panel(ax, "the tail is what hedging cuts")
ax = axes[1]
for rows, colour, mark, label in ((HEDGE, C1, "o-", "256 fixed slots"), (TIGHT, C4, "s--", "40 fixed slots"),
                                  (LEARNING, C8, "^--", "learning gate")):
    ax.plot([h["extra_calls"] for h in rows], [h["slowest"] for h in rows], mark, color=colour, label=label)
for h in HEDGE:
    ax.annotate(h["setting"].replace("hedge after ", "").replace("no hedging", "none"), (h["extra_calls"], h["slowest"]),
                textcoords="offset points", xytext=(5, 4), fontsize=8)
ax.set_xlabel("extra calls paid for (of 60)")
ax.set_ylabel("slowest call, seconds")
ax.legend(fontsize=7.5)
panel(ax, "each point is one threshold under one gate")
best_h = min(HEDGE[1:], key=lambda h: h["slowest"] + 0.02 * h["extra_calls"])
finish(fig, "s25_hedging", f"With spare capacity, hedging after p{best_h['setting'].split('p')[-1]} took the slowest call from "
       f"{HEDGE[0]['slowest']:.1f}s to {best_h['slowest']:.1f}s for {best_h['extra_calls']} extra calls",
       f"60 calls on the demo server; latencies from {TRACE_SOURCE}, scaled 1/{int(1 / TIME_SCALE)}")

#%% md
**Reading FIG {{figures.s25_hedging}} (s25_hedging).** The left panel shows, for each setting with spare capacity, the share of calls finished after a given time. Without hedging (grey) the curve has a tail: a few calls take far longer than the rest, and a barrier waits for exactly those. The hedged curves reach the top sooner, because a straggler's duplicate often finishes first, while the median hardly moves: hedging only acts on calls that are already late. The right panel is the price. With 256 slots, hedging after the median paid for {{hedging.extra_p50}} extra calls of 60 and took the slowest call from {{hedging.slowest_none|.2f}} s to {{hedging.slowest_p50|.2f}} s; after the 90th percentile it paid for {{hedging.extra_p90}} and reached {{hedging.slowest_p90|.2f}} s. With 40 fixed slots the same median threshold gave {{hedging.tight_verdict}}, and through the learning gate {{hedging.learning_verdict}}: there the duplicates had to wait for slots before they could help. Two rules follow. Hedge only where there is spare capacity, and with per-call billing prefer a late threshold. Whether hedging earns its calls in the full system is decided in the ablation ledger of Part VII.

#%% code
save_exp("parallel", {"workers": len(LANES), "span": span, "serial": sum(e - s for _, _, s, e, _ in LANES), "tax": STRAGGLER_TAX,
                      "spread": durs[-1] / max(durs[0], 1e-9), "found": par_score.tp, "findings": len(par_found)})
save_exp("pipeline", {"barrier_s": bar_s, "pipeline_s": pipe_s, "saving": 1 - pipe_s / bar_s, "ideal_barrier": ideal_bar,
                      "ideal_pipeline": ideal_pipe, "items": N_ITEMS, "trace": TRACE_SOURCE})
save_exp("hedging", {"rows": [{k: v for k, v in h.items() if k != "durations"} for h in HEDGE + TIGHT + LEARNING],
                     "extra_p50": HEDGE[1]["extra_calls"], "extra_p90": HEDGE[3]["extra_calls"], "slowest_p50": HEDGE[1]["slowest"],
                     "tight_verdict": verdict(TIGHT[0]["slowest"], TIGHT[1]["slowest"]),
                     "learning_verdict": verdict(LEARNING[0]["slowest"], LEARNING[1]["slowest"]),
                     "slowest_none": HEDGE[0]["slowest"], "slowest_p90": HEDGE[3]["slowest"]})
results = []
expect("the parallel phase ran all twelve workers", len(LANES) == 12)
expect("the pipeline made the same number of calls as the barrier plan", len(PIPE.threads) == len(BAR.threads) == 2 * N_ITEMS)
expect("the pipeline finished sooner than the barrier plan", pipe_s < bar_s)
expect("every hedging setting answered all 60 calls", all(len(h["durations"]) == 60 for h in HEDGE))
expect("with spare capacity, hedging never made the slowest call slower", all(h["slowest"] <= HEDGE[0]["slowest"] * 1.1 for h in HEDGE[1:]))
expect("with spare capacity, every hedged setting paid for at least one extra call", all(h["extra_calls"] >= 1 for h in HEDGE[1:]))
