#%% md
## S26 - The budget: one meter for the session, runs included

**Theory.** A dozen workers spend money a dozen times as fast as one, and a plan the lead writes can easily ask for more workers than anyone expected. So spending is capped by a **budget**, and the budget follows three rules:

1. **One meter for the whole session.** The lead's own calls and every call of every run it starts are charged to the same budget. A plan cannot escape the cap by starting another run.
2. **At the cap, work pauses; it is not killed.** A call that would push spending past the cap does not start. It waits. Calls already in flight finish normally, and nothing already done is thrown away.
3. **Raise the cap, and the work resumes** from exactly where it stopped. No call is repeated, because nothing was cancelled.

Admission works by **reservation**. Before a call starts, its price is reserved: the budget checks that the money already spent, plus the money reserved by calls in flight, plus this call's price, stays under the cap. When the call returns, the reservation becomes spending. With per-call billing the price is known exactly in advance, so a reserved budget can never be overshot. Under per-token billing it could be, because nobody knows before a call how long the answer will be; the measurement at the end of this section shows by how much.

**In plain terms.** Every call asks the budget for permission first. When the money is used up, new calls wait in line until somebody raises the limit, and then they carry on.

**For teams.** Put the cap where the spending happens, in the one function every call goes through, not in a script that checks a dashboard every few minutes. A check that runs after the money is spent is a report, not a cap.

![budget](attachment:budget.png)

#%% code
class Budget:
    """A spending cap shared by the lead and every run: reserve before a call, settle after, pause at the cap."""

    def __init__(self, cap, spent=0.0, unit="Magicubes"):
        self.cap, self.spent, self.reserved, self.unit = float(cap), float(spent), 0.0, unit
        self.refuse_at_cap = False                  # True when no person can raise the cap: refuse instead of pausing
        self.cond = threading.Condition()
        self.paused, self.waiting, self.pauses = False, 0, 0
        self.listeners = []
        self.t0 = time.perf_counter()
        self.history = [(0.0, self.spent, 0.0, self.cap, 0, "start")]

    def _record(self, what):
        self.history.append((time.perf_counter() - self.t0, self.spent, self.reserved, self.cap, self.waiting, what))

    def _tell(self, what):
        for fn in list(self.listeners):
            try:
                fn(what, {"spent": round(self.spent, 2), "cap": self.cap, "waiting": self.waiting})
            except Exception:
                pass

show_def(Budget)

#%% md
**`Budget.admit(cost)`** reserves a call's price or waits until it can. **`Budget.settle(reserved, actual)`** turns the reservation into spending, or releases it if the call failed and was not billed. **`Budget.raise_to(cap)`** moves the cap and wakes every waiting call. The `paused` and `resumed` announcements are made once per pause, not once per waiting call.

#%% code
@method_of(Budget)
def admit(self, cost, who=""):
    with self.cond:
        while self.spent + self.reserved + cost > self.cap + 1e-9:
            if self.refuse_at_cap:                       # nobody is watching who could raise the cap
                raise SpendRefused(f"the cap of {self.cap:.0f} {self.unit} is reached and nobody is here to raise it")
            if not self.paused:
                self.paused = True
                self.pauses += 1
                self._record("paused")
                self._tell("paused")
            self.waiting += 1
            self.cond.wait(timeout=1.0)
            self.waiting -= 1
        self.reserved += cost
        self._record("admit")


@method_of(Budget)
def settle(self, reserved, actual):
    with self.cond:
        self.reserved -= reserved
        self.spent += actual
        self._record("settle")
        self.cond.notify_all()


@method_of(Budget)
def raise_to(self, cap):
    with self.cond:
        self.cap = float(cap)
        self._record("raised")
        if self.paused:
            self.paused = False
            self._tell("resumed")
        self.cond.notify_all()


@method_of(Budget)
def on(self, fn):
    self.listeners.append(fn)


@method_of(Budget)
def off(self, fn):
    if fn in self.listeners:
        self.listeners.remove(fn)

show_def(Budget.admit, Budget.settle, Budget.raise_to, Budget.on, Budget.off)

#%% md
**Connecting runs to the budget.** A start hook subscribes each run to the budget of its front door, so a pause or a resume appears in the run's own event stream, and an end hook unsubscribes it again. This is the "runs included" rule in code: the run does not have a budget of its own, it listens to the session's.

#%% code
def _budget_start(run):
    if run.llm.budget is not None:
        run._budget_listener = lambda what, info: run.bus.emit(f"run.{what}", **info)
        run.llm.budget.on(run._budget_listener)


def _budget_end(run):
    if run.llm.budget is not None and hasattr(run, "_budget_listener"):
        run.llm.budget.off(run._budget_listener)


