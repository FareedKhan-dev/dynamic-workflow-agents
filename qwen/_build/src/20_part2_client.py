#%% md
# Part II. Talking to models

Before a lead can hand work to forty workers, one call to one model has to be dependable.

**Where this sits.** Part I built the job without touching a model. Part II builds the plumbing every agent in the rest of the notebook will use. The pieces are a streaming client, a local stand-in server to test it against, a ledger that records every answer, a gate that controls how many calls run at once, and the probes that tell us what each of the six models can do. It ends with the first real measurement of the notebook: how much code one worker can read in one call before it starts missing bugs. That number sets the size of every piece of work in Parts IV to VII.

**By the end of this Part you can**

- stream an answer from a reasoning model and keep its reasoning apart from its reply;
- test a network client against a local server that fails on purpose, before spending anything;
- explain why every answer is stored, and how that makes a rerun free;
- control concurrency so the server is not overwhelmed and does not sit idle;
- choose how much work to put in one call, from a measurement rather than a guess.

![part2_map](attachment:part2_map.png)

#%% md
## S5 - Credentials: the key is read once and never seen again

**Theory.** The API key is the one thing in this project that must never be printed, stored, committed or sent anywhere except to the model server. We read it from the `MODELSCOPE_API_KEY` environment variable, only in `collect` mode (smoke and replay never need it), and add it to the list `scrub` removes from every output. The check at the end of the notebook (S76) scans every file in the project for the key's bytes.

**In plain terms.** The key goes from the environment straight into the request header, and nowhere else.

**For teams.** Put the scan in your build, not in your memory. A key in a notebook output is a key on GitHub the moment someone pushes.

#%% code
def load_key():
    """The ModelScope key from the environment, or None. It must look like a key, or nothing is sent."""
    key = os.environ.get("MODELSCOPE_API_KEY", "").strip()
    if not key:
        return None
    if not re.fullmatch(r"ms-[0-9A-Za-z-]{20,}", key):
        raise ValueError("[key] MODELSCOPE_API_KEY does not look like a ModelScope key")
    return key


def describe_key(key):
    """What may be said about a key in public: whether it is there, and its length."""
    return "absent" if not key else f"present, {len(key)} characters"

show_def(load_key, describe_key)
API_KEY = load_key() if DW_MODE == "collect" else None   # not ANSWER_KEY: that name holds the answer key since S3
if API_KEY:
    SECRETS.append(API_KEY)
print(f"[key] mode {DW_MODE}: key {describe_key(API_KEY)}; the environment holds one: {bool(os.environ.get('MODELSCOPE_API_KEY'))}")
print(f"[key] scrub test: {scrub('Authorization: Bearer ' + (API_KEY or 'ms-not-a-real-key-0000000000'))!r}")

#%% md
**`key_leak_scan(paths)`** looks for the key's bytes inside files. It runs here on the project as it stands, and again at the very end on everything the notebook wrote.

#%% code
def key_leak_scan(root=ROOT):
    """Files under root that contain the key's bytes (empty when there is no key to look for)."""
    key = os.environ.get("MODELSCOPE_API_KEY", "").strip().encode()
    if not key:
        return []
    hits = []
    for p in Path(root).rglob("*"):
        if p.is_file() and not any(part in (".venv", ".git", ".uv-cache") for part in p.parts):
            try:
                if key in p.read_bytes():
                    hits.append(rel(p))
            except OSError:
                pass
    return hits

show_def(key_leak_scan)
leaks = key_leak_scan()
print(f"[leak] {len(leaks)} files contain the key" + (f": {leaks[:5]}" if leaks else ""))

#%% md
## S6 - A streaming client in the standard library

**Theory.** The six models are reached through one **OpenAI-compatible** endpoint: we POST a JSON body with the model's name and a list of messages, and the server answers. All six are **reasoning models**: before answering they think, sometimes for a minute, and on this service that only works with a **streamed** reply. The server sends **server-sent events**, one line per small piece, each line starting with `data: ` and holding a JSON object. The reasoning arrives first in a field called `reasoning_content`, the answer follows in `content`, and when we ask for it with `stream_options`, a final event carries the token counts.

