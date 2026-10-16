#%% md
## S27 - Runs in the background

**Theory.** A run of a hundred workers takes many minutes. The lead, and the person watching, should not be frozen for that long. **`Run.start(plan)`** executes the plan on a background thread and returns at once; **`wait()`** blocks until it is done and returns the result; **`cancel()`** asks it to stop, so workers that have not started yet never start; and **`statusline()`** is a one-line answer to "how is it going?" that can be asked at any moment, from any thread. While the run works, the lead is free: it can answer the user, prepare the next step, or start another run.

**In plain terms.** Start the run, get on with something else, and glance at its status whenever you like.

**For teams.** Anything that takes longer than a person will wait in front of a screen should run in the background and report through events and a status line. Then it can also be watched by software, not only by people.

#%% code
@method_of(Run)
def start(self, plan):
    self._worker = threading.Thread(target=self._execute, args=(plan,), daemon=True, name=self.run_id)
    self._worker.start()
    return self


@method_of(Run)
def wait(self, timeout=None):
    if self._worker is not None:
        self._worker.join(timeout)
    return self.result


@method_of(Run)
def cancel(self):
    if not self.cancelled.is_set():
        self.log("cancel requested")
    self.cancelled.set()


@method_of(Run)
def statusline(self):
    running = sum(t.status == "running" for t in self.threads)
    done = sum(t.status == "done" for t in self.threads)
    failed = sum(t.status == "failed" for t in self.threads)
    paused = " | PAUSED at the budget" if self.llm.budget is not None and self.llm.budget.paused else ""
    phase = self.current["name"] if self.current else "-"
    return (f"{self.run_id} | {self.status} | phase {len(self.phases)}: {phase} | {running} running, {done} done, "
            f"{failed} failed | {sum(t.cost for t in self.threads):.1f}¢ | {self.elapsed():.1f}s{paused}")

show_def(Run.start, Run.wait, Run.cancel, Run.statusline)

#%% md
**A run in the background, watched.** A three-phase plan starts on the demo server. While it works, the notebook's own thread plays the lead: it asks for the run's status line ten times a second and drafts a line of its memo in between, to show that it is not blocked. It prints the status when the run enters a new phase, and otherwise once a second. Then it waits for the result.