RUN_START_HOOKS.append(_budget_start)
RUN_END_HOOKS.append(_budget_end)
show_def(_budget_start, _budget_end)

#%% md
**Pause and resume, measured.** A plan of 40 workers costs 8 Magicubes at the worker price. It runs on the demo server against a budget with a cap of 5. A timer standing in for a person raises the cap to 10 a moment after the pause begins. We then check three things. The meter never went past the cap. Every worker finished. And the server received exactly 40 requests, so the pause cost no repeated call. The same plan is also run without a cap, as a reference, and the two results are compared.

#%% code
def forty(run):
    run.phase("Work")
    return run.parallel([lambda i=i: run.agent(f"budget item {i}", schema=DEMO_SCHEMA, model="fake-worker", label=f"w#{i}")
                         for i in range(40)])

show_def(forty, layer="plan")
llm_cap = demo_llm()
llm_cap.budget = Budget(cap=5.0)
capped = Run("forty workers under a cap of 5", run_id="s26-budget", llm=llm_cap, concurrency=12)
llm_cap.budget.on(lambda what, info: what == "paused" and threading.Timer(0.6, lambda: llm_cap.budget.raise_to(10.0)).start())
own = lambda: sum(n for text, n in DEMO_SERVER.seen.items() if text.startswith("budget item"))   # this demo's requests only
server_before = own()                    # duplicates left over from the hedging demo may still be arriving
capped.run_sync(forty)
server_calls = own() - server_before
reference = Run("forty workers, no cap", run_id="s26-reference", llm=demo_llm(), concurrency=12)
reference.run_sync(forty)
B = llm_cap.budget
over = max(s - c for _, s, _, c, _, _ in B.history)   # how far spending ever went past the cap in force
print(f"[budget] status {capped.status}; {sum(t.status == 'done' for t in capped.threads)} of 40 workers done; "
      f"spent {B.spent:.1f} of a final cap of {B.cap:.1f}; {B.pauses} pause(s)")
print(f"[budget] events: " + ", ".join(e["type"][4:] for e in capped.bus.events if e["type"] in ("run.paused", "run.resumed")))
print(f"[budget] the server received {server_calls} requests for 40 workers; results identical to the uncapped run: "
      f"{[t.result for t in capped.threads] == [t.result for t in reference.threads]}")
first_pause, spent_p, reserved_p, cap_p, _, _ = next(h for h in B.history if h[5] == "paused")
print(f"[budget] at the first pause {spent_p:.1f} was spent and {reserved_p:.1f} reserved by calls in flight, "
      f"{spent_p + reserved_p:.1f} of the cap of {cap_p:.1f}, so one more call at {PRICE['fake-worker']} would have passed it")
print(f"[budget] most calls waiting in line at once: {max(w for *_, w, _ in B.history)}")

