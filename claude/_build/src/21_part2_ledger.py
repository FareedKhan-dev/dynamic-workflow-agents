#%% md
## S8 - The ledger: cache, replay source and accounts in one table

**Theory.** Every model call goes through one front door, and every answer it gets is written to one SQLite table, the **ledger**, under a **fingerprint** of the request. The fingerprint is a SHA-256 hash of the model's name, the messages, the parameters and a **sample index**. Ask the same question again and the fingerprint is the same, so the ledger answers instead of the network: the second call is free and instant, and it returns exactly the answer the first call got. That one property gives us three things at once:

- **a cache**, so rerunning a cell does not pay again;
- **a replay source**, so a reader can run the whole notebook offline and get our numbers;
- **a resume journal**, so a run that crashed halfway can be started again, and every call it already made comes back from the ledger. Part IV uses this instead of a separate journal.

The sample index exists because we sometimes want the **same** question asked **again on purpose**: three skeptics given the same finding, or the same scan repeated to see what a second look finds. Each repeat gets its own index, so each is a different fingerprint and a different, stored answer.

The ledger also keeps the **accounts**: every live call is recorded with its model, its role, its phase, its run and its cost in cents, worked out from its token counts, so the cost of anything in the notebook is one SQL query away.

**In plain terms.** Every answer is saved under a fingerprint of its question. Ask the same question again and you get the saved answer, free.

**For teams.** Keep a ledger like this for any evaluation of an agent you might want to repeat or defend. Without one, a rerun is a different experiment, and an argument about a result cannot be settled by looking at what the model actually said.

#%% md
**Storing the same code once.** A scan worker's request holds tens of thousands of tokens of code, and the same shard of code is sent many times: once per lens, once per run, once per ablation. Stored naively, the ledger would hold every copy and grow into gigabytes. So the text of every message is stored once, compressed, in a **blob** table keyed by its own hash, and a request only holds references to its blobs. The demo after the class measures what this saves.

#%% code
class CacheMiss(RuntimeError):
    """Replay mode met a request the ledger has never seen; the notebook was changed after the paid run."""


class SpendRefused(RuntimeError):
    """A paid call was refused: no key, the cap is reached, or the daily guard tripped."""