Network calls fail in many ways. The client sorts failures into those worth retrying and those that are not:

- **retry:** a timeout, a dropped connection, a 5xx from the server, and a 429 that means "slow down";
- **stop:** a 429 that means the account has run out of Magicubes, and a 401 or 403;
- **keep:** a 400, 404 or 422, which would fail the same way again. The ledger keeps these, so the next run does not pay to rediscover them.

**In plain terms.** The client asks, reads the answer as it arrives, gives up politely when it should, and never hammers a service that is struggling.

**For teams.** Write the failure policy down as a table, as below, and test every row. A retry loop nobody tested is how a quota disappears overnight.

#%% md
**`Reply`** is one answer, with everything we will want to know about it later: the text, the reasoning, why it stopped, the token counts the server reported, how long it took, how many tries it needed, any error, whether it came from the ledger instead of the network, and the quota the server said we have left.

#%% code
@dataclass
class Reply:
    text: str = ""                # the answer, assembled from the content stream
    reasoning: str = ""           # what the model thought first, from the reasoning_content stream
    finish: str = None            # stop, length or error
    prompt_tokens: int = 0        # as the server counted them, from the final usage event
    completion_tokens: int = 0    # the answer and the reasoning, in tokens
    seconds: float = 0.0          # the whole call
    first_byte: float = None      # seconds until the first line arrived
    model: str = ""               # the model that answered
    attempts: int = 0             # tries the call needed
    error: str = None             # set only when finish is "error"
    cached: bool = False          # True when the ledger answered instead of the network
    quota: dict = field(default_factory=dict)   # the server's modelscope-ratelimit-* headers

show_def(Reply)

#%% md
**`parse_sse(lines)`** folds a stream of event lines into one `Reply`. It skips keep-alive lines and the final `data: [DONE]`, adds each piece of text to the right field, and takes the token counts from the last event. Below it runs on a stream with exactly the shape these models send.

#%% code
def parse_sse(lines, model=""):
    """Fold server-sent event lines into one Reply."""
    reply = Reply(model=model)
    for line in lines:
        line = line.strip()
        if not line.startswith("data:") or line == "data: [DONE]":
            continue
        chunk = json.loads(line[5:])
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            reply.text += delta.get("content") or ""
            reply.reasoning += delta.get("reasoning_content") or ""
            reply.finish = choice.get("finish_reason") or reply.finish
        usage = chunk.get("usage") or {}
        reply.prompt_tokens = usage.get("prompt_tokens", reply.prompt_tokens)
        reply.completion_tokens = usage.get("completion_tokens", reply.completion_tokens)
    return reply

show_def(parse_sse)
RECORDED = [
    'data: {"choices":[{"delta":{"reasoning_content":"The user wants one word."}}]}',
    ': keep-alive',
    'data: {"choices":[{"delta":{"content":"O"}}]}',
    'data: {"choices":[{"delta":{"content":"K"},"finish_reason":"stop"}]}',
    'data: {"choices":[],"usage":{"prompt_tokens":64,"completion_tokens":14,"total_tokens":78}}',
    'data: [DONE]',
]
r = parse_sse(RECORDED, "demo")
print(f"[sse] {len(RECORDED)} lines -> text {r.text!r}, reasoning {r.reasoning!r}, finish {r.finish}, "
      f"tokens {r.prompt_tokens}+{r.completion_tokens}")

#%% md
**The failure policy as a table.** **`classify_error(status, body)`** maps an HTTP status and the start of the error body to one action. The rows below are real error shapes this service returns: a rate limit, an empty balance, a model still loading, a bad request.

#%% code
class OutOfMagicubes(RuntimeError):
    """The account's balance is spent; retrying would only fail again."""


class AccessDenied(RuntimeError):
    """The key is missing, wrong, or not allowed to use this model."""