#%% code
# FIG  the spending meter: it climbs to the cap, stops, and climbs again when the cap is raised
fig, axes = plt.subplots(2, 1, figsize=(10.4, 4.6), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
ts = [h[0] for h in B.history]
ax = axes[0]
ax.step(ts, [h[1] for h in B.history], where="post", color=C1, lw=2, label="spent")
ax.step(ts, [h[1] + h[2] for h in B.history], where="post", color=C1, lw=1, ls=":", label="spent + reserved")
ax.step(ts, [h[3] for h in B.history], where="post", color=C8, lw=1.5, ls="--", label="cap")
resumed_t = next((t for t, *_, what in B.history if what == "raised"), None)
if resumed_t is not None:
    ax.axvspan(first_pause, resumed_t, color=C4, alpha=0.15)
    ax.text((first_pause + resumed_t) / 2, 0.4, "paused", ha="center", fontsize=8, color=INK2)
ax.set_ylabel("Magicubes")
ax.legend(fontsize=8, loc="upper left")
panel(ax, "the meter, with the cap and the pause")
ax = axes[1]
ax.step(ts, [h[4] for h in B.history], where="post", color=C4, lw=1.6)
ax.set_ylabel("calls waiting")
ax.set_xlabel("seconds since the run started (demo time)")
finish(fig, "s26_budget", f"Spending stopped at the cap, waited, and resumed when the cap was raised; {server_calls} requests for 40 workers",
       "40 workers at 0.2 Magicubes each against a cap of 5, raised to 10 during the pause; nothing was cancelled or repeated")

#%% md
**Reading FIG {{figures.s26_budget}} (s26_budget).** The top panel is the meter. Spending (solid) climbs as workers finish, and the dotted line adds what is reserved for calls in flight, which is what admission checks against the cap (red). When the dotted line reached the cap, new calls stopped being admitted and the meter flattened: the amber band is the pause. The bottom panel shows the calls that were waiting in line during it, {{budget.max_waiting}} at most. When the cap was raised, the waiting calls were admitted and the meter climbed again to its final {{budget.spent|.1f}} Magicubes. The server received exactly {{budget.server_calls}} requests for 40 workers, so the pause repeated nothing, and the results matched the uncapped reference run.

#%% md
**Why reservation matters, and why per-call billing makes it exact.** If admission only checked money already *spent*, every call that started while the meter was just under the cap would push it over, and with twelve calls in flight that is twelve calls' worth of overshoot. Reservation counts the calls in flight too. With a known price per call it can never overshoot. With per-token billing it must reserve a guess, here the call's prompt plus its maximum output, and any guess that is too small lets the meter overshoot. The table below replays the token counts of the real scan calls in S13 against a token cap under both rules, at increasing concurrency.

#%% code
TOKEN_TRACE = [(p, c) for p, c in LEDGER.query("SELECT prompt_tokens, completion_tokens FROM calls WHERE role = 'scan' AND prompt_tokens > 0")]
if len(TOKEN_TRACE) < 10:
    rng_ = np.random.default_rng(SEED)
    TOKEN_TRACE = [(int(x), int(y)) for x, y in zip(rng_.integers(15_000, 40_000, 80), rng_.integers(1_000, 12_000, 80))]


def overshoot(concurrency, reserve, cap=600_000, max_out=16_000):
    """Simulate a token budget: how far past the cap does spending go?"""
    spent, reserved, in_flight, i, worst = 0, 0, [], 0, 0
    calls = (TOKEN_TRACE * 20)[:400]
    while i < len(calls) or in_flight:
        while i < len(calls) and len(in_flight) < concurrency:
            p, c = calls[i]
            guess = p + max_out if reserve else 0
            if spent + reserved + guess > cap or (not reserve and spent >= cap):
                break
            reserved += guess
            in_flight.append((p + c, guess))
            i += 1
        if not in_flight:
            break
        cost, guess = in_flight.pop(0)
        reserved -= guess
        spent += cost
        worst = max(worst, spent - cap)
    return max(0, worst)

show_def(overshoot)
OVER = [{"concurrency": k, "check spent only": overshoot(k, False), "reserve the maximum": overshoot(k, True)} for k in (1, 4, 8, 12, 16)]
table(OVER, [("concurrency", "calls in flight", "d"), ("check spent only", "overshoot, spent-only rule (tokens)", ","),
             ("reserve the maximum", "overshoot, reservation (tokens)", ",")])
print("[budget] with a price per call known in advance, reservation is exact, so the overshoot in Magicubes is zero at any concurrency")
print(f"[budget] largest completion seen: {max(c for _, c in TOKEN_TRACE):,} tokens against a reserved maximum of 16,000 "
      f"(a reserved maximum only protects the cap if the provider really stops there)")

#%% code
save_exp("budget", {"spent": B.spent, "cap_final": B.cap, "pauses": B.pauses, "server_calls": server_calls,
                    "max_waiting": max(w for *_, w, _ in B.history), "overshoot": max(0.0, over),
                    "identical": [t.result for t in capped.threads] == [t.result for t in reference.threads],
                    "token_overshoot": OVER})
results = []
expect("spending never passed the cap in force at the time", all(s <= c + 1e-9 for _, s, _, c, _, _ in B.history))
expect("every worker finished after the cap was raised", capped.status == "completed" and all(t.status == "done" for t in capped.threads))
expect("the pause repeated no call: one request per worker", server_calls == 40)
expect("the run's own event stream shows the pause and the resume",
       [e["type"] for e in capped.bus.events if e["type"] in ("run.paused", "run.resumed")][:2] == ["run.paused", "run.resumed"])
expect("reservation overshoots a token cap less than checking spending alone",
       all(r["reserve the maximum"] <= r["check spent only"] for r in OVER))

#%% md
**The session budget.** From here on, every call the notebook makes in collect mode passes through one budget: the session cap from the parameters cell, less what the ledger has already charged. Replay and smoke runs make no paid calls, so for them the budget is a formality.

#%% code
SESSION_BUDGET = Budget(cap=CAP_MAGICUBES, spent=LEDGER.spent())
SESSION_BUDGET.refuse_at_cap = os.environ.get("DW_HEADLESS") == "1"   # a script run stops at the cap instead of waiting for a person
FRONT_DOOR.budget = SESSION_BUDGET
print(f"[budget] session: {SESSION_BUDGET.spent:.1f} of {SESSION_BUDGET.cap:,.0f} Magicubes already spent; "
      f"{SESSION_BUDGET.cap - SESSION_BUDGET.spent:.1f} left for everything that follows")
