#%% md
## S10 - Rate control: as fast as the server allows, and no faster

**Theory.** A team of forty workers is only useful if the model service lets forty calls run at once, and nobody tells us the real limit. The provider's limits depend on the account and on how quickly usage ramps up, and a call over them gets a 429 with a `rate_limit_error`. A **fixed** concurrency is therefore wrong in one of two ways. Set it too high and most calls bounce off the limit, retry and bounce again. Set it too low and the server sits idle while workers wait.

Networks solved this problem decades ago. TCP, the protocol under every web page, does not know how much bandwidth a connection has either. It finds out with **slow start** and **AIMD**, short for additive increase, multiplicative decrease. Start small and double the window after every round that goes well. At the first sign of trouble, halve it. From then on grow by one per good round, and halve again on trouble. The window ends up oscillating just under the real limit, and many senders sharing one link settle on a fair split without talking to each other. **`AIMDGate`** applies the same rule to calls in flight per model: a "round" is a window of completed calls, "trouble" is a 429 that asks us to slow down.

**In plain terms.** Start gently, speed up while everything goes well, and back off by half the moment the server complains.

**For teams.** Any client that fans out to a shared service needs this, or something like it. The alternative is a constant you will get wrong for somebody, on some day, at some load.

![aimd](attachment:aimd.png)

#%% code
class AIMDGate:
    """Calls in flight for one model, learned from the server: slow start, then additive increase, multiplicative decrease."""

    def __init__(self, start=START_IN_FLIGHT, ceiling=MAX_IN_FLIGHT):
        self.limit, self.ceiling = float(start), ceiling
        self.in_flight, self.done_in_window, self.slow_start = 0, 0, True
        self.cond = threading.Condition()
        self.timeline = [(time.perf_counter(), start, "start")]

    @contextlib.contextmanager
    def slot(self):
        with self.cond:
            while self.in_flight >= int(self.limit):
                self.cond.wait()
            self.in_flight += 1
        try:
            yield self
        finally:
            with self.cond:
                self.in_flight -= 1
                self.cond.notify_all()

show_def(AIMDGate)

#%% md
**`AIMDGate.ok`** and **`AIMDGate.throttled`** are the two signals. After a full window of good calls (as many as the current limit), the limit doubles during slow start and grows by one afterwards, never past the ceiling. A throttle halves the limit at once, ends slow start, and starts a new window.

#%% code
@method_of(AIMDGate)
def ok(self):
    with self.cond:
        self.done_in_window += 1
        if self.done_in_window >= int(self.limit):
            self.limit = min(self.ceiling, self.limit * 2 if self.slow_start else self.limit + 1)
            self.done_in_window = 0
            self.timeline.append((time.perf_counter(), self.limit, "grow"))
        self.cond.notify_all()


@method_of(AIMDGate)
def throttled(self):
    with self.cond:
        self.limit = max(1.0, self.limit / 2)
        self.slow_start, self.done_in_window = False, 0
        self.timeline.append((time.perf_counter(), self.limit, "throttled"))

show_def(AIMDGate.ok, AIMDGate.throttled)
g = AIMDGate(start=2, ceiling=16)
trace = []
for signal in ["ok"] * 2 + ["ok"] * 4 + ["ok"] * 8 + ["throttled"] + ["ok"] * 8 + ["ok"] * 9:
    getattr(g, signal)()
    trace.append(int(g.limit))
print(f"[aimd] limit after each signal: {trace}")

#%% md
**The measurement.** We send the same 120 requests to the local server three ways and record every 429. The server allows 6 calls in flight. The first client uses a fixed concurrency of 16, roughly what a script written without this section would use. The second uses a fixed concurrency of 2, a cautious guess. The third uses the AIMD gate, starting at 2 with a ceiling of 16. Retries wait as they would in a real run, scaled down by the same factor for all three, so the comparison is fair.

#%% code
def hammer(gate_factory, n=120, workers=20, label=""):
    """Send n requests through a client with the given gate; return what happened."""
    server = FakeModelServer(capacity=6, latency=0.02, chunks=6)
    client = ModelClient("sk-ant-test-key-not-real-000000", endpoint=server.endpoint, gate_factory=gate_factory)
    client.backoff_scale = 0.05
    start = time.perf_counter()
    with cf.ThreadPoolExecutor(workers) as pool:
        replies = list(pool.map(lambda i: client.chat("fake", [{"role": "user", "content": f"{label} request {i}"}]), range(n)))
    took = time.perf_counter() - start
    gate = client.gates["fake"]
    server.httpd.shutdown()
    return {"label": label, "seconds": took, "ok": sum(r.finish == "stop" for r in replies),
            "failed": sum(r.finish == "error" for r in replies), "429s": server.rejected["429 busy"],
            "requests": server.calls, "peak": server.peak, "timeline": gate.timeline, "t0": start,
            "attempts": sum(r.attempts for r in replies)}

show_def(hammer)
RATE = [hammer(lambda m: FixedGate(16), label="fixed at 16"),
        hammer(lambda m: FixedGate(2), label="fixed at 2"),
        hammer(lambda m: AIMDGate(start=2, ceiling=16), label="AIMD from 2")]
table(RATE, [("label", "gate", ""), ("ok", "answered", "d"), ("failed", "gave up", "d"), ("429s", "429s received", "d"),
             ("requests", "requests sent", "d"), ("peak", "peak in flight", "d"), ("seconds", "seconds", ".2f")])

#%% md
### Figure: what each gate does over time