def classify_error(status, body):
    """retry, throttled, out of magicubes, denied or keep (a deterministic rejection worth storing)."""
    low = body.lower()
    if status == 429 and ("balance" in low or "insufficient_balance" in low):
        return "out of magicubes"
    if status == 429:
        return "throttled"
    if status in (401, 403):
        return "denied"
    if status in (400, 404, 422):
        return "keep"
    if status in (408, 409, 425, 500, 502, 503, 504):
        return "retry"
    return "retry"

show_def(OutOfMagicubes, AccessDenied, classify_error)
POLICY_CASES = [(429, '{"error":{"message":"Request rate increased too quickly, scale requests more smoothly"}}'),
                (429, '{"error":{"code":"insufficient_balance_error","message":"insufficient balance"}}'),
                (503, '{"error":{"code":"model_not_ready","message":"model is still loading"}}'),
                (400, '{"error":{"message":"The value of the enable_thinking parameter is restricted to True."}}'),
                (403, '{"error":{"message":"not entitled to this model"}}'),
                (502, 'Bad Gateway')]
table([{"status": s, "body": b[:62], "action": classify_error(s, b)} for s, b in POLICY_CASES],
      [("status", "status", "d"), ("body", "start of the body", ""), ("action", "action", "")])

#%% md
### A server we control

**Theory.** A client that talks to a paid service is hard to test, because the failures you most need to test are the ones you cannot order on demand: a rate limit, a model still loading, a stream that stalls halfway. So before the client meets the real service, it meets **`FakeModelServer`**: a tiny OpenAI-compatible server running inside the notebook on `127.0.0.1`. It speaks the same streaming protocol and sends the same quota headers. It fails on command, when a message contains a marker such as `[503 once]` or `[slow]`. It also has a **capacity**: when more calls are in flight than it allows, it answers 429 with the same text the real service uses. Everything in this section and in S10 runs against it, over real HTTP, for free.

**In plain terms.** We build a pretend model server that we can break on purpose, and make sure the client copes with every way it breaks.

#%% code
import http.server
import socketserver


class FakeModelServer:
    """A local OpenAI-compatible streaming server with a capacity, quota headers and failures on demand."""

    def __init__(self, capacity=6, latency=0.03, chunks=8, delay_fn=None, json_fn=None):
        self.capacity, self.latency, self.chunks = capacity, latency, chunks
        self.delay_fn = delay_fn      # optional: total seconds for a request, from its text (Part IV uses measured latencies)
        self.json_fn = json_fn        # optional: the JSON object to answer in JSON mode, from the request body
        self.in_flight, self.peak, self.calls, self.rejected = 0, 0, 0, collections.Counter()
        self.lock = threading.Lock()
        self.seen = collections.Counter()   # how many times each request text has been served
        self.remaining = 5000
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):            # quiet: the notebook prints what matters
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.handle(self, body)

        self.httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        self.endpoint = f"http://127.0.0.1:{self.port}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def reset_seen(self):
        """Forget which texts were served, so two trials start on equal terms."""
        with self.lock:
            self.seen.clear()

show_def(FakeModelServer)

#%% md
**`FakeModelServer.handle`** decides what one request gets. It checks the capacity first, exactly as a busy real server would, and then looks for a failure marker in the last message. Only a request with no marker gets a normal streamed answer: a sentence of reasoning, then the reply in small pieces, then the token counts. When the request asks for JSON mode, the reply is a small JSON object. The server counts how often it has served each text: `[503 once]` fails only the first time, and when a `delay_fn` sets the latency, a repeated request gets a fresh draw instead of the same delay again, which is how a real server behaves when a request is retried.