#%% code
def three_phases(run):
    run.phase("Read")
    run.parallel([lambda i=i: run.agent(f"bg read {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"read#{i}") for i in range(16)])
    run.phase("Check")
    run.parallel([lambda i=i: run.agent(f"bg check {i}", schema=DEMO_SCHEMA, model="fake-judge", label=f"check#{i}") for i in range(8)])
    run.phase("Combine")
    return run.agent("bg combine", schema=DEMO_SCHEMA, model="fake-worker", label="combine")

show_def(three_phases, layer="plan")
bg = Run("background demo", run_id="s27-background", llm=demo_llm(), concurrency=8).start(three_phases)
memo, polls, printed, last_phase, last_t = [], 0, 0, None, -1.0
while bg.status in ("created", "running") and polls < 600:
    line, now = bg.statusline(), bg.elapsed()
    if len(bg.phases) != last_phase or now - last_t >= 1.0:          # a new phase, or a second since the last line
        print("  " + line)
        printed, last_phase, last_t = printed + 1, len(bg.phases), now
    memo.append(f"note {polls}: the lead keeps working while the run runs")
    time.sleep(0.1)
    polls += 1
result = bg.wait()
print("  " + bg.statusline())
print(f"[background] polled the status {polls} times and printed it {printed} times: at each new phase, otherwise once a second")
print(f"[background] result {result}; the lead wrote {len(memo)} lines of its memo while waiting; final status {bg.status}")

#%% md
## S28 - Resume: a crash costs only the calls that had not been made

**Theory.** A long run will sometimes die halfway: the laptop sleeps, the kernel restarts, the network drops, somebody presses stop. Many systems answer this with a **journal**, a separate log of completed steps that a restart reads back. We already have one. Every answer is in the ledger under the fingerprint of its request, and a plan that is run again asks the same questions in the same way. So **resuming is just running the plan again**: every call that completed before the crash is answered from the ledger at once and for free, and only the calls that never completed reach the network.

This only works if the plan is **deterministic**: given the same answers, it must ask the same questions. That is why plans in this notebook never read the clock or draw random numbers. When they need variety, such as three skeptics asking about the same finding, they vary the sample index on purpose, and the index is part of the fingerprint. Part V's plan validator enforces the rule for plans the lead writes.

**In plain terms.** Because every answer is saved, running the same plan again after a crash replays what was done for free and pays only for what was not.

**For teams.** Make your workflow steps pure functions of their inputs and your cache keyed by those inputs, and you get resume for nothing. Add a clock or a random seed to a prompt, and you lose it.

#%% code
RESUME_DIR = Path(tempfile.mkdtemp())


def resumable_llm():
    """A front door to the demo server whose ledger survives between runs, like the real one."""
    client = ModelClient("ms-demo-key-not-real-000000", endpoint=DEMO_SERVER.endpoint, gate_factory=lambda m: AIMDGate(16, 64))
    return LLM("collect", Ledger(RESUME_DIR / "resume.sqlite"), client)


def thirty_items(run):
    run.phase("Scan, then verify, per item")
    return run.pipeline(range(30),
                        lambda _, it, i: run.agent(f"resume scan {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"scan#{i}", phase="Scan"),
                        lambda _, it, i: run.agent(f"resume verify {i}", schema=DEMO_SCHEMA, model="fake-judge", label=f"verify#{i}", phase="Verify"))

show_def(resumable_llm, thirty_items)
crash = Run("resume demo", run_id="s28-resume", llm=resumable_llm(), concurrency=8)
threading.Timer(0.9, crash.cancel).start()                      # the crash: somebody presses stop
c0 = DEMO_SERVER.calls
crash.run_sync(thirty_items)
paid_before = DEMO_SERVER.calls - c0
again = Run("resume demo", run_id="s28-resume", llm=resumable_llm(), concurrency=8)
c1 = DEMO_SERVER.calls
again.run_sync(thirty_items)
paid_after = DEMO_SERVER.calls - c1
fresh = Run("resume reference", run_id="s28-fresh", llm=demo_llm(), concurrency=8)
c2 = DEMO_SERVER.calls
fresh.run_sync(thirty_items)
paid_fresh = DEMO_SERVER.calls - c2
from_ledger = sum(1 for t in again.threads for r in t.replies if r.cached)
print(f"[resume] crashed run: status {crash.status}, {sum(t.status == 'done' for t in crash.threads)} workers finished, {paid_before} calls paid")
print(f"[resume] resumed run: status {again.status}, {from_ledger} answers from the ledger, {paid_after} new calls paid")
print(f"[resume] a run without a crash pays {paid_fresh} calls; crash plus resume paid {paid_before + paid_after}")
print(f"[resume] the resumed result equals the uninterrupted one: {again.result == fresh.result}")

#%% code
# FIG  what a crash costs when every answer is kept
fig, ax = plt.subplots(figsize=(8.6, 3.0))
ax.barh(1, paid_before, color=C1, height=0.55, label="paid before the crash")
ax.barh(1, paid_after, left=paid_before, color=C7, height=0.55, label="paid after resuming")
ax.barh(0, paid_fresh, color=MUTED, height=0.55, label="a run that never crashed")
ax.text(paid_before + paid_after, 1, f"  {paid_before + paid_after} calls", va="center", fontsize=8.5)
ax.text(paid_fresh, 0, f"  {paid_fresh} calls", va="center", fontsize=8.5)
ax.set_yticks([0, 1], ["no crash", "crash, then resume"])
ax.set_xlabel("calls that reached the server")
ax.set_xlim(0, max(paid_fresh, paid_before + paid_after) * 1.25)
ax.legend(fontsize=8, loc="lower right")
finish(fig, "s28_resume", f"A crash halfway cost nothing extra: {paid_before + paid_after} calls with the crash, {paid_fresh} without",
       f"{from_ledger} answers came back from the ledger on resume; the final result matched the uninterrupted run")

#%% md
**Reading FIG {{figures.s28_resume}} (s28_resume).** The run was stopped after {{resume.paid_before}} calls had been paid for. Running the same plan again answered those {{resume.from_ledger}} calls from the ledger in an instant and paid only for the {{resume.paid_after}} that were missing. Together that is {{resume.total}} calls, the same as the {{resume.fresh}} a run that never crashed pays, and the final results are identical. There is no separate journal, no checkpoint file and no recovery code: the ledger built in S8 for cost and replay already does the job.

#%% md
## S29 - Backstops: limits that say what they dropped

**Theory.** A plan written by a model can contain a mistake that asks for far too much work, such as a loop that never stops or a fan-out over a list a thousand times longer than intended. The budget limits the money such a plan can spend, but two cheap limits catch it sooner. A run may start at most `MAX_AGENTS_PER_RUN` workers, and one `parallel()` or `pipeline()` call accepts at most `MAX_ITEMS_PER_CALL` items. The rule that matters most is about what happens at a limit: **no silent caps.** Work refused by a limit is announced with a `run.dropped` event, saying what was dropped and how much. A run that quietly did a third of its job and reported success is worse than a run that failed, because nobody looks at it twice.

One more rule turns a limit into a stop. A plan that keeps asking for workers after the limit, until it has asked for twice as many as allowed, is not a plan that slightly overshot: it is a runaway loop. The run then cancels itself, says why in its event stream, and ends with the status `cancelled`.

**In plain terms.** There are hard limits on how many workers a run may start, and whenever a limit cuts something off, the run says so out loud. A plan that keeps pushing against the limit is stopped.

#%% code
greedy_run = Run("a plan that asks for too many workers", run_id="s29-agents", llm=demo_llm(), max_agents=10)
greedy_run.run_sync(lambda run: (run.phase("Work"), run.parallel([lambda i=i: run.agent(f"backstop {i}", schema=DEMO_SCHEMA,
                    model="fake-worker", label=f"w#{i}") for i in range(15)]))[1])
saved_items, MAX_ITEMS_PER_CALL = MAX_ITEMS_PER_CALL, 8                 # a small limit, only for this demonstration
items_run = Run("a plan that passes too many items", run_id="s29-items", llm=demo_llm())
items_run.run_sync(lambda run: (run.phase("Work"), run.parallel([lambda i=i: run.agent(f"items {i}", schema=DEMO_SCHEMA,
                   model="fake-worker", label=f"i#{i}") for i in range(12)]))[1])
MAX_ITEMS_PER_CALL = saved_items
for r in (greedy_run, items_run):
    drops = [e for e in r.bus.events if e["type"] == "run.dropped"]
    ended = r.bus.events[-1]
    print(f"[{r.run_id}] {len(r.threads)} workers ran; {len(drops)} dropped events; first: "
          f"{ {k: drops[0][k] for k in drops[0] if k in ('what', 'count', 'limit')} if drops else None}; "
          f"run.ended reports dropped={ended.get('dropped')}")
results = []
expect("the agent limit stopped the run at 10 workers and announced the rest",
       len(greedy_run.threads) == 10 and sum(e["type"] == "run.dropped" for e in greedy_run.bus.events) == 5)
expect("the item limit announced the 4 items it cut", any(e["type"] == "run.dropped" and e.get("count") == 4 for e in items_run.bus.events))
expect("each run's final event counts everything its limits dropped",
       greedy_run.bus.events[-1].get("dropped") == 5 and items_run.bus.events[-1].get("dropped") == 4)
runaway = Run("a plan that never stops asking", run_id="s29-runaway", llm=demo_llm(), max_agents=5)
runaway.run_sync(lambda run: [run.agent(f"loop {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"r#{i}") for i in range(500)])
print(f"[{runaway.run_id}] status {runaway.status}; {len(runaway.threads)} workers ran, {len(runaway.dropped)} were refused; "
      f"last log: {next(e['message'] for e in reversed(runaway.bus.events) if e['type'] == 'run.log')}")
expect("a plan asking for twice its limit is cancelled as a runaway", runaway.status == "cancelled" and len(runaway.dropped) == 5)

#%% md
## S30 - Watching a run

**Theory.** The events and threads are all we need to see a run from three distances:

- **The status line** (S27), for a glance while it runs.
- **The portrait**, for an overview afterwards. It is a picture built only from the event stream: one lane per worker, coloured by phase, with phase boundaries, failures and pauses marked, and below it the number of workers in flight over time.
- **The thread**, for detail: open any worker and read its conversation (S20).

**`portrait(run)`** draws the second view for any run, from its recorded events. Because it reads only events, it works the same for a run that just finished, a run on disk, or a run being replayed.

**In plain terms.** One line while it runs, one picture when it is done, and the full conversation of any worker you want to check.

#%% code
def portrait(run_or_id, title=None, sub=None, name=None):
    """Lanes per worker coloured by phase, phase boundaries, pauses and failures; workers in flight below."""
    run_id = run_or_id if isinstance(run_or_id, str) else run_or_id.run_id
    path = RUNS_DIR / run_id / "events.jsonl"
    events = ([json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()] if path.exists() else run_or_id.bus.events)
    lanes = timeline(run_or_id)
    phases = list(dict.fromkeys(ph for _, ph, *_ in lanes))
    colour = {ph: PALETTE[i % len(PALETTE)] for i, ph in enumerate(phases)}
    fig, axes = plt.subplots(2, 1, figsize=(10.6, 0.16 * len(lanes) + 2.4), sharex=True,
                             gridspec_kw={"height_ratios": [max(2, 0.16 * len(lanes)), 1]})
    ax = axes[0]
    for k, (label, ph, s, e, ok) in enumerate(lanes):
        ax.barh(k, e - s, left=s, color=colour[ph] if ok else C8, height=0.75)
    for e in events:
        if e["type"] == "run.phase_ended":
            ax.axvline(e["t"], color=INK2, ls=":", lw=0.8)
    pauses = [e["t"] for e in events if e["type"] == "run.paused"]
    resumes = [e["t"] for e in events if e["type"] == "run.resumed"]
    for p0, p1 in zip(pauses, resumes + [events[-1]["t"]] * len(pauses)):
        ax.axvspan(p0, p1, color=C4, alpha=0.15)
    ax.set_yticks([])
    ax.invert_yaxis()
    ax.set_ylabel(f"{len(lanes)} workers")
    handles = [plt.Rectangle((0, 0), 1, 1, color=colour[ph]) for ph in phases]
    ax.legend(handles, phases, fontsize=7.5, loc="lower right")
    ax = axes[1]
    grid = np.linspace(0, max(e for *_, e, _ in lanes), 400)
    ax.plot(grid, [sum(s <= g < e for _, _, s, e, _ in lanes) for g in grid], color=C1, lw=1.5)
    ax.set_ylabel("in flight")
    ax.set_xlabel("seconds since the run started")
    finish(fig, name or f"portrait_{run_id}", title or f"Run {run_id}", sub)

show_def(portrait)

#%% code
# FIG  the portrait of the budget demo run: phases, the pause, and the workers in flight
portrait(capped, name="s30_portrait_budget", title="A run, drawn from its events alone: the pause is where nothing new starts",
         sub="the budget demo of S26; amber band: paused at the cap; lower panel: workers in flight")

#%% md
**Reading FIG {{figures.s30_portrait_budget}} (s30_portrait_budget).** This is the budget run from S26, drawn from nothing but its event stream. Each lane is one worker. During the amber band no new lane starts: the run was paused at the cap, and the lower panel shows the number of workers in flight while the calls already admitted finish. When the cap is raised the lanes start again, and the count in flight rises again. The same function draws every run in the notebook, real or demo, live or replayed, because it reads only events.

#%% code
# FIG  the portrait of the barrier and pipeline demos, side by side in time
portrait(PIPE, name="s30_portrait_pipeline", title="A two-stage pipeline: scans and verifies overlap from the first minute",
         sub="the pipeline demo of S24; colours are phases; there is no moment when everyone waits")

#%% md
**Reading FIG {{figures.s30_portrait_pipeline}} (s30_portrait_pipeline).** The pipeline run from S24. Scan lanes and verify lanes overlap, because each item's verify begins as soon as its own scan is done, with no gap of waiting between the stages. A barrier plan's portrait would show two separate blocks with a gap of waiting between them.

#%% md
**The event stream, read directly.** The printed stream of a run is often the quickest way to see what happened. Here are the first and last events of the background run from S27, and the counts of each type.

#%% code
def print_events(run, head=6, tail=4):
    ev = run.bus.events
    for e in ev[:head]:
        print_event(e)
    if len(ev) > head + tail:
        print(f"  ... {len(ev) - head - tail} more events ...")
    for e in ev[-tail:]:
        print_event(e)
    print("  counts: " + ", ".join(f"{k[4:]} {v}" for k, v in collections.Counter(e["type"] for e in ev).items()))

show_def(print_events)
print_events(bg)

#%% md
**A run browser.** In a live notebook, the widget below lists every run recorded so far and draws the portrait of the one you pick. In a static view, such as GitHub or the committed notebook, the table it prints first carries the same information.

#%% code
def run_index():
    """Every run recorded under artifacts/runs, from the run.ended event of its record."""
    rows = []
    for d in sorted(RUNS_DIR.iterdir()) if RUNS_DIR.exists() else []:
        f = d / "events.jsonl"
        if f.exists():
            ev = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
            end = next((e for e in reversed(ev) if e["type"] == "run.ended"), {})
            rows.append({"run": d.name, "status": end.get("status"), "agents": end.get("agents"), "seconds": end.get("seconds"),
                         "cents": end.get("cents"), "phases": sum(e["type"] == "run.phase_started" for e in ev)})
    return rows

show_def(run_index)
RUN_INDEX = run_index()
table(RUN_INDEX, [("run", "run", ""), ("status", "status", ""), ("phases", "phases", "d"), ("agents", "workers", "d"),
                  ("seconds", "seconds", ".1f"), ("cents", "cents", ".1f")])
W = widgets()
if W:
    pick = W.Dropdown(options=[r["run"] for r in RUN_INDEX], description="run")
    out = W.Output()

    def show(change):
        with out:
            out.clear_output()
            portrait(change["new"], name="browser_" + change["new"])
    pick.observe(show, names="value")
    display(W.VBox([pick, out]))
else:
    print("(the run browser needs a live Jupyter session; the table above lists the same runs)")

#%% code
save_exp("resume", {"paid_before": paid_before, "paid_after": paid_after, "total": paid_before + paid_after, "fresh": paid_fresh,
                    "from_ledger": from_ledger, "identical": again.result == fresh.result, "crash_status": crash.status})
save_exp("runtime", {"runs_recorded": len(RUN_INDEX), "background_status": bg.status, "memo_lines": len(memo)})
results = []
expect("the background run completed while the notebook kept working", bg.status == "completed" and len(memo) >= 1)
expect("the crashed run really stopped early", crash.status == "cancelled" and paid_before < paid_fresh)
expect("crash plus resume paid exactly what an uninterrupted run pays", paid_before + paid_after == paid_fresh)
expect("the resumed result equals the uninterrupted result", again.result == fresh.result)

#%% md
**Part IV recap.** The runtime is complete, and every piece was tested on its own:

- `agent()` runs one worker in its own thread and returns checked JSON or nothing; its conversation can be read afterwards;
- an event stream announces every step, and listeners cannot break it;
- `parallel()` runs a phase at once and would pay a straggler tax of {{parallel.rec_tax|.0%}} on the recorded latencies of real workers; `pipeline()` removed the barrier and finished {{pipeline.saving|.0%}} sooner;
- hedging costs extra calls, and the trade is measured: with spare capacity, hedging after the median paid {{hedging.extra_p50}} extra calls of 60 for {{hedging.wide_p50_verdict}};
- one budget covers the session; at the cap work pauses, and when the cap is raised it resumes with no call repeated;
- a crash costs nothing extra, because resuming is just running the plan again against the ledger;
- backstops announce what they drop, and any run can be drawn from its events.

What is still missing is the part that makes it dynamic: so far every plan was written by hand. Part V gives the pen to the lead.

**Try it yourself.**

1. In the S26 demo, lower the run's concurrency from 12 to 2 and rerun it. How does the pause look in the meter and in the portrait, and why?
2. Add a listener to a run that prints a line every time a phase ends, and another that raises an exception on every event. Confirm the run still completes and that `bus.health` counts the failures.
3. Change `thirty_items` so the verify prompt includes `time.time()`. Run the crash and resume demo again. What happens to the resumed run's cost, and why does Part V forbid the clock in plans?
