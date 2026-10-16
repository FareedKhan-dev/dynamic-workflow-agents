#%% md
# Part II. Talking to models

Before a lead can hand work to forty workers, one call to one model has to be dependable.

**Where this sits.** Part I built the job without touching a model. Part II builds the plumbing every agent in the rest of the notebook will use. The pieces are a streaming client, a local stand-in server to test it against, a ledger that records every answer, a gate that controls how many calls run at once, and the probes that tell us what each model can do. It ends with the first real measurement of the notebook: how much code one worker can read in one call before it starts missing bugs. That number sets the size of every piece of work in Parts IV to VII.

**By the end of this Part you can**

- stream an answer from a reasoning model and keep its reasoning apart from its reply;
- test a network client against a local server that fails on purpose, before spending anything;
- explain why every answer is stored, and how that makes a rerun free;
- control concurrency so the server is not overwhelmed and does not sit idle;
- choose how much work to put in one call, from a measurement rather than a guess.

![part2_map](attachment:part2_map.png)

#%% md
## S5 - Credentials: the key is read once and never seen again

**Theory.** The API key is the one thing in this project that must never be printed, stored, committed or sent anywhere except to the model server. We read it from the `CLAUDE_API_KEY` environment variable, only in `collect` mode (smoke and replay never need it), and add it to the list `scrub` removes from every output. The check at the end of the notebook (S76) scans every file in the project for the key's bytes.

**In plain terms.** The key goes from the environment straight into the request header, and nowhere else.

**For teams.** Put the scan in your build, not in your memory. A key in a notebook output is a key on GitHub the moment someone pushes.

#%% code
KEY_VARIABLE = "CLAUDE_API_KEY"


def load_key():
    """The API key from the environment, or None. It must look like a key, or nothing is sent."""
    key = os.environ.get(KEY_VARIABLE, "").strip()
    if not key:
        return None
    if not re.fullmatch(r"sk-ant-[0-9A-Za-z_-]{20,}", key):
        raise ValueError(f"[key] {KEY_VARIABLE} does not look like an API key")
    return key


def describe_key(key):
    """What may be said about a key in public: whether it is there, and its length."""
    return "absent" if not key else f"present, {len(key)} characters"

show_def(load_key, describe_key)
API_KEY = load_key() if DW_MODE == "collect" else None   # not ANSWER_KEY: that name holds the answer key since S3
if API_KEY:
    SECRETS.append(API_KEY)
print(f"[key] mode {DW_MODE}: key {describe_key(API_KEY)}; the environment holds one: {bool(os.environ.get(KEY_VARIABLE))}")
print(f"[key] scrub test: {scrub('x-api-key: ' + (API_KEY or 'sk-ant-not-a-real-key-0000000000'))!r}")

#%% md
**`key_leak_scan(paths)`** looks for the key's bytes inside files. It runs here on the project as it stands, and again at the very end on everything the notebook wrote.

#%% code
def key_leak_scan(root=ROOT):
    """Files under root that contain the key's bytes (empty when there is no key to look for)."""
    key = os.environ.get(KEY_VARIABLE, "").strip().encode()
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

**Theory.** Every model is reached through one endpoint: we POST a JSON body with the model's name, a system prompt and a list of messages, and the server answers. Most of these models can **think** before they answer, sometimes at length, so we always ask for a **streamed** reply: a long silence on an open connection looks like a dead one, and a stream shows progress from the first second. The server sends **server-sent events**, one JSON object per small piece, each on a line starting with `data: `. The first event carries the count of tokens sent, then come pieces of thinking (`thinking_delta`) and pieces of the answer (`text_delta`), and a closing event carries the reason the answer stopped and the count of tokens received.

Network calls fail in many ways. The client sorts failures into those worth retrying and those that are not:

