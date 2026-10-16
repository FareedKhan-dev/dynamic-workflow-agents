#%% md
## S54 - Scaling, with a simulator checked against real runs

**Theory.** How long would this plan take with 64 workers at once instead of 32? With a different shape? Running every variant for real would cost a fortune, so we build a **simulator** and make it earn trust first. It is deliberately simple: every worker is a task with a duration and a list of tasks it must wait for, and a fixed number of slots run tasks in the order they become ready. Durations are drawn from the latencies the ledger recorded for each role. Two checks come before any prediction:

1. **replay**: given the recorded duration of every worker of a real run and the same number of slots, the simulator must reproduce that run's recorded wall clock;
2. **prediction**: given only latencies drawn from one run, it must predict the wall clock of *another* run of the same plan.

Anything the simulator does not model, such as the rate gate of S10 holding calls back, shows up as error in these two checks, and the error is reported, not hidden. Every figure that uses the simulator says "simulated" in its subtitle.

**In plain terms.** A small program that pretends to run a plan, using real timings, so we can ask "what if" questions for free after checking that it reproduces runs we have really made.

**For teams.** Capacity planning for agent workflows is queueing, and queueing is easy to simulate. Validate the simulator on two real runs before you believe it on a third.

#%% code
import heapq


def schedule(tasks, slots):
    """Makespan of {task: (seconds, [tasks it waits for])} on `slots` slots, tasks starting in the order they become ready."""
    waiting = {t: set(deps) for t, (_, deps) in tasks.items()}
    children = collections.defaultdict(list)
    for t, (_, deps) in tasks.items():
        for d in deps:
            children[d].append(t)
    ready = collections.deque(sorted((t for t, d in waiting.items() if not d), key=str))
    running, now, finish = [], 0.0, {}
    while ready or running:
        while ready and len(running) < slots:
            t = ready.popleft()
            heapq.heappush(running, (now + tasks[t][0], str(t), t))
        now, _, t = heapq.heappop(running)
        finish[t] = now
        for c in children[t]:
            waiting[c].discard(t)
            if not waiting[c]:
                ready.append(c)
    return max(finish.values()) if finish else 0.0


def phased(durations_by_phase):
    """Tasks for a barrier plan: every task of a phase waits for every task of the phase before, through a zero-length barrier."""
    tasks, prev = {}, []
    for k, durs in enumerate(durations_by_phase):
        bar = f"barrier {k}"
        tasks[bar] = (0.0, prev)
        prev = []
        for j, d in enumerate(durs):
            tasks[(k, j)] = (d, [bar])
            prev.append((k, j))
    return tasks

show_def(schedule, phased)
toy_plan = phased([[3, 1, 1, 1], [2, 2]])
print(f"[sim] a toy plan: phases of 4 and 2 tasks; makespan with 4 slots {schedule(toy_plan, 4)}, with 2 slots {schedule(toy_plan, 2)}, "
      f"with 1 slot {schedule(toy_plan, 1)}")

#%% md
**Latencies.** **`latency_pool(role)`** collects the recorded seconds of every paid call of one role. In a smoke run there are none, and the pool falls back to the assumed distribution of S24, which every simulated figure then says.

#%% code
def latency_pool(role):
    """Recorded seconds of the paid calls of a role, or the assumed trace of S24 when there are too few."""
    xs = [s for (s,) in FRONT_DOOR.ledger.query("SELECT seconds FROM calls WHERE role = ? AND seconds > 0.5", (role,))]
    return (np.array(xs), "recorded") if len(xs) >= 20 else (np.array(LATENCY_TRACE), "assumed")

show_def(latency_pool)
POOLS = {r: latency_pool(r) for r in ("scan", "skeptic", "report", "lead")}
for r, (xs, src) in POOLS.items():
    print(f"[latency] {r:<8} {len(xs):>5} values ({src}): median {np.median(xs):.0f} s, 90th percentile {np.percentile(xs, 90):.0f} s")