#%% code
# FIG  the AIMD sawtooth against the two fixed gates
fig, axes = plt.subplots(1, 3, figsize=(11.2, 3.6), gridspec_kw={"width_ratios": [1.5, 1, 0.9]})
ax = axes[0]
aimd = RATE[2]
ts = [t - aimd["t0"] for t, _, _ in aimd["timeline"]]
ls = [l for _, l, _ in aimd["timeline"]]
ax.step(ts, ls, where="post", color=C1, lw=2, label="AIMD limit")
for (t, l, ev) in aimd["timeline"]:
    if ev == "throttled":
        ax.plot(t - aimd["t0"], l, "v", color=C8, ms=6)
ax.axhline(6, color=INK2, ls="--", lw=1)
ax.text(0, 6.3, " server capacity 6", fontsize=8, color=INK2)
ax.set_xlabel("seconds since the first request")
ax.set_ylabel("calls allowed in flight")
ax.set_ylim(0, 17)
panel(ax, "AIMD limit; red triangles: a 429 halved it")
ax = axes[1]
x = np.arange(len(RATE))
ok_ = [r["ok"] for r in RATE]
lost = [r["failed"] for r in RATE]
ax.bar(x, ok_, 0.6, color=C3, label="answered")
ax.bar(x, lost, 0.6, bottom=ok_, color=C8, label="gave up")
for i, r in enumerate(RATE):
    ax.text(i, 122, f"{r['429s']} x 429", ha="center", va="bottom", fontsize=7.5, color=INK2)
ax.set_xticks(x, [r["label"] for r in RATE], fontsize=8)
ax.set_ylim(0, 140)
ax.legend(fontsize=7.5, loc="lower right")
panel(ax, "the same 120 requests")
ax = axes[2]
ax.bar(x, [r["seconds"] for r in RATE], 0.6, color=[MUTED, MUTED, C1])
for i, r in enumerate(RATE):
    ax.text(i, r["seconds"], f"{r['seconds']:.1f}s", ha="center", va="bottom", fontsize=8)
ax.set_xticks(x, [r["label"].replace(" from ", "\nfrom ").replace(" at ", "\nat ") for r in RATE], fontsize=8)
ax.set_ylabel("seconds")
panel(ax, "time to finish")
finish(fig, "s10_aimd", f"AIMD answered {RATE[2]['ok']} of 120; the greedy fixed gate gave up on {RATE[0]['failed']}",
       "local server with capacity 6; repeated 429s tripped the greedy client's circuit breaker, the cautious one left capacity idle")

#%% md
**Reading FIG {{figures.s10_aimd}} (s10_aimd).** The left panel is the AIMD gate's limit over time. It doubles quickly while every call succeeds, overshoots the server's capacity once, gets a 429 and halves, then creeps up by one per good window and halves again whenever it touches the limit. That sawtooth is the gate probing the capacity all the time, so it would follow the server if the capacity changed. The middle panel is the cost of not doing this, and it is worse than a few retries. The gate fixed at 16 drew {{rate_control.fixed16_429s}} rejections. Every request that used up its four attempts counted as a failure, and after five such failures in a row the client's circuit breaker did its job and stopped calling the model, so {{rate_control.fixed16_failed}} of 120 requests were simply lost. The gate fixed at 2 lost nothing, but took {{rate_control.fixed2_seconds|.1f}} s instead of {{rate_control.aimd_seconds|.1f}} s, because it left most of the capacity unused. AIMD answered {{rate_control.aimd_answered}} of 120, drew {{rate_control.aimd_429s}} rejections and took {{rate_control.aimd_seconds|.1f}} s, against {{rate_control.fixed16_seconds|.1f}} s for the greedy gate that lost most of its requests, without anyone telling it the number 6.

#%% code
save_exp("rate_control", {"fixed16_429s": RATE[0]["429s"], "fixed16_seconds": RATE[0]["seconds"], "fixed16_requests": RATE[0]["requests"],
                          "fixed16_failed": RATE[0]["failed"], "fixed16_answered": RATE[0]["ok"],
                          "fixed2_429s": RATE[1]["429s"], "fixed2_seconds": RATE[1]["seconds"],
                          "aimd_429s": RATE[2]["429s"], "aimd_seconds": RATE[2]["seconds"], "aimd_requests": RATE[2]["requests"], "aimd_answered": RATE[2]["ok"],
                          "capacity": 6, "requests": 120})
results = []
expect("the cautious gate and the AIMD gate answered every request", RATE[1]["ok"] == 120 and RATE[2]["ok"] == 120)
expect("the greedy gate lost requests once its circuit breaker opened", RATE[0]["failed"] > 0)
expect("the AIMD gate drew fewer 429s than the greedy fixed gate", RATE[2]["429s"] < RATE[0]["429s"])
expect("the AIMD gate finished faster than the cautious fixed gate", RATE[2]["seconds"] < RATE[1]["seconds"])
expect("the AIMD limit never went below 1 or above its ceiling", all(1 <= l <= 16 for _, l, _ in RATE[2]["timeline"]))

#%% md
**From here on the notebook's client uses AIMD gates.** The live client (in collect mode) gets one `AIMDGate` per model, starting at `START_IN_FLIGHT` and capped at `MAX_IN_FLIGHT`.

#%% code
if CLIENT is not None:
    CLIENT.gate_factory = lambda m: AIMDGate(START_IN_FLIGHT, MAX_IN_FLIGHT)
    CLIENT.gates.clear()
print(f"[gate] live client: {'AIMD gates, start ' + str(START_IN_FLIGHT) + ', ceiling ' + str(MAX_IN_FLIGHT) if CLIENT else 'none in ' + DW_MODE + ' mode'}")