- **retry:** a timeout, a dropped connection, a 5xx or 529 ("overloaded") from the server, and a 429 that means "slow down";
- **stop:** an error that says the account's credit is spent, and a 401 or 403;
- **keep:** a 400, 404, 413 or 422, which would fail the same way again. The ledger keeps these, so the next run does not pay to rediscover them.

**In plain terms.** The client asks, reads the answer as it arrives, gives up politely when it should, and never hammers a service that is struggling.

**For teams.** Write the failure policy down as a table, as below, and test every row. A retry loop nobody tested is how a quota disappears overnight.

#%% md
**`Reply`** is one answer, with everything we will want to know about it later: the text, the reasoning, why it stopped, the token counts the server reported, how long it took, how many tries it needed, any error, whether it came from the ledger instead of the network, and the quota the server said we have left.

#%% code
@dataclass
class Reply:
    text: str = ""                # the answer, assembled from the content stream
    reasoning: str = ""           # what the model thought first, from the thinking stream
    finish: str = None            # stop, length, refusal or error
    prompt_tokens: int = 0        # tokens sent, as the server counted them (cached ones included)
    completion_tokens: int = 0    # the answer and the thinking, in tokens
    cache_read: int = 0           # tokens sent that the server read from its prompt cache (billed at a tenth)
    cache_write: int = 0          # tokens sent that the server wrote to its prompt cache (billed at 1.25 times)
    seconds: float = 0.0          # the whole call
    first_byte: float = None      # seconds until the first line arrived
    model: str = ""               # the model that answered
    attempts: int = 0             # tries the call needed
    error: str = None             # set only when finish is "error"
    cached: bool = False          # True when the ledger answered instead of the network
    quota: dict = field(default_factory=dict)   # the server's anthropic-ratelimit-* headers

show_def(Reply)

#%% md
**What a call costs.** Billing is per token: one price per million tokens sent and another per million received, from the table in S0. Tokens the server reads from its prompt cache cost a tenth of the full price, and tokens it writes to the cache cost a quarter more. **`price_of(model, reply)`** turns a reply's token counts into cents. **`reserve_of(model, messages, max_tokens)`** is the most a call can cost before it is made: its prompt, estimated from its length, plus the longest answer it is allowed. The budget of S26 reserves that much while a call is in flight. A model with a flat price per call, like the local test server below, is given a single number instead of a pair.

#%% code
def _rates(model, sent):
    rates = PRICE.get(model, 0.2)
    limit, high = LONG_PROMPT.get(model, (None, None))
    return high if limit and sent > limit else rates


def price_of(model, reply):
    """Cents for one reply, from its token counts; a flat price per call when the model has one."""
    rates = _rates(model, reply.prompt_tokens)
    if isinstance(rates, (int, float)):
        return float(rates)
    fresh = max(0, reply.prompt_tokens - reply.cache_read - reply.cache_write)
    sent = fresh + 1.25 * reply.cache_write + 0.1 * reply.cache_read
    return (sent * rates[0] + reply.completion_tokens * rates[1]) / 1e6 * 100


def reserve_of(model, messages, max_tokens):
    """The most one call can cost, in cents: its prompt, estimated from its length, plus its longest allowed answer."""
    sent = sum(len(m["content"]) for m in messages) // 3 + 50
    return price_of(model, Reply(prompt_tokens=sent, completion_tokens=max_tokens))

TYPICAL_ANSWER = 3000                                   # tokens a typical answer takes, thinking included, when only an estimate is possible


def call_cents(model, sent, received=TYPICAL_ANSWER):
    """Cents for a call that sends `sent` tokens and gets `received` back."""
    return price_of(model, Reply(prompt_tokens=sent, completion_tokens=received))


def price_text(roles):
    """The price list as a lead reads it."""
    return "; ".join(f"{r} ${PRICE[MODELS[r]][0]:.2f} sent / ${PRICE[MODELS[r]][1]:.2f} received" for r in roles)