SIM_SOURCE = "recorded" if all(src == "recorded" for xs, src in list(POOLS.values())[:2]) else "assumed (no recorded latencies in this mode)"

#%% md
**Check 1, replay.** The workers of the showcase run, with their recorded durations, grouped by phase, on the run's 32 slots.

#%% code
def recorded_phases(run_id):
    """Recorded worker durations of a run, grouped by phase in the order the phases started."""
    lanes = timeline(run_id)
    phases = list(dict.fromkeys(ph for _, ph, *_ in lanes))
    return [[e - s for _, ph, s, e, _ in lanes if ph == p] for p in phases]

show_def(recorded_phases)
REPLAY = []
for run_id, slots in ((SHOW_RUN.run_id, 32), (C_OBJS[0][0].run_id, 32)):
    durs = recorded_phases(run_id)
    sim = schedule(phased(durs), slots)
    real = recorded_seconds(run_id) or 0.0
    REPLAY.append({"run": run_id, "workers": sum(len(d) for d in durs), "recorded": real, "simulated": sim,
                   "error": sim / real - 1 if real > 0 else None})
table(REPLAY, [("run", "run", ""), ("workers", "workers", "d"), ("recorded", "recorded s", ".1f"), ("simulated", "simulated s", ".1f"),
               ("error", "error", "+.1%")])

#%% md
**Check 2, prediction.** The fixed plan's run 1, predicted from nothing but run 0: the number of workers per phase from run 1's plan, and durations drawn at random from run 0's recorded workers of the same phase. The prediction is the median over 200 draws, with the 5th and 95th percentiles.

#%% code
def predict(phase_counts, pools, slots=32, draws=200, seed=SEED):
    """(median, 5th, 95th percentile) simulated makespan with durations drawn from per-phase pools."""
    rng_ = np.random.default_rng(seed)
    out = [schedule(phased([rng_.choice(pool, n) for n, pool in zip(phase_counts, pools)]), slots) for _ in range(draws)]
    return float(np.median(out)), float(np.percentile(out, 5)), float(np.percentile(out, 95))

show_def(predict)
src_phases = recorded_phases(C_OBJS[0][0].run_id)
tgt_phases = recorded_phases(C_OBJS[1][0].run_id)
PRED = predict([len(d) for d in tgt_phases], [np.array(d) if len(d) else np.array([0.0]) for d in src_phases])
PRED_REAL = recorded_seconds(C_OBJS[1][0].run_id) or 0.0
PRED_ERR = PRED[0] / PRED_REAL - 1 if PRED_REAL > 0 else None
print(f"[predict] run 1 of the fixed plan: predicted {PRED[0]:.1f} s (5% to 95%: {PRED[1]:.1f} to {PRED[2]:.1f}), "
      f"recorded {PRED_REAL:.1f} s, error {PRED_ERR:+.1%}" if PRED_ERR is not None else "[predict] no recorded wall clock")

#%% md
**Scaling.** With the simulator checked, the showcase plan's phases are simulated with 1 to 64 slots, durations drawn from the recorded pools of the matching roles. **Speedup** is the time with one slot divided by the time with *n*. **Amdahl's law** says a job whose fraction *p* can run in parallel speeds up by at most 1 / ((1 − *p*) + *p* / *n*); fitting *p* to the simulated curve says how parallel the plan really is. Here the serial part is the barriers: each phase waits for its slowest worker, and the report waits for everything.

#%% code
def amdahl(n, p):
    return 1 / ((1 - p) + p / n)


def fit_amdahl(ns, speedups):
    """The parallel fraction p that best fits the speedups, by a fine grid search."""
    grid = np.linspace(0.5, 0.99999, 20000)
    err = [sum((amdahl(n, p) - s) ** 2 for n, s in zip(ns, speedups)) for p in grid]
    return float(grid[int(np.argmin(err))])

