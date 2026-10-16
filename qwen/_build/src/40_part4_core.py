#%% md
# Part IV. The runtime, one primitive at a time

The lead will write plans. Something has to run them. This Part builds that something.

**Where this sits.** Part III showed the three limits of a single context: it cannot read everything, it forgets what it read, and it does one thing at a time. The cure is a **runtime** that takes a plan and executes it in the background: many workers at once, each in a fresh context, in phases, with a record of everything. This Part builds the runtime from a handful of primitives (`agent`, `phase`, `log`, `parallel`, `pipeline`) plus a session `Budget`, wrapped in a `Run` object that can work in the background. Nothing in this Part decides *what* the plan is; Part V hands that decision to the lead. Here every plan is written by hand, so each primitive can be tested on its own.

**By the end of this Part you can**

- run one worker in its own thread with a readable log, and get back checked JSON or nothing;
- follow a run through its events, and add listeners that cannot break it;
- run a phase of workers in parallel, and say exactly what waiting for the slowest one costs;
- let items flow through stages without waiting for each other, and measure the time saved;
- cap a session's spend so the work pauses at the cap and resumes when it is raised, with nothing lost;
- resume a run that died halfway, paying only for what was not done yet.

![part4_map](attachment:part4_map.png)

#%% md
## S20 - A worker and its thread

**Theory.** A **worker** is one model call (or a short conversation, when a repair is needed) with a single job: read this shard, judge this finding, tag these messages. Each worker gets a fresh context holding only what its job needs, which is the cure for the memory problem of Part III. Each worker also gets a **thread**: the record of its whole conversation, every message sent and every reply, with timings, tokens and cost. After a run you can open any thread and read exactly what that worker saw and said. If a final answer looks wrong, the thread of the worker that produced it is where you go to find out why.

**In plain terms.** One worker, one job, one fresh memory, and a written record of the conversation that anyone can read afterwards.

**For teams.** Make the unit of work small and its record complete. "Which worker produced this claim, from which input?" should be a lookup, not an investigation.

#%% code
class RunCancelled(RuntimeError):
    """The run was cancelled; workers that have not started yet will not start."""


ABORT = (RunCancelled, OutOfMagicubes, CacheMiss, SpendRefused, AccessDenied)   # these end a run; every other failure is local


@dataclass
class Thread:
    id: str                 # run id plus a counter, such as "s22-demo/t001"
    run_id: str
    phase: str
    label: str              # what the plan called this worker, such as "scan:boundaries#3"
    model: str
    role: str = "worker"
    messages: list = field(default_factory=list)   # everything the worker was sent, in order
    replies: list = field(default_factory=list)    # every Reply it got back
    status: str = "waiting"                        # waiting, running, done or failed
    started: float = None                          # seconds since the run started
    ended: float = None
    error: str = None
    cost: float = 0.0                              # Magicubes charged for this worker's live calls
    result: object = None

show_def(RunCancelled, Thread)

#%% md
**Reading a thread.** **`render_thread(thread)`** prints a worker's conversation the way a chat is read: who said what, with long texts shortened so a shard of code does not fill the screen, and each reply's reasoning reduced to its length. **`thread_card(thread)`** draws the same thing as an HTML card, for notebooks that show HTML.