#%% code
@method_of(FakeModelServer)
def handle(self, h, body):
    text = body["messages"][-1]["content"]
    with self.lock:
        self.calls += 1
        busy = self.in_flight >= self.capacity
        if not busy:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.remaining -= 1
            n = self.seen[text]                   # 0 the first time this text is served, 1 the second time, ...
            self.seen[text] += 1
    if busy:
        self.rejected["429 busy"] += 1
        return self.error(h, 429, "Request rate increased too quickly, scale requests more smoothly over time.")
    try:
        if "[balance]" in text:
            return self.error(h, 429, '{"error":{"code":"insufficient_balance_error","message":"insufficient balance"}}')
        if "[bad]" in text:
            return self.error(h, 400, '{"error":{"message":"invalid parameter"}}')
        if "[503 once]" in text and n == 0:
            self.rejected["503 once"] += 1
            return self.error(h, 503, '{"error":{"code":"model_not_ready","message":"model is still loading"}}')
        if "response_format" in body:
            answer = json.dumps(self.json_fn(body) if self.json_fn else {"answer": "ok", "echo": text[-20:]})
        else:
            answer = "OK. " + text[-40:]
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("modelscope-ratelimit-requests-remaining", str(self.remaining))
        h.send_header("modelscope-ratelimit-model-requests-remaining", str(self.remaining // 2))
        h.end_headers()
        events = [{"choices": [{"delta": {"reasoning_content": "Let me think about this."}}]}]
        step = max(1, len(answer) // self.chunks)
        events += [{"choices": [{"delta": {"content": answer[i:i + step]}}]} for i in range(0, len(answer), step)]
        events[-1]["choices"][0]["finish_reason"] = "stop"
        events.append({"choices": [], "usage": {"prompt_tokens": len(text) // 4, "completion_tokens": len(answer) // 4 + 6}})
        if self.delay_fn:                         # a repeat gets a fresh draw, as a retry to a real server would
            total = self.delay_fn(text if n == 0 else f"{text}#{n}")
        else:
            total = self.latency * (8 if "[slow]" in text else 1) * len(events)
        for ev in events:
            time.sleep(total / len(events))                 # the reply trickles in over the whole delay
            h.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
            h.wfile.flush()
        h.wfile.write(b"data: [DONE]\n\n")
    except (BrokenPipeError, ConnectionResetError):
        pass                                      # the client gave up, which is its right
    finally:
        with self.lock:
            self.in_flight -= 1


@method_of(FakeModelServer)
def error(self, h, status, text):
    h.send_response(status)
    h.send_header("Content-Type", "application/json")
    h.end_headers()
    h.wfile.write(text.encode())

show_def(FakeModelServer.handle, FakeModelServer.error)
FAKE = FakeModelServer(capacity=6)
print(f"[fake] serving on {FAKE.endpoint}, capacity {FAKE.capacity} calls in flight")

#%% md
### The client, one method at a time

**`FixedGate`** is the simplest way to limit concurrency: a fixed number of slots per model. A call waits for a free slot, holds it for its duration, and gives it back. It reports successes and throttles but ignores them. S10 replaces it with a gate that learns the right limit, and measures the difference.

#%% code
class FixedGate:
    """A fixed number of concurrent calls; ignores what the server says."""

    def __init__(self, limit):
        self.limit = limit
        self.sem = threading.BoundedSemaphore(limit)
        self.timeline = []                         # (time, limit, event) for the figures in S10

    @contextlib.contextmanager
    def slot(self):
        self.sem.acquire()
        try:
            yield self
        finally:
            self.sem.release()

    def ok(self):
        self.timeline.append((time.perf_counter(), self.limit, "ok"))

    def throttled(self):
        self.timeline.append((time.perf_counter(), self.limit, "throttled"))

show_def(FixedGate)

#%% md
**`ModelClient`** holds the key, the endpoint, one gate per model, and a **circuit breaker**: after five failed calls in a row to one model, the client leaves that model alone for two minutes instead of piling more requests onto a service that is already in trouble. A shared `stop` event lets a run that is being cancelled end every retry loop at once.

#%% code
class ModelClient:
    """Streaming chat completions over HTTP with only the standard library."""

    def __init__(self, key, endpoint=ENDPOINT, max_attempts=4, gate_factory=None):
        self.key = key                             # sent only in a request header, never stored
        self.endpoint = endpoint.rstrip("/")
        self.max_attempts = max_attempts           # the first try plus up to three retries
        self.gate_factory = gate_factory or (lambda model: FixedGate(4))
        self.gates, self.failures, self.open_until = {}, {}, {}
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.events = []                           # (time, model, what happened) for the figures

    def gate(self, model):
        with self.lock:
            if model not in self.gates:
                self.gates[model] = self.gate_factory(model)
            return self.gates[model]

show_def(ModelClient)

#%% md
**`ModelClient._stream`** makes one attempt. It sends the request, records the quota headers, and reads the stream line by line, checking the deadline on every line rather than only at the end, so a stream that trickles forever is still cut off on time.

#%% code
QUOTA_PREFIX = "modelscope-ratelimit-"


@method_of(ModelClient)
def _stream_once(self, body, deadline):
    req = urllib.request.Request(f"{self.endpoint}/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
    start = time.perf_counter()
    lines, first, pending = [], None, b""
    with urllib.request.urlopen(req, timeout=min(60, deadline)) as resp:
        quota = {k[len(QUOTA_PREFIX):]: v for k, v in resp.headers.items() if k.lower().startswith(QUOTA_PREFIX)}
        while True:
            # read1 hands back whatever has arrived, so the deadline is checked after every piece of data, even when one
            # line trickles in over many pieces (a readline here could wait on that one line for ever)
            piece = resp.read1(65536)
            if not piece:
                break
            if first is None:
                first = time.perf_counter() - start
            if time.perf_counter() - start > deadline:
                raise TimeoutError(f"the call ran past its {deadline}s deadline")
            *done, pending = (pending + piece).split(b"\n")
            lines.extend(line.decode("utf-8") for line in done)
    if pending.strip():
        lines.append(pending.decode("utf-8"))
    reply = parse_sse(lines, body["model"])
    reply.seconds, reply.first_byte, reply.quota = time.perf_counter() - start, first, quota
    return reply

show_def(ModelClient._stream_once)

@method_of(ModelClient)
def _stream(self, body, deadline):
    """One attempt, cut off at its deadline even when a read blocks: the read runs in its own thread, which is abandoned on time."""
    box = {}

    def attempt():
        try:
            box["reply"] = self._stream_once(body, deadline)
        except BaseException as e:
            box["error"] = e

    worker = threading.Thread(target=attempt, daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        raise TimeoutError(f"the call ran past its {deadline}s deadline")
    if "error" in box:
        raise box["error"]
    return box["reply"]

show_def(ModelClient._stream)

#%% md
**`ModelClient.chat`** is the retry loop. Each attempt holds a gate slot only while it is talking to the server; the wait between attempts happens outside the slot, so a sleeping retry never blocks another call. The wait grows with each attempt (1, 2, 4, 8 seconds, at most 30) and is multiplied by a random factor between 0.5 and 1. That jitter matters as soon as calls run in parallel: without it, every call that failed together would retry together and fail together again.

#%% code
import http.client

RETRYABLE = (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError,
             http.client.HTTPException, UnicodeDecodeError)


@method_of(ModelClient)
def chat(self, model, messages, **params):
    body = {"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}, **params}
    deadline = CALL_DEADLINE_S.get(model, CALL_DEADLINE_S["default"])
    if time.time() < self.open_until.get(model, 0):
        return Reply(model=model, finish="error", error="circuit open after repeated failures")
    gate, last, attempt = self.gate(model), None, 0
    while attempt < self.max_attempts and not self.stop.is_set():
        attempt += 1
        with gate.slot():
            try:
                reply = self._stream(body, deadline)
                gate.ok()
                reply.attempts = attempt
                with self.lock:
                    self.failures[model] = 0
                self.events.append((time.perf_counter(), model, "ok"))
                return reply
            except urllib.error.HTTPError as e:
                text = e.read()[:300].decode("utf-8", "replace")
                action = classify_error(e.code, text)
                self.events.append((time.perf_counter(), model, f"HTTP {e.code}"))
                if action == "out of magicubes":
                    raise OutOfMagicubes(scrub(text))
                if action == "denied":
                    raise AccessDenied(scrub(f"HTTP {e.code}: {text}"))
                if action == "keep":
                    return Reply(model=model, finish="error", error=scrub(f"HTTP {e.code}: {text}"), attempts=attempt)
                if action == "throttled":
                    gate.throttled()
                last = f"HTTP {e.code}: {text[:120]}"
            except RETRYABLE as e:
                last = f"{type(e).__name__}: {e}"
                self.events.append((time.perf_counter(), model, type(e).__name__))
        if attempt < self.max_attempts:
            time.sleep(min(30, 2 ** (attempt - 1)) * (0.5 + random.random() / 2) * self.backoff_scale)
    with self.lock:
        self.failures[model] = self.failures.get(model, 0) + 1
        if self.failures[model] >= 5:
            self.open_until[model] = time.time() + 120
    return Reply(model=model, finish="error", error=scrub(last or "stopped"), attempts=attempt)


ModelClient.backoff_scale = 1.0   # the tests below shrink the waits; real runs keep them
show_def(ModelClient.chat)

#%% md
**Testing every row of the policy, over real HTTP.** Each case sends one request to the local server with a marker that makes it fail in one particular way, and checks what the client did. The waits between retries are shortened for the test; nothing else is changed.

#%% code
test_client = ModelClient("ms-test-key-not-real-000000", endpoint=FAKE.endpoint, gate_factory=lambda m: FixedGate(2))
test_client.backoff_scale = 0.02
msgs = lambda text: [{"role": "user", "content": text}]

r_ok = test_client.chat("fake", msgs("hello"))
r_json = test_client.chat("fake", msgs("give json"), response_format={"type": "json_object"})
r_503 = test_client.chat("fake", msgs("load me [503 once]"))
r_bad = test_client.chat("fake", msgs("[bad] request"))
CALL_DEADLINE_S["fake-slow"] = 0.5
r_slow = test_client.chat("fake-slow", msgs("take your time [slow]"))
try:
    test_client.chat("fake", msgs("[balance]"))
    balance_raised = False
except OutOfMagicubes:
    balance_raised = True
for name, rr in [("ordinary", r_ok), ("json mode", r_json), ("503 once", r_503), ("bad request", r_bad), ("too slow", r_slow)]:
    print(f"  {name:<12} finish {str(rr.finish):<6} attempts {rr.attempts}  text {rr.text[:34]!r:<38} "
          f"error {str(rr.error)[:44]!r}  quota {rr.quota}")
results = []
expect("an ordinary call streams text and reasoning", r_ok.text.startswith("OK") and r_ok.reasoning and r_ok.finish == "stop")
expect("token counts arrive from the final event", r_ok.prompt_tokens > 0 and r_ok.completion_tokens > 0)
expect("quota headers are recorded", "requests-remaining" in r_ok.quota)
expect("JSON mode returns parseable JSON", json.loads(r_json.text)["answer"] == "ok")
expect("a 503 is retried and then succeeds", r_503.finish == "stop" and r_503.attempts == 2)
expect("a 400 is not retried and is kept as an error", r_bad.finish == "error" and r_bad.attempts == 1 and "400" in r_bad.error)
expect("a stream past its deadline is cut off and retried, then reported", r_slow.finish == "error" and "deadline" in r_slow.error)
expect("an empty balance stops at once", balance_raised)

#%% md
## S7 - What the server says about our quota

Every answer from this service carries headers that begin with `modelscope-ratelimit-`: how many requests the account has left, and how many it has left for this model. The client stores them on the `Reply`. They do not change any decision on their own, but they are the earliest warning that a long experiment is about to run out of quota, so the status line in S27 shows them, and the accounts in S71 keep them.

#%% code
def quota_line(reply):
    """The quota headers of one reply as a short line."""
    if not reply.quota:
        return "no quota headers (smoke or replay)"
    return ", ".join(f"{k.replace('requests-remaining', 'left')}: {v}" for k, v in sorted(reply.quota.items()))

show_def(quota_line)
print(f"[quota] {quota_line(r_ok)}")