show_def(amdahl, fit_amdahl)
show_counts = [len(d) for d in recorded_phases(SHOW_RUN.run_id)]
show_roles = [collections.Counter(t.role for t in SHOW_RUN.threads if t.phase == p["name"]).most_common(1)[0][0]
              for p in SHOW_RUN.phases if any(t.phase == p["name"] for t in SHOW_RUN.threads)]
role_pool = {"scan": "scan", "skeptic": "skeptic", "report": "report"}
pools = [POOLS.get(role_pool.get(r, "scan"), POOLS["scan"])[0] for r in show_roles]
SLOTS = [1, 2, 4, 8, 16, 32, 64]
SCALE = [{"slots": n, "seconds": predict(show_counts, pools, slots=n, draws=40)[0]} for n in SLOTS]
for r in SCALE:
    r["speedup"] = SCALE[0]["seconds"] / max(r["seconds"], 1e-9)
P_PAR = fit_amdahl(SLOTS, [r["speedup"] for r in SCALE])
table(SCALE, [("slots", "slots", "d"), ("seconds", "simulated seconds", ".0f"), ("speedup", "speedup", ".1f")])
print(f"[amdahl] fitted parallel fraction p = {P_PAR:.4f}; the most any number of slots could give is {1 / (1 - P_PAR):.0f}x")

#%% code
# FIG  the simulator against real runs, then scaling the showcase plan
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6))
ax = axes[0]
labels = [r["run"] for r in REPLAY] + [f"{C_OBJS[1][0].run_id} (predicted)"]
real = [r["recorded"] for r in REPLAY] + [PRED_REAL]
sim = [r["simulated"] for r in REPLAY] + [PRED[0]]
x = np.arange(len(labels))
ax.bar(x - 0.18, real, 0.36, color=MUTED, label="recorded")
ax.bar(x + 0.18, sim, 0.36, color=C1, label="simulated")
ax.errorbar([x[-1] + 0.18], [PRED[0]], yerr=[[PRED[0] - PRED[1]], [PRED[2] - PRED[0]]], color=INK, capsize=4)
ax.set_xticks(x, labels, fontsize=7.5)
ax.set_ylabel("seconds")
ax.legend(fontsize=7.5)
panel(ax, "replay and prediction")
ax = axes[1]
ax.plot(SLOTS, [r["speedup"] for r in SCALE], "o-", color=C1, label="simulated")
grid_n = np.linspace(1, 64, 200)
ax.plot(grid_n, amdahl(grid_n, P_PAR), "--", color=C7, label=f"Amdahl, p = {P_PAR:.3f}")
ax.plot(grid_n, grid_n, ":", color=MUTED, label="perfect")
ax.set_xscale("log", base=2)
ax.set_yscale("log", base=2)
ax.set_xlabel("slots (workers at once)")
ax.set_ylabel("speedup over one slot")
ax.legend(fontsize=7.5)
panel(ax, "the showcase plan, simulated")
finish(fig, "s54_simulator", f"Simulated: the showcase plan speeds up {SCALE[-1]['speedup']:.0f}x with 64 slots; its parallel fraction is {P_PAR:.3f}",
       f"simulated from {SIM_SOURCE} latencies; left: replay of two recorded runs and a prediction of a third")

#%% md
**Reading FIG {{figures.s54_simulator}} (s54_simulator).** Left: replaying the showcase run from its recorded worker durations gave {{sim.replay_show|.0f}} s against {{sim.recorded_show|.0f}} s recorded ({{sim.err_show|+.0%}}), and the fixed plan's run 0 {{sim.err_c0|+.0%}}. Predicting run 1 of the fixed plan from run 0 alone gave {{sim.pred|.0f}} s against {{sim.pred_real|.0f}} s recorded ({{sim.pred_err|+.0%}}). Error that remains comes from what the simulator leaves out, mainly the rate gate of S10, which sometimes held calls back below the run's 32 slots. Right: the showcase plan simulated with 1 to 64 slots. The fitted parallel fraction is {{sim.p|.3f}}, so no number of slots could make it more than {{sim.cap|.0f}} times faster than one slot: the barriers between phases, and the slowest worker of each phase, set the limit. That is the same straggler tax S23 measured, seen from the planning side.