#%% code
def _short(text, n=320):
    text = str(text)
    return text if len(text) <= n else text[:n // 2] + f"\n[... {len(text) - n:,} characters not shown ...]\n" + text[-n // 2:]


def render_thread(t, width=320):
    """A worker's conversation as text."""
    took = (t.ended or 0) - (t.started or 0)
    lines = [f"thread {t.id}  {t.label}  [{t.status}]  model {t.model.split('/')[-1]}, phase {t.phase}, {took:.1f}s, {t.cost:.1f} MC"]
    for m in t.messages:
        lines.append(f"  {m['role']:<9}| " + _short(m["content"], width).replace("\n", "\n           | "))
    for r in t.replies:
        lines.append(f"  reply    | {len(r.reasoning):,} characters of reasoning, {r.prompt_tokens:,}+{r.completion_tokens:,} tokens, "
                     f"{r.seconds:.1f}s{' (from the ledger)' if r.cached else ''}")
        lines.append("           | " + _short(r.text, width).replace("\n", "\n           | "))
    if t.error:
        lines.append(f"  error    | {t.error}")
    return "\n".join(lines).replace("\u2014", " - ").replace("\u2013", "-")   # the notebook prints no dashes, even a model's


def thread_card(t):
    """A worker's conversation as a small HTML card."""
    colour = {"system": "#f0efec", "user": "#e3eefb", "assistant": "#e0f5ec"}
    took = (t.ended or 0) - (t.started or 0)
    parts = [f'<div style="font-family:sans-serif;font-size:12px;border:1px solid {GRID};border-radius:8px;padding:8px;max-width:760px">',
             f'<b>{html.escape(t.label)}</b> <span style="color:{INK2}">{html.escape(t.id)} | {t.status} | {took:.1f}s | {t.cost:.1f} MC</span>']
    for m in t.messages + [{"role": "assistant", "content": r.text} for r in t.replies]:
        parts.append(f'<div style="background:{colour.get(m["role"], "#fff")};border-radius:6px;padding:4px 6px;margin:4px 0;'
                     f'white-space:pre-wrap"><b>{m["role"]}</b> {html.escape(_short(m["content"], 400))}</div>')
    return "".join(parts) + "</div>"

show_def(_short, render_thread, thread_card)

#%% md
## S21 - Events: following a run without touching it

**Theory.** A run that works in the background needs a way to tell the world what it is doing. It does that with **events**: short records announcing that something happened, each with a type, a sequence number, a timestamp and a few fields. The types follow a `thing.what_happened` pattern, so a listener can subscribe to a family with a wildcard such as `run.phase_*`. Our vocabulary is small on purpose:

| event | when | key fields |
|---|---|---|
| `run.created` | the run starts | title, goal |
| `run.phase_started` | the plan opens a phase | phase, index |
| `run.agent_started` | a worker starts | thread, label, model |
| `run.agent_ended` | a worker finishes | thread, ok, seconds, cached, magicubes |
| `run.phase_ended` | the next phase opens, or the run ends | phase, agents, failed, seconds |
| `run.log` | the plan says something | message |
| `run.paused` / `run.resumed` | the budget stops or releases new work | spent, cap |
| `run.dropped` | a limit refused some work | what, count (dropped by this event) |
| `run.ended` | the run is over | status, seconds, agents, magicubes, dropped (in total) |

Listeners are called in the run's own threads, so a listener that crashes or hangs could take the run down with it. The bus catches every exception a listener raises and counts it in a health record, so a broken progress bar can never fail an audit.

**In plain terms.** The run writes a running commentary of what it is doing. Anyone can listen; nobody listening can interrupt it.

**For teams.** Put everything a dashboard, an alert or a billing job needs into events, and make the events the only coupling. Then nobody has to touch the runtime to add a dashboard.

![events](attachment:events.png)

#%% code
class EventBus:
    """Ordered events for one run, delivered to listeners that cannot break it."""

    def __init__(self, run_id, t0):
        self.run_id, self.t0 = run_id, t0
        self.events, self.listeners = [], []
        self.health = collections.Counter()
        self.lock = threading.Lock()

    def on(self, pattern, fn):
        """Call fn(event) for every event whose type matches the wildcard pattern."""
        self.listeners.append((pattern, fn))

    def emit(self, kind, **data):
        with self.lock:
            event = {"seq": len(self.events) + 1, "t": round(time.perf_counter() - self.t0, 3), "type": kind, "run_id": self.run_id, **data}
            self.events.append(event)
        for pattern, fn in list(self.listeners):
            if fnmatch.fnmatch(kind, pattern):
                try:
                    fn(event)
                    self.health["ok"] += 1
                except Exception as e:                       # a listener's failure stays the listener's
                    self.health["error"] += 1
                    self.health[f"last error: {type(e).__name__}"] += 1
        return event


def print_event(e):
    """A compact one-line view of an event, for runs started with printer=True."""
    keys = [k for k in e if k not in ("seq", "t", "type", "run_id")]
    print(f"  [{e['run_id']} {e['t']:7.2f}s] {e['type'][4:]:<14} " + ", ".join(f"{k}={e[k]}" for k in keys)[:110])

show_def(EventBus, print_event)

#%% md
**A bus, tested.** A few events go through a bus with three listeners: one that prints, one that collects only phase events through a wildcard, and one that crashes on every call. The run, here just a series of `emit` calls, does not notice the crash, and the health record does.

#%% code
bus = EventBus("bus-demo", time.perf_counter())
bus.on("run.*", print_event)
phase_seen = []
bus.on("run.phase_*", lambda e: phase_seen.append(e["type"]))
bus.on("run.*", lambda e: 1 / 0)                                   # a listener with a bug in it
bus.emit("run.created", title="a demo")
bus.emit("run.phase_started", phase="Scan", index=1)
bus.emit("run.agent_started", thread="bus-demo/t001", label="scan#0")
bus.emit("run.agent_ended", thread="bus-demo/t001", ok=True, seconds=1.2)
bus.emit("run.phase_ended", phase="Scan", agents=1, failed=0)
bus.emit("run.ended", status="completed")
print(f"[bus] {len(bus.events)} events; the phase listener saw {phase_seen}; health {dict(bus.health)}")
results = []
expect("a crashing listener does not stop the events", len(bus.events) == 6)
expect("the wildcard listener saw only phase events", phase_seen == ["run.phase_started", "run.phase_ended"])
expect("the crashes were counted, not hidden", bus.health["error"] == 6)

#%% md
## S22 - The run, and `agent()`

**Theory.** **`Run`** holds everything one execution of a plan produces: its id, its title and goal, its event bus, its threads, its phases, the slots that cap how many workers run at once, and its status. A plan is just a Python function that receives the run and calls its primitives. `agent()` is the primitive that runs one worker, and it follows three rules:

- **It returns a value or nothing.** With a schema, the reply is parsed and checked, and repaired once if needed (S12). If it still does not fit, the worker returns `None` and its thread records why. A plan never receives a malformed object, and never receives an exception for a worker that failed.
- **It is counted.** Every worker counts toward the run's limit (S29), waits for a free slot, and charges its cost to the run.
- **It is announced.** It emits an event when it starts and when it ends.

The only exceptions that do escape are the ones that must end the whole run: a cancellation, an empty balance, a replay that meets a request it never saw, or a refusal to spend.

**In plain terms.** The run is the container; `agent()` is how a plan puts one worker into it.

#%% code
class Run:
    """One execution of a plan: threads, events, phases, slots, status."""

    def __init__(self, title, goal="", *, run_id=None, llm=None, concurrency=16, max_agents=MAX_AGENTS_PER_RUN, printer=False):
        self.title, self.goal = title, goal
        self.run_id = run_id or "run-" + hashlib.sha256((title + "|" + goal).encode()).hexdigest()[:6]
        self.llm = llm or FRONT_DOOR
        self.t0 = time.perf_counter()
        self.bus = EventBus(self.run_id, self.t0)
        self.threads, self.phases, self.dropped = [], [], []
        self.slots = threading.BoundedSemaphore(concurrency)
        self.concurrency, self.max_agents, self.agents_started = concurrency, max_agents, 0
        self.lock = threading.Lock()
        self.cancelled = threading.Event()
        self.status, self.result, self.error, self.current = "created", None, None, None
        self._worker = None
        if printer:
            self.bus.on("run.*", print_event)

    def elapsed(self):
        return time.perf_counter() - self.t0

show_def(Run)

#%% md
**`Run.phase(title)`** closes the phase in progress, with its numbers, and opens the next one. **`Run.log(message)`** lets a plan say something into the event stream, which is how a plan reports what it decided and why. A plan that has been cancelled stops at its next `log` line, as it does at its next `agent` call.

#%% code
@method_of(Run)
def phase(self, title):
    now = self.elapsed()
    with self.lock:
        if self.current is not None:
            p = self.current
            p["ended"] = now
            self.bus.emit("run.phase_ended", phase=p["name"], agents=p["agents"], failed=p["failed"],
                          seconds=round(now - p["started"], 2))
        self.current = None if title is None else {"name": title, "index": len(self.phases) + 1, "started": now,
                                                   "ended": None, "agents": 0, "failed": 0}
        if self.current is not None:
            self.phases.append(self.current)
            self.bus.emit("run.phase_started", phase=title, index=self.current["index"])


@method_of(Run)
def log(self, message):
    if self.cancelled.is_set():                                 # a cancelled plan stops at its next log line too
        raise RunCancelled(self.run_id)
    self.bus.emit("run.log", message=scrub(str(message))[:500])

show_def(Run.phase, Run.log)

#%% md
**`Run.agent(...)`** is the primitive itself. It resolves the model from a role name, checks the cancel flag and the agent limit, creates the thread, waits for a slot, holds the conversation, and records the outcome. The conversation is in **`Run._converse`** below; this method is the bookkeeping around it.

#%% code
@method_of(Run)
def agent(self, prompt="", *, schema=None, model="worker", label="", phase=None, system="", data=None, sample=0,
          thinking=None, max_tokens=16000, hedge_after=None, role="worker"):
    model = MODELS.get(model, model)
    if thinking is None:   # the workers follow WORKER_THINKING; other models keep their default
        thinking = WORKER_THINKING if (model == MODELS["worker"] or role == "scan") else True   # scans think only when WORKER_THINKING is on, whichever model runs them
    if self.cancelled.is_set():
        raise RunCancelled(self.run_id)
    with self.lock:
        self.agents_started += 1
        n = self.agents_started
        if n > self.max_agents:
            self.dropped.append(label)
            over = True
        else:
            over = False
            ph = phase or (self.current["name"] if self.current else "")
            t = Thread(f"{self.run_id}/t{n:03d}", self.run_id, ph, label or f"agent {n}", model, role)
            self.threads.append(t)
    if over:
        self.bus.emit("run.dropped", what="agent", label=label, count=1, limit=self.max_agents)
        if len(self.dropped) >= self.max_agents:              # asking for twice the limit is a runaway, not a plan
            self.log(f"the plan asked for {self.max_agents + len(self.dropped)} workers, twice its limit: cancelled as a runaway")
            self.cancelled.set()
        return None
    self.bus.emit("run.agent_started", thread=t.id, label=t.label, model=model.split("/")[-1], phase=t.phase)
    with self.slots:
        t.started, t.status = self.elapsed(), "running"
        try:
            t.result = self._converse(t, system, (prompt + ("\n\n" + data if data else "")).strip(), schema,
                                      sample, thinking, max_tokens, hedge_after)
            t.status = "done" if t.result is not None else "failed"
        except ABORT:
            t.status, t.error = "failed", "aborted"
            raise
        except Exception as e:                                    # a worker's failure stays the worker's
            t.status, t.error, t.result = "failed", scrub(f"{type(e).__name__}: {e}")[:300], None
        finally:
            t.ended = self.elapsed()
    with self.lock:
        for p in self.phases:
            if p["name"] == t.phase:
                p["agents"] += 1
                p["failed"] += t.status == "failed"
    self.bus.emit("run.agent_ended", thread=t.id, label=t.label, ok=t.status == "done", seconds=round(t.ended - t.started, 2),
                  cached=all(r.cached for r in t.replies) if t.replies else False, magicubes=round(t.cost, 2), phase=t.phase)
    return t.result

show_def(Run.agent)

#%% md
**`Run._converse`** holds one worker's conversation. It asks with JSON mode where the model supports it, checks the answer against the schema, and gives one repair turn, exactly as `ask_json` did in S12. The difference is that every message and every reply is written into the worker's thread, and every live call is charged to it. **`Run._call`** makes one call, and is where hedging (S25) plugs in.

#%% code
@method_of(Run)
def _call(self, t, messages, params, sample, hedge_after):
    tag = f"{self.run_id}:{t.label}"
    ask = lambda s: self.llm.chat(t.model, messages, tag=tag, role=t.role, phase=t.phase, run_id=self.run_id, sample=s, **params)
    r = ask(sample) if hedge_after is None else hedged(ask, sample, hedge_after)
    t.replies.append(r)
    if not r.cached and r.finish != "error":
        t.cost += PRICE.get(t.model, 0.2) * getattr(r, "copies", 1)
    return r


@method_of(Run)
def _converse(self, t, system, user, schema, sample, thinking, max_tokens, hedge_after):
    params = {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": max_tokens}
    if schema is not None and "JSON mode" in CAN.get(t.model, ()):
        params["response_format"] = {"type": "json_object"}
    if not thinking and "thinking off" in CAN.get(t.model, ()):
        params["enable_thinking"] = False
    t.messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    r = self._call(t, t.messages, params, sample, hedge_after)
    if r.finish == "error":
        t.error = r.error
        return None
    if schema is None:
        return r.text
    obj = extract_json(r.text)
    errors = validate(obj, schema)
    if not errors:
        return obj
    t.messages = t.messages + [{"role": "assistant", "content": r.text[:6000]}, {"role": "user", "content": repair_message(errors, schema)}]
    r2 = self._call(t, t.messages, params, sample, None)
    obj2 = extract_json(r2.text) if r2.finish != "error" else None
    errors2 = validate(obj2, schema)
    if errors2:
        t.error = "schema: " + "; ".join(errors2)[:240]
        return None
    return obj2


def hedged(ask, sample, after):
    """Placeholder until S25 defines hedging: a plain call."""
    return ask(sample)

show_def(Run._call, Run._converse, hedged)

#%% md
**`Run.run_sync(plan)`** runs a plan in the calling thread, from `run.created` to `run.ended`, and saves the run's record. S27 adds `start()`, which does the same in the background. **`Run._finish`** is the part they share: close the last phase, count the cost, and announce the end. Two lists of **hooks** let later sections attach behaviour to every run's start and end without editing this code; S26 uses them to connect the budget.

#%% code
RUN_START_HOOKS, RUN_END_HOOKS = [], []   # functions of a run, called when it starts and when it ends; S26 adds the budget's


@method_of(Run)
def _execute(self, plan):
    self.status = "running"
    self.bus.emit("run.created", title=self.title, goal=self.goal)
    for hook in RUN_START_HOOKS:
        hook(self)
    try:
        self.result = plan(self)
        self.status = "completed"
    except RunCancelled:
        self.status = "cancelled"
    except ABORT as e:
        self.status, self.error = "failed", scrub(f"{type(e).__name__}: {e}")[:300]
    except Exception as e:
        self.status, self.error = "failed", scrub(f"{type(e).__name__}: {e}")[:300]
    finally:
        self._finish()
    return self.result


@method_of(Run)
def _finish(self):
    for hook in RUN_END_HOOKS:
        hook(self)
    self.phase(None)
    self.bus.emit("run.ended", status=self.status, seconds=round(self.elapsed(), 2), agents=len(self.threads),
                  failed=sum(t.status == "failed" for t in self.threads), magicubes=round(sum(t.cost for t in self.threads), 2),
                  dropped=len(self.dropped), error=self.error)
    self.persist()


@method_of(Run)
def run_sync(self, plan):
    return self._execute(plan)

show_def(Run._execute, Run._finish, Run.run_sync)
print(f"[hooks] {len(RUN_START_HOOKS)} start hooks, {len(RUN_END_HOOKS)} end hooks so far")

#%% md
**Keeping the record.** **`Run.persist()`** writes the run's events and a summary of every thread to `artifacts/runs/<run id>/`. A run made in collect mode writes `events.jsonl`. The same run replayed later writes `events.replay.jsonl` instead and leaves the original alone. That matters for every timing figure: a replayed call returns instantly, so the true timeline of a run is the one recorded when it was paid for. **`timeline(run)`** returns that true timeline whenever it exists.

#%% code
@method_of(Run)
def persist(self):
    d = RUNS_DIR / self.run_id
    d.mkdir(parents=True, exist_ok=True)
    name = "events.jsonl" if DW_MODE != "replay" or not (d / "events.jsonl").exists() else "events.replay.jsonl"
    with open(d / name, "w", encoding="utf-8") as f:
        for e in self.bus.events:
            f.write(json.dumps(e, default=str) + "\n")
    summary = [{"id": t.id, "label": t.label, "phase": t.phase, "model": t.model, "status": t.status, "started": t.started,
                "ended": t.ended, "cost": t.cost, "error": t.error, "replies": len(t.replies),
                "reply": scrub(t.replies[-1].text[:2000]) if t.replies else ""} for t in self.threads]
    (d / ("threads.json" if name == "events.jsonl" else "threads.replay.json")).write_text(json.dumps(summary, indent=1), encoding="utf-8")


def timeline(run_or_id):
    """[(label, phase, start, end, ok)] of a run, from its collect-time record when one exists."""
    run_id = run_or_id if isinstance(run_or_id, str) else run_or_id.run_id
    path = RUNS_DIR / run_id / "events.jsonl"
    if path.exists():
        events = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines()]
    else:
        events = run_or_id.bus.events
    starts = {e["thread"]: e for e in events if e["type"] == "run.agent_started"}
    out = []
    for e in events:
        if e["type"] == "run.agent_ended" and e["thread"] in starts:
            out.append((e["label"], e.get("phase", ""), e["t"] - e["seconds"], e["t"], e["ok"]))
    return sorted(out, key=lambda r: r[2])

show_def(Run.persist, timeline)

#%% md
**One real worker.** The first run of the runtime is as small as a run can be: one phase, one worker, one shard of real code, the scan instruction from S13. Events are printed as they happen. Afterwards we open the worker's thread and read the whole conversation.

#%% code
def scan_task(paths, lens="general"):
    """The system prompt and data for a scan worker on one shard."""
    return {"system": SCAN_SYSTEM + ("\n\n" + LENS_TEXT[lens] if LENS_TEXT.get(lens) else ""), "data": render_shard(paths)}


def findings_of(obj, source=""):
    """Finding objects from a scan worker's JSON answer (an empty list for None)."""
    return [Finding(file=str(f.get("file", "")), line=int(f.get("line", 0) or 0), function=str(f.get("function", "")),
                    claim=str(f.get("claim", "")), failing_call=str(f.get("failing_call", "")), expected=str(f.get("expected", "")),
                    source=source) for f in (obj or {}).get("findings", []) if isinstance(f, dict)]

show_def(scan_task, findings_of)
SHARDS = pack(sorted(CORPUS), SHARD_TOKENS)
first_shard = next(s for s in SHARDS if any(b["path"] in s for b in ANSWER_KEY))
demo_run = Run("one worker on one shard", run_id="s22-one-worker", printer=True)


def one_worker(run):
    run.phase("Scan")
    return run.agent(**scan_task(first_shard), schema=FINDINGS_SCHEMA, label="scan#0")

show_def(one_worker, layer="plan")
obj = demo_run.run_sync(one_worker)
found = findings_of(obj)
print(f"\n[s22] status {demo_run.status}; {len(found)} findings; matched to planted bugs in this shard: "
      f"{match(found, key=[b for b in ANSWER_KEY if b['path'] in first_shard]).tp} of {sum(b['path'] in first_shard for b in ANSWER_KEY)}")
print(render_thread(demo_run.threads[0]))
display(HTML(thread_card(demo_run.threads[0])))

#%% code
results = []
expect("the run completed and recorded one thread", demo_run.status == "completed" and len(demo_run.threads) == 1)
expect("the thread holds the system prompt, the shard and the reply", len(demo_run.threads[0].messages) >= 2 and demo_run.threads[0].replies)
expect("the events came in order: created, phase, agent, agent, phase, ended",
       [e["type"] for e in demo_run.bus.events] == ["run.created", "run.phase_started", "run.agent_started", "run.agent_ended",
                                                     "run.phase_ended", "run.ended"])
expect("the run's record was written", (RUNS_DIR / "s22-one-worker" / "events.jsonl").exists())