show_def(_rates, price_of, reserve_of, call_cents, price_text)
scan_like = Reply(prompt_tokens=20_000, completion_tokens=2_000)
for role in ("worker", "judge", "lead"):
    print(f"[price] a {role} call sending 20,000 tokens and getting 2,000 back: {price_of(MODELS[role], scan_like):.2f} cents "
          f"({MODELS[role]}); reserved before it starts: {reserve_of(MODELS[role], [{'role': 'user', 'content': 'x' * 70_000}], 16_000):.2f}")

#%% md
**`parse_sse(lines)`** folds a stream of event lines into one `Reply`. It skips the `event:` lines and keep-alive pings, adds each piece of text to the right field, takes the tokens sent from the first event and the tokens received from the last. Below it runs on a stream with exactly the shape the provider sends.

#%% code
STOP = {"end_turn": "stop", "stop_sequence": "stop", "max_tokens": "length", "refusal": "refusal"}


def parse_sse(lines, model=""):
    """Fold server-sent event lines into one Reply."""
    reply = Reply(model=model)
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        ev = json.loads(line[5:])
        kind = ev.get("type")
        if kind == "message_start":
            u = ev["message"].get("usage") or {}
            reply.cache_read, reply.cache_write = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
            reply.prompt_tokens = (u.get("input_tokens") or 0) + reply.cache_read + reply.cache_write
        elif kind == "content_block_delta":
            d = ev.get("delta") or {}
            reply.text += d.get("text") or ""
            reply.reasoning += d.get("thinking") or ""
        elif kind == "message_delta":
            reply.finish = STOP.get((ev.get("delta") or {}).get("stop_reason"), reply.finish)
            reply.completion_tokens = (ev.get("usage") or {}).get("output_tokens", reply.completion_tokens)
        elif kind == "error":
            raise ConnectionError(f"stream error: {json.dumps(ev.get('error'))[:200]}")
    return reply

show_def(parse_sse)
RECORDED = [
    'event: message_start',
    'data: {"type":"message_start","message":{"usage":{"input_tokens":64,"output_tokens":1}}}',
    'data: {"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"The user wants one word."}}',
    'event: ping',
    'data: {"type":"ping"}',
    'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"O"}}',
    'data: {"type":"content_block_delta","index":1,"delta":{"type":"text_delta","text":"K"}}',
    'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":14}}',
    'data: {"type":"message_stop"}',
]
r = parse_sse(RECORDED, "demo")
print(f"[sse] {len(RECORDED)} lines -> text {r.text!r}, reasoning {r.reasoning!r}, finish {r.finish}, "
      f"tokens {r.prompt_tokens}+{r.completion_tokens}")

#%% md
**The failure policy as a table.** **`classify_error(status, body)`** maps an HTTP status and the start of the error body to one action. The rows below are the error shapes the provider documents: a rate limit, an overloaded server, spent credit, a bad request, a wrong key.

#%% code
class OutOfCredit(RuntimeError):
    """The account's credit is spent; retrying would only fail again."""


class AccessDenied(RuntimeError):
    """The key is missing, wrong, or not allowed to use this model."""


def classify_error(status, body):
    """retry, throttled, out of credit, denied or keep (a deterministic rejection worth storing)."""
    low = body.lower()
    if "credit balance" in low or "billing" in low:
        return "out of credit"
    if status == 429:
        return "throttled"
    if status in (401, 403):
        return "denied"
    if status in (400, 404, 413, 422):
        return "keep"
    return "retry"                                     # 408, 409, 500, 502, 503, 504, 529 and anything unexpected

show_def(OutOfCredit, AccessDenied, classify_error)
POLICY_CASES = [(429, '{"type":"error","error":{"type":"rate_limit_error","message":"Number of request tokens has exceeded your rate limit"}}'),
                (529, '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}'),
                (400, '{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low to access the API"}}'),
                (400, '{"type":"error","error":{"type":"invalid_request_error","message":"max_tokens: must be at most 64000"}}'),
                (401, '{"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}}'),
                (502, 'Bad Gateway')]