class Ledger:
    """Every model answer by fingerprint: the cache, the replay source and the accounts."""

    def __init__(self, path):
        self.path = Path(path)
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS calls (key TEXT PRIMARY KEY, model TEXT, role TEXT, tag TEXT, phase TEXT,
                run_id TEXT, day TEXT, request TEXT, reply BLOB, seconds REAL, prompt_tokens INT,
                completion_tokens INT, reasoning_chars INT, cents REAL, created REAL);
            CREATE TABLE IF NOT EXISTS blobs (hash TEXT PRIMARY KEY, data BLOB);
            CREATE TABLE IF NOT EXISTS failures (key TEXT PRIMARY KEY, model TEXT, tag TEXT, day TEXT, error TEXT);
        """)
        self.lock = threading.Lock()

    @staticmethod
    def key(model, messages, params, sample=0):
        """The fingerprint of a request: model, messages, parameters and sample index."""
        blob = json.dumps([model, messages, params, sample], sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()

show_def(CacheMiss, SpendRefused, Ledger)

#%% md
**`Ledger._blob`** stores one text, compressed, under its own hash, and only once however often it is stored. **`Ledger.put`** writes one answer: the request as references to blobs, and the reply compressed as a whole. It commits at once, so a crash loses at most the calls still in flight.

#%% code
@method_of(Ledger)
def _blob(self, text):
    h = hashlib.sha256(text.encode()).hexdigest()
    self.db.execute("INSERT OR IGNORE INTO blobs VALUES (?, ?)", (h, zlib.compress(text.encode(), 6)))
    return h


@method_of(Ledger)
def _unblob(self, h):
    row = self.db.execute("SELECT data FROM blobs WHERE hash = ?", (h,)).fetchone()
    return zlib.decompress(row[0]).decode() if row else None


@method_of(Ledger)
def put(self, key, model, request, reply, *, role="", tag="", phase="", run_id="", cents=0.0):
    with self.lock:
        compact = {"messages": [{"role": m["role"], "content": "blob:" + self._blob(m["content"])} for m in request["messages"]],
                   "params": request.get("params", {}), "sample": request.get("sample", 0)}
        self.db.execute("INSERT OR REPLACE INTO calls VALUES (?, ?, ?, ?, ?, ?, date('now'), ?, ?, ?, ?, ?, ?, ?, ?)",
                        (key, model, role, scrub(tag), phase, run_id, json.dumps(compact),
                         zlib.compress(scrub(json.dumps(asdict(reply))).encode(), 6), reply.seconds,
                         reply.prompt_tokens, reply.completion_tokens, len(reply.reasoning), cents, time.time()))
        self.db.execute("DELETE FROM failures WHERE key = ?", (key,))
        self.db.commit()

show_def(Ledger._blob, Ledger._unblob, Ledger.put)

#%% md
**`Ledger.get`** returns a stored answer as a `Reply` marked `cached`, or `None`. **`Ledger.put_failure`** and **`Ledger.failure`** keep the requests the API failed on, apart from the answers. They are not answers, so a later paid run tries them again, but a replay meets the same failure the paid run met, and its numbers match.

#%% code
@method_of(Ledger)
def get(self, key):
    with self.lock:
        row = self.db.execute("SELECT reply FROM calls WHERE key = ?", (key,)).fetchone()
    if not row:
        return None
    stored = json.loads(zlib.decompress(row[0]).decode())
    return Reply(**{**stored, "cached": True})


@method_of(Ledger)
def put_failure(self, key, model, tag, error):
    with self.lock:
        self.db.execute("INSERT OR REPLACE INTO failures VALUES (?, ?, ?, date('now'), ?)", (key, model, scrub(tag), scrub(error)))
        self.db.commit()


@method_of(Ledger)
def failure(self, key):
    with self.lock:
        row = self.db.execute("SELECT error FROM failures WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None

show_def(Ledger.get, Ledger.put_failure, Ledger.failure)

#%% md
**The accounts.** `Ledger.query` runs any SQL under the lock. `Ledger.accounts(by)` groups the live calls by model, role, phase or run, and `Ledger.spent()` is the total in cents. `Ledger.request_of(key)` rebuilds a full request from its blobs, which is how S63 audits what a worker was actually shown.

#%% code
@method_of(Ledger)
def query(self, sql, args=()):
    with self.lock:
        return self.db.execute(sql, args).fetchall()


@method_of(Ledger)
def accounts(self, by="model", where="1=1", args=()):
    cols = ["group", "calls", "prompt_tokens", "completion_tokens", "cents", "seconds"]
    rows = self.query(f"SELECT {by}, COUNT(*), SUM(prompt_tokens), SUM(completion_tokens), SUM(cents), SUM(seconds) "
                      f"FROM calls WHERE {where} GROUP BY {by} ORDER BY SUM(cents) DESC, COUNT(*) DESC", args)
    return [dict(zip(cols, r)) for r in rows]


@method_of(Ledger)
def spent(self):
    return self.query("SELECT COALESCE(SUM(cents), 0) FROM calls")[0][0]


@method_of(Ledger)
def request_of(self, key):
    row = self.query("SELECT request FROM calls WHERE key = ?", (key,))
    if not row:
        return None
    req = json.loads(row[0][0])
    for m in req["messages"]:
        m["content"] = self._unblob(m["content"][5:])
    return req

show_def(Ledger.query, Ledger.accounts, Ledger.spent, Ledger.request_of)

#%% md
**What the blob store saves.** Three requests that share one shard of 40,000 characters, as three lenses scanning the same code would, are written to a fresh ledger. A naive table would hold the shard three times.

#%% code
with tempfile.TemporaryDirectory() as tmp:
    demo_ledger = Ledger(Path(tmp) / "demo.sqlite")
    shard = "".join(SOURCES[p] for p in sorted(CORPUS)[:20])[:40_000]
    naive = 0
    for lens in ("boundaries", "logic", "state"):
        req = {"messages": [{"role": "system", "content": f"You review code. Lens: {lens}."},
                            {"role": "user", "content": shard}], "params": {"temperature": 0.6}, "sample": 0}
        k = Ledger.key("demo", req["messages"], req["params"])
        demo_ledger.put(k, "demo", req, Reply(text='{"findings": []}', finish="stop"), tag=f"scan:{lens}")
        naive += len(json.dumps(req).encode())
    demo_ledger.db.execute("VACUUM")
    on_disk = (Path(tmp) / "demo.sqlite").stat().st_size
    n_blobs = demo_ledger.query("SELECT COUNT(*) FROM blobs")[0][0]
    print(f"[ledger] 3 calls, {n_blobs} blobs: {on_disk / 1000:.0f} KB on disk instead of {naive / 1000:.0f} KB of raw requests "
          f"({naive / on_disk:.1f} times smaller)")
    rebuilt = demo_ledger.request_of(k)
    print(f"[ledger] request rebuilt from blobs: {len(rebuilt['messages'][1]['content']):,} characters, identical: "
          f"{rebuilt['messages'][1]['content'] == shard}")

#%% md
## S9 - The front door, and a model that is free

**Theory.** **`LLM.chat`** is the only way any code in this notebook reaches a model, and it decides where each answer comes from:

1. If the ledger holds the fingerprint, it returns the stored answer: free, instant and identical.
2. Otherwise, in `replay` mode it refuses with `CacheMiss`, because replay must never spend.
3. In `smoke` mode it asks the **scripted model**, a stand-in that answers from rules each section registers.
4. In `collect` mode it checks the guards (a key exists, the session cap is not reached, today's call count is under the daily guard), makes the real call, and charges its price.

Whatever produced the answer, it is stored, so the next identical call is free. The session **budget** that can pause work (S26) plugs into step 4 later; until then the guard is a plain refusal at the cap.

**In plain terms.** One door, three rooms behind it: the saved answers, the free pretend model, and the real model. The door checks the saved answers first.

#%% md
**`ScriptedModel`** is the free stand-in. Each section registers **responders**: small functions that recognise their own kind of request and return a plausible answer, or return `None` to let another responder try. The newest responder is asked first, so a later section can override an earlier one. A request nobody recognises gets an empty answer rather than an error, so a smoke run always reaches the end. An optional latency makes the stand-in take time like a real model, which the runtime demos in Part IV need. Each responder also receives the call's sample index among the parameters, so two samples of the same question can get two different answers, as they would from a real model.

#%% code
class ScriptedModel:
    """A free, deterministic stand-in for every model, built from per-section responders."""

    def __init__(self):
        self.responders = []
        self.latency = (0.0, 0.0)              # seconds, drawn uniformly; Part IV raises it for its demos

    def register(self, fn):
        self.responders.append(fn)
        return fn

    def __call__(self, model, messages, params):
        lo, hi = self.latency
        if hi > 0:
            seed = zlib.crc32(json.dumps(messages[-1]["content"][-200:]).encode())
            time.sleep(lo + (hi - lo) * (seed % 1000) / 1000)
        for fn in reversed(self.responders):
            text = fn(model, messages, params)
            if text is not None:
                n_in = sum(len(m["content"]) for m in messages) // 4
                thinking = params.get("enable_thinking") is not False
                return Reply(text=text, reasoning="(scripted)" if thinking else "", finish="stop", model=model,
                             prompt_tokens=n_in, completion_tokens=len(text) // 4 + 1, seconds=0.01, attempts=1)
        empty = "{}" if params.get("response_format") else "(the scripted model has no answer for this request)"
        return Reply(text=empty, finish="stop", model=model, attempts=1)

show_def(ScriptedModel)
SCRIPTED = ScriptedModel()


@SCRIPTED.register
def _ok(model, messages, params):
    return "OK" if "single word OK" in messages[-1]["content"] else None

show_def(_ok)

#%% md
**`LLM`** holds the mode, the ledger, the client and the scripted model, and counts what it served from where.

#%% code
class LLM:
    """The front door: ledger first, then scripted (smoke) or the network (collect); replay never spends."""

    def __init__(self, mode, ledger, client=None, scripted=None):
        self.mode, self.ledger, self.client, self.scripted = mode, ledger, client, scripted
        self.budget = None                     # the session Budget plugs in here (S26)
        self.live_calls, self.hits = 0, 0
        self.lock = threading.Lock()

show_def(LLM)

#%% md
**`LLM.chat`**, the door itself. Only answers and deterministic rejections are stored as answers. A transient failure goes to the failures table instead, so a later paid run retries it while a replay meets it exactly as the paid run did. Before a live call, its most possible cost (`reserve_of`) is checked against the cap; after it, the real cost (`price_of`, from the token counts the server reported) is charged. A call that failed after all its retries is assumed not to have been billed.

#%% code
DETERMINISTIC = ("HTTP 400", "HTTP 404", "HTTP 413", "HTTP 422")


@method_of(LLM)
def chat(self, model, messages, *, tag="", role="", phase="", run_id="", sample=0, **params):
    key = Ledger.key(model, messages, params, sample)
    hit = self.ledger.get(key)
    if hit:
        with self.lock:
            self.hits += 1
        return hit
    if self.mode == "replay":
        failed = self.ledger.failure(key)
        if failed:
            return Reply(model=model, finish="error", error=failed)
        raise CacheMiss(f"{tag or model}: no stored answer for this request; run in collect mode first")
    charged = 0.0
    price = reserve_of(model, messages, params.get("max_tokens", 8000))
    if self.mode == "smoke":
        reply = self.scripted(model, messages, dict(params, sample=sample))   # responders may vary by sample
    else:
        if self.client is None:
            raise SpendRefused("no API key, so nothing can be collected; replay needs no key")
        if self.ledger.query("SELECT COUNT(*) FROM calls WHERE day = date('now') AND cents > 0")[0][0] >= DAILY_CALL_CAP:
            raise SpendRefused("the daily call guard tripped; the next run resumes from the ledger")
        if self.budget is not None:
            self.budget.admit(price, who=tag or role or model)          # may pause here until the cap is raised
        elif self.ledger.spent() + price > CAP_CENTS:
            raise SpendRefused(f"the session cap of {CAP_CENTS} cents is reached")
        try:
            reply = self.client.chat(model, messages, **params)
        except BaseException:
            if self.budget is not None:
                self.budget.settle(price, 0.0)
            raise
        charged = price_of(model, reply) if reply.finish != "error" else 0.0
        if self.budget is not None:
            self.budget.settle(price, charged)
        with self.lock:
            self.live_calls += 1
    request = {"messages": messages, "params": params, "sample": sample}
    if reply.finish != "error" or (reply.error or "").startswith(DETERMINISTIC):
        self.ledger.put(key, model, request, reply, role=role, tag=tag, phase=phase, run_id=run_id, cents=charged)
    else:
        self.ledger.put_failure(key, model, tag, reply.error or "")
    return reply

show_def(LLM.chat)

#%% md
**The door, tested against the local server.** A throwaway ledger and a client pointed at `FakeModelServer` let us watch every rule work over real HTTP. The server counts the requests it receives, so "free" can be checked rather than believed.

#%% code
with tempfile.TemporaryDirectory() as tmp:
    door = LLM("collect", Ledger(Path(tmp) / "door.sqlite"), ModelClient("sk-ant-test-key-not-real-000000", endpoint=FAKE.endpoint))
    q = [{"role": "user", "content": "What is 2 + 2? Reply with one number."}]
    before = FAKE.calls
    a1 = door.chat("fake", q, tag="first")
    a2 = door.chat("fake", q, tag="again, with another tag")
    a3 = door.chat("fake", q, tag="a deliberate repeat", sample=1)
    after = FAKE.calls
    replay = LLM("replay", door.ledger)
    a4 = replay.chat("fake", q)
    try:
        replay.chat("fake", [{"role": "user", "content": "a question nobody asked"}])
        missed = False
    except CacheMiss:
        missed = True
    acc = door.ledger.accounts("model")
    print(f"[door] 3 calls made, the server received {after - before}: first live, second from the ledger, third live (sample 1)")
    print(f"[door] cached flags: {a1.cached}, {a2.cached}, {a3.cached}; replay answered from the ledger: {a4.cached}")
    table(acc, [("group", "model", ""), ("calls", "calls", "d"), ("cents", "cents", ".2f")])
results = []
expect("an identical request is served by the ledger and reaches no server", after - before == 2 and a2.cached and not a1.cached)
expect("the tag is not part of the fingerprint", a2.text == a1.text)
expect("a new sample index is a new, paid call", not a3.cached)
expect("replay answers from the ledger", a4.cached and a4.text == a1.text)
expect("replay refuses a request it has never seen", missed)
expect("the accounts charge two live calls, at the test server's flat price", acc[0]["calls"] == 2 and abs(acc[0]["cents"] - 2 * price_of("fake", a1)) < 1e-9)

#%% md
**The notebook's own front door.** From here on every model call in the notebook goes through `FRONT_DOOR`. In smoke mode it gets a fresh ledger of its own, so a smoke run never mixes with the paid answers; in collect and replay mode it uses the committed ledger.

#%% code
if DW_MODE == "smoke":
    ledger_path = ART / "cache" / "smoke_ledger.sqlite"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if ledger_path.exists():
        ledger_path.unlink()
else:
    ledger_path = LEDGER_PATH
LEDGER = Ledger(ledger_path)
CLIENT = ModelClient(API_KEY, gate_factory=lambda m: FixedGate(4)) if API_KEY else None
FRONT_DOOR = LLM(DW_MODE, LEDGER, CLIENT, SCRIPTED)
print(f"[llm] mode {DW_MODE}; ledger {rel(ledger_path)} holds {LEDGER.query('SELECT COUNT(*) FROM calls')[0][0]:,} answers; "
      f"client {'ready' if CLIENT else 'none (no key needed in this mode)' if DW_MODE != 'collect' else 'none'}; "
      f"spent so far {LEDGER.spent():.2f} of {CAP_CENTS:,.0f} cents")