#%% md
**H7, decided on the simulator: does a pipeline beat a barrier?** The fixed plan's run 0, simulated twice with its own recorded latencies: as it ran, with a barrier between scanning and verifying, and as a pipeline in which each shard's findings are verified as soon as that shard's three lens scans are done.

#%% code
def fixed_plan_tasks(kit, pools, pipeline, seed=SEED):
    """Tasks for the fixed plan: a scan per shard and lens, skeptic batches of six places, then the report.

    Both versions make the same calls. With a barrier every batch waits for every scan; in the pipeline a batch waits
    only for the scans of the shards its six places came from."""
    rng_ = np.random.default_rng(seed)
    shard_of = {p: i for i, s in enumerate(shards()) for p in s}
    places = dedupe(kit.trace["found"])                     # sorted by place, so a batch draws on one or two shards
    tasks = {("scan", i, lens): (float(rng_.choice(pools["scan"])), []) for i in range(len(shards())) for lens in LENSES}
    tasks["barrier"] = (0.0, [t for t in tasks])
    checks = []
    for b, batch in enumerate(batches(places, 6)):
        needs = sorted({shard_of.get(f["file"], 0) for f in batch})
        deps = [("scan", i, l) for i in needs for l in LENSES] if pipeline else ["barrier"]
        for k in range(3):
            tasks[("check", b, k)] = (float(rng_.choice(pools["skeptic"])), deps)
            checks.append(("check", b, k))
    tasks["report"] = (float(rng_.choice(pools["report"])), checks or ["barrier"])
    return tasks

show_def(fixed_plan_tasks)
pools_h7 = {"scan": POOLS["scan"][0], "skeptic": POOLS["skeptic"][0], "report": POOLS["report"][0]}
H7_ROWS = []
for seed in range(20):
    bar = schedule(fixed_plan_tasks(C0_KIT, pools_h7, False, seed), 32)
    pipe = schedule(fixed_plan_tasks(C0_KIT, pools_h7, True, seed), 32)
    H7_ROWS.append({"seed": seed, "barrier": bar, "pipeline": pipe, "ratio": pipe / bar})
H7_RATIO = float(np.median([r["ratio"] for r in H7_ROWS]))
print(f"[H7] over 20 simulated draws: barrier {np.median([r['barrier'] for r in H7_ROWS]):.0f} s, pipeline "
      f"{np.median([r['pipeline'] for r in H7_ROWS]):.0f} s; median ratio {H7_RATIO:.2f} (the rule asks for at most 0.80)")

#%% code
save_exp("sim", {"replay": REPLAY, "replay_show": REPLAY[0]["simulated"], "recorded_show": REPLAY[0]["recorded"], "err_show": REPLAY[0]["error"],
                 "err_c0": REPLAY[1]["error"], "pred": PRED[0], "pred_lo": PRED[1], "pred_hi": PRED[2], "pred_real": PRED_REAL,
                 "pred_err": PRED_ERR, "p": P_PAR, "cap": 1 / (1 - P_PAR), "scale": SCALE, "source": SIM_SOURCE,
                 "h7_ratio": H7_RATIO, "h7_rows": H7_ROWS})
results = []
expect("the scheduler gets a hand-checked toy plan right", schedule(toy_plan, 4) == 5.0 and schedule(toy_plan, 2) == 5.0 and schedule(toy_plan, 1) == 10.0)
expect("more slots never make the simulated plan slower", all(a["seconds"] >= b["seconds"] - 1e-6 for a, b in zip(SCALE, SCALE[1:])))
expect("both versions of the fixed plan make the same calls", len(fixed_plan_tasks(C0_KIT, pools_h7, True)) == len(fixed_plan_tasks(C0_KIT, pools_h7, False)))
expect("on the median draw the pipeline is not slower than the barrier", H7_RATIO <= 1.0)