table([{"status": s, "body": b[:62], "action": classify_error(s, b)} for s, b in POLICY_CASES],
      [("status", "status", "d"), ("body", "start of the body", ""), ("action", "action", "")])

#%% md
### A server we control

**Theory.** A client that talks to a paid service is hard to test, because the failures you most need to test are the ones you cannot order on demand: a rate limit, a model still loading, a stream that stalls halfway. So before the client meets the real service, it meets **`FakeModelServer`**: a tiny server running inside the notebook on `127.0.0.1` that speaks the provider's protocol. It speaks the same streaming protocol and sends the same quota headers. It fails on command, when a message contains a marker such as `[503 once]` or `[slow]`. It also has a **capacity**: when more calls are in flight than it allows, it answers 429 with a rate-limit error of the real shape. Everything in this section and in S10 runs against it, over real HTTP, for free.

**In plain terms.** We build a pretend model server that we can break on purpose, and make sure the client copes with every way it breaks.

#%% code
import http.server
import socketserver


class FakeModelServer:
    """A local streaming server in the provider's protocol, with a capacity, quota headers and failures on demand."""

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
**`FakeModelServer.handle`** decides what one request gets. It checks the capacity first, exactly as a busy real server would, and then looks for a failure marker in the last message. Only a request with no marker gets a normal streamed answer: a sentence of reasoning, then the reply in small pieces, then the token counts. When the system prompt asks for a JSON object only, the reply is a small JSON object. The server counts how often it has served each text: `[503 once]` fails only the first time, and when a `delay_fn` sets the latency, a repeated request gets a fresh draw instead of the same delay again, which is how a real server behaves when a request is retried.

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
        return self.error(h, 429, '{"type":"error","error":{"type":"rate_limit_error","message":"rate limit exceeded"}}')
    try:
        if "[balance]" in text:
            return self.error(h, 400, '{"type":"error","error":{"type":"invalid_request_error","message":"Your credit balance is too low"}}')
        if "[bad]" in text:
            return self.error(h, 400, '{"type":"error","error":{"type":"invalid_request_error","message":"invalid parameter"}}')
        if "[503 once]" in text and n == 0:
            self.rejected["503 once"] += 1
            return self.error(h, 529, '{"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}')
        if JSON_ONLY in body.get("system", ""):
            answer = json.dumps(self.json_fn(body) if self.json_fn else {"answer": "ok", "echo": text[-20:]})
        else:
            answer = "OK. " + text[-40:]
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("anthropic-ratelimit-requests-remaining", str(self.remaining))
        h.send_header("anthropic-ratelimit-tokens-remaining", str(self.remaining * 400))
        h.end_headers()
        events = [{"type": "message_start", "message": {"usage": {"input_tokens": len(text) // 4, "output_tokens": 1}}},
                  {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Let me think about this."}}]
        step = max(1, len(answer) // self.chunks)
        events += [{"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": answer[i:i + step]}}
                   for i in range(0, len(answer), step)]
        events += [{"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": len(answer) // 4 + 6}},
                   {"type": "message_stop"}]
        if self.delay_fn:                         # a repeat gets a fresh draw, as a retry to a real server would
            total = self.delay_fn(text if n == 0 else f"{text}#{n}")
        else:
            total = self.latency * (8 if "[slow]" in text else 1) * len(events)
        for ev in events:
            time.sleep(total / len(events))                 # the reply trickles in over the whole delay
            h.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
            h.wfile.flush()
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
    """Streaming model calls over HTTP with only the standard library."""

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
**`to_request(model, messages, params)`** writes the request body. The rest of the notebook speaks one small dialect: a list of messages that may start with a system message, and a few parameters. `max_tokens` bounds the answer. `enable_thinking=False` asks for no thinking, which each model switches off in its own way, and the newest larger models cannot switch it off at all, only turn it down. `response_format` asks for a JSON object, which this provider gets as a sentence in the system prompt. `temperature` goes only to the models that still accept it, and `top_p` to none, since those models take one or the other. Thinking effort is set per model in `EFFORT`: the lead thinks at medium effort, enough for planning and much cheaper than its default. Keeping this translation in one function is what lets the same engine move to another provider by changing one function and the model table.

#%% code
JSON_ONLY = "Answer with one JSON object and nothing else: no code fences, no text before or after it."
NO_SAMPLING = ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-sonnet-5", "claude-opus-5-5")   # these reject temperature and top_p
NO_DISABLE = {"claude-sonnet-5-5": {"type": "between_tools"}, "claude-opus-5-5": None}          # their way of thinking less
EFFORT = {"claude-sonnet-5-5": "medium"}        # how hard a model thinks when thinking is on; the rest keep their default


def to_request(model, messages, params):
    """The provider's request body for one call in the notebook's own dialect."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    if params.get("response_format"):
        system = (system + "\n\n" + JSON_ONLY).strip()
    body = {"model": model, "max_tokens": int(params.get("max_tokens", 8000)), "stream": True,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages if m["role"] != "system"]}
    if system:
        body["system"] = system
    if params.get("enable_thinking") is False:
        if model in NO_DISABLE:
            if NO_DISABLE[model]:
                body["thinking"] = NO_DISABLE[model]
            else:
                body["output_config"] = {"effort": "low"}
        elif model.startswith("claude-haiku-5") or model.startswith("claude-sonnet-5"):
            body["thinking"] = {"type": "disabled"}
    if model not in NO_SAMPLING and "temperature" in params:
        body["temperature"] = params["temperature"]      # older models take one of temperature and top_p, not both
    if model in EFFORT and "output_config" not in body and body.get("thinking", {}).get("type") != "between_tools":
        body["output_config"] = {"effort": EFFORT[model]}
    if len(body["messages"]) > 2:                      # a growing conversation: let the server cache what it has seen
        body["cache_control"] = {"type": "ephemeral"}
    return body


def json_only(text):
    """The JSON object in a reply, without the fences or remarks a model sometimes adds around it."""
    a, b = text.find("{"), text.rfind("}")
    return text[a:b + 1] if 0 <= a < b else text

show_def(to_request, json_only)
demo_body = to_request(MODELS["fast"], [{"role": "system", "content": "You tag messages."}, {"role": "user", "content": "hello"}],
                       {"max_tokens": 500, "temperature": 0.6, "enable_thinking": False, "response_format": {"type": "json_object"}})
print(f"[request] {json.dumps({k: v for k, v in demo_body.items() if k != 'system'})}")
print(f"[request] system prompt: {demo_body['system']!r}")
print(f"[request] {json_only('Here it is: ```json {\"a\": 1} ```')!r} is what json_only keeps of a fenced reply")

#%% md
**`ModelClient._stream`** makes one attempt. It sends the request, records the quota headers, and reads the stream line by line, checking the deadline on every line rather than only at the end, so a stream that trickles forever is still cut off on time.

#%% code
QUOTA_PREFIX = "anthropic-ratelimit-"
API_VERSION = "2023-06-01"


@method_of(ModelClient)
def _stream(self, body, deadline):
    req = urllib.request.Request(f"{self.endpoint}/messages", data=json.dumps(body).encode(),
                                 headers={"x-api-key": self.key, "anthropic-version": API_VERSION, "content-type": "application/json"})
    start = time.perf_counter()
    lines, first = [], None
    with urllib.request.urlopen(req, timeout=min(60, deadline)) as resp:
        quota = {k[len(QUOTA_PREFIX):]: v for k, v in resp.headers.items() if k.lower().startswith(QUOTA_PREFIX)}
        for raw in resp:
            if first is None:
                first = time.perf_counter() - start
            if time.perf_counter() - start > deadline:
                raise TimeoutError(f"the call ran past its {deadline}s deadline")
            lines.append(raw.decode("utf-8"))
    reply = parse_sse(lines, body["model"])
    reply.seconds, reply.first_byte, reply.quota = time.perf_counter() - start, first, quota
    return reply

show_def(ModelClient._stream)

#%% md
**`ModelClient.chat`** is the retry loop. Each attempt holds a gate slot only while it is talking to the server; the wait between attempts happens outside the slot, so a sleeping retry never blocks another call. The wait grows with each attempt (1, 2, 4, 8 seconds, at most 30) and is multiplied by a random factor between 0.5 and 1. That jitter matters as soon as calls run in parallel: without it, every call that failed together would retry together and fail together again.

#%% code
import http.client

RETRYABLE = (urllib.error.URLError, TimeoutError, ConnectionError, OSError, json.JSONDecodeError,
             http.client.HTTPException, UnicodeDecodeError)


@method_of(ModelClient)
def chat(self, model, messages, **params):
    body = to_request(model, messages, params)
    deadline = CALL_DEADLINE_S.get(model, CALL_DEADLINE_S["default"])
    if time.time() < self.open_until.get(model, 0):
        return Reply(model=model, finish="error", error="circuit open after repeated failures")
    gate, last, attempt = self.gate(model), None, 0
    while attempt < self.max_attempts and not self.stop.is_set():
        attempt += 1
        with gate.slot():
            try:
                reply = self._stream(body, deadline)
                if params.get("response_format"):
                    reply.text = json_only(reply.text)
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
                if action == "out of credit":
                    raise OutOfCredit(scrub(text))
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
test_client = ModelClient("sk-ant-test-key-not-real-000000", endpoint=FAKE.endpoint, gate_factory=lambda m: FixedGate(2))
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
except OutOfCredit:
    balance_raised = True
for name, rr in [("ordinary", r_ok), ("json mode", r_json), ("529 once", r_503), ("bad request", r_bad), ("too slow", r_slow)]:
    print(f"  {name:<12} finish {str(rr.finish):<6} attempts {rr.attempts}  text {rr.text[:34]!r:<38} "
          f"error {str(rr.error)[:44]!r}  quota {rr.quota}")
results = []
expect("an ordinary call streams text and reasoning", r_ok.text.startswith("OK") and r_ok.reasoning and r_ok.finish == "stop")
expect("token counts arrive from the final event", r_ok.prompt_tokens > 0 and r_ok.completion_tokens > 0)
expect("quota headers are recorded", "requests-remaining" in r_ok.quota)
expect("JSON mode returns parseable JSON", json.loads(r_json.text)["answer"] == "ok")
expect("an overloaded server (529) is retried and then succeeds", r_503.finish == "stop" and r_503.attempts == 2)
expect("a 400 is not retried and is kept as an error", r_bad.finish == "error" and r_bad.attempts == 1 and "400" in r_bad.error)
expect("a stream past its deadline is cut off and retried, then reported", r_slow.finish == "error" and "deadline" in r_slow.error)
expect("spent credit stops at once", balance_raised)

#%% md
## S7 - What the server says about our quota

Every answer from the provider carries headers that begin with `anthropic-ratelimit-`: how many requests and tokens the account may still send in the current minute, and when that allowance resets. The client stores them on the `Reply`. They do not change any decision on their own, but they are the earliest warning that a long experiment is about to run out of quota, so the status line in S27 shows them, and the accounts in S71 keep them.

#%% code
def quota_line(reply):
    """The quota headers of one reply as a short line."""
    if not reply.quota:
        return "no quota headers (smoke or replay)"
    return ", ".join(f"{k.replace('requests-remaining', 'left')}: {v}" for k, v in sorted(reply.quota.items()))

show_def(quota_line)
print(f"[quota] {quota_line(r_ok)}")
