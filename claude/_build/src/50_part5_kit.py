#%% md
# Part V. The lead writes the plan

**Where this sits.** Part III showed one agent stalling on a job too big for it, and a lead that supervised helpers one at a time and spent most of its life waiting. Part IV built a runtime that runs many workers at once, in phases, under one budget, and can be watched, paused and resumed. But every plan in Part IV was a Python function that a person wrote. This Part hands the pen to the lead. It reads a short summary of the job, writes a plan, the plan is checked and priced before a single paid call is made, and then it runs in the background while the lead waits for one combined result.

The plan comes in two forms, in this order. First as **data**: a small JSON document with phases and settings, which our own compiler turns into runtime calls. Then, after measuring what data cannot say, as a **program**: a few lines of restricted Python that call the runtime's primitives directly.

**By the end of this Part you can**

- describe a job as a **kit** of steps a plan can use, and test every step alone;
- write a plan as JSON, validate it, compile it and run it, and use it as the fixed baseline the dynamic plans must beat;
- give a lead a cheap, exact summary of the work instead of the work itself;
- say, with a measurement, what a JSON plan cannot express;
- check a model-written plan program against a whitelist, dry-run it for free, estimate its cost and hold it for approval;
- run the lead's own plan end to end and read the memo it writes about the result.

![part5](attachment:part5_map.png)

#%% md
## S31 - The task kit: what a plan is allowed to talk about

**Theory.** A plan says who does what, in which order, and with how many workers. The *what* is specific to the job: where the work items come from, how they are cut into pieces, which instruction a worker gets, and how a claim is checked. We collect these job-specific pieces in a **kit**. The runtime of Part IV knows nothing about bugs or code; the kit knows nothing about threads or budgets. A plan is written in the words of both: the runtime's primitives (`agent`, `parallel`, `pipeline`, `phase`, `log`) and the kit's steps.

The kit for the audit has four kinds of pieces:

- **data**: `work`, the files to audit, and `shards(tokens)`, the same files packed into pieces of a chosen size;
- **finder steps**: `scan(shard, lens)`, one worker reading one shard through one **lens**, a paragraph that points it at one family of mistakes;
- **checker steps**: `evidence(finding)`, which runs the finding's failing call in the sandbox of S15, and `check(batch)`, a **skeptic** worker that tries to refute a batch of findings with that evidence in front of it;
- **helpers**: `dedupe`, `vote` and `report`, which merge, decide and write up.

Every step is tested alone in this section, on real code, before any plan uses it. Part VI then measures, one feature at a time, whether each step earns its calls.

**In plain terms.** Before anyone can write a plan, we have to agree on the words it can use. The kit is that vocabulary for this one job.

**For teams.** Keep the job-specific code in one small module with a test per step, and keep the runtime generic. A new job then costs a new kit, not a new engine. Part VIII builds two more kits on the same runtime.

#%% md
**Lenses.** A lens is one extra paragraph appended to the scan instruction of S13. Each lens names one family of mistakes and tells the worker where to look. Twelve kinds of bug were planted in S2, and each lens is aimed at four of them, so three workers with three lenses together point at all twelve. Whether three narrow readings find more than three general ones is a question for Part VI; here we only define them.

#%% code
LENSES = ["boundaries", "logic", "state"]
LENS_TEXT.update({
    "boundaries": ("Read this code for boundary mistakes. Check every comparison (< against <=, > against >=), every range and "
                   "slice end, every index at the start or end of a sequence (0, -1, len - 1), and what happens with an empty "
                   "input or a single element. Bugs of this kind are usually off by exactly one."),
    "logic": ("Read this code for logic mistakes. Check every arithmetic and boolean operator (+ against -, and against or), "
              "every condition that may have lost or gained a not, and every call whose arguments may be in the wrong order."),
    "state": ("Read this code for state mistakes. Check the starting value of every counter, accumulator and best-so-far "
              "variable, every update such as += or -=, every early return and base case of a recursion, and whether the "
              "function returns the variable it should."),
})
LENS_FAMILY = {"boundaries": ["flip comparison", "off-by-one range", "off-by-one slice", "wrong index"],
               "logic": ["swap + and -", "swap and / or", "drop not", "swap arguments"],
               "state": ["wrong start value", "change update", "remove early return", "wrong return value"]}
PLANTED_KINDS = sorted({b["operator"] for b in ANSWER_KEY})
aimed = collections.Counter(op for ops in LENS_FAMILY.values() for op in ops)
for lens in LENSES:
    print(f"[lens] {lens:<10} {len(LENS_TEXT[lens].split()):>3} words, aimed at: {', '.join(LENS_FAMILY[lens])}")
print(f"[lens] the three lenses cover {len(aimed)} of {len(PLANTED_KINDS)} planted kinds, each exactly once: {set(aimed.values()) == {1}}")

#%% md
**The data steps.** `work` is the sorted list of audited files. `shards(tokens)` packs them with the packer of S13 and caches the result, because a plan may ask for the same shards several times. `batches(items, size)` cuts a list into groups, and `flatten(lists)` joins the answers of a parallel phase into one list, skipping workers that returned nothing. These four are pure functions: same input, same output, no calls.

#%% code
WORK = sorted(CORPUS)
_SHARD_CACHE = {}


def shards(tokens=None):
    """Whole files packed into shards of about `tokens` tokens (the packer of S13); default SHARD_TOKENS."""
    tokens = int(tokens or SHARD_TOKENS)
    if tokens not in _SHARD_CACHE:
        _SHARD_CACHE[tokens] = pack(WORK, tokens)
    return [list(s) for s in _SHARD_CACHE[tokens]]


def batches(items, size):
    """Consecutive groups of at most `size` items."""
    items, size = list(items), max(1, int(size))
    return [items[i:i + size] for i in range(0, len(items), size)]


def flatten(lists):
    """One list from a list of lists; None entries, from workers that failed, are skipped."""
    return [x for xs in lists if xs for x in xs]

show_def(shards, batches, flatten)
for t in (20_000, SHARD_TOKENS, 100_000):
    sh = shards(t)
    print(f"[shards] {t // 1000:>3}k tokens: {len(sh):>3} shards, {min(len(s) for s in sh)} to {max(len(s) for s in sh)} files each")
print(f"[batches] 14 items in groups of 6: {[len(b) for b in batches(range(14), 6)]}; flatten([[1, 2], None, [3]]) = {flatten([[1, 2], None, [3]])}")

#%% md
**Findings as plain dictionaries.** Plans pass findings around, and a plan program (S36) may read a finding's fields but not call methods on objects. So inside plans a finding is a plain `dict`. **`finding(obj)`** turns one item of a scan worker's JSON into that dict. It cleans the path, keeps the line, and looks up the function that really contains that line in the audited file, because a model sometimes names the function it was thinking about rather than the one the line is in.

**`key_of(f)`** names the place a finding is about: the file and the function, or for a line outside any function, the file and a ten-line block. Two findings with the same key are about the same place. One bug per function is the unit this audit reports in, and the scorer of S4 counts the same way. **`dedupe(findings)`** keeps one finding per key, the most confident one, and records how many workers reported that place. Ties are broken by the findings' content, never by their order: workers finish in a different order on every run, and the result must not depend on it. That count is a signal in its own right: a place reported by three independent workers is more likely real.

#%% code
def finding(obj, source=""):
    """A plain dict from one item of a scan answer: clean path, true enclosing function, bounded text."""
    path = normalise_path(obj.get("file", ""))
    try:
        line = int(obj.get("line") or 0)
    except (TypeError, ValueError):
        line = 0
    conf = obj.get("confidence", 0.5)
    conf = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else 0.5
    return {"file": path, "line": line, "function": (function_at(path, line) if path in CORPUS else None) or str(obj.get("function") or ""),
            "claim": str(obj.get("claim") or "")[:400], "failing_call": str(obj.get("failing_call") or "")[:400],
            "expected": str(obj.get("expected") if obj.get("expected") is not None else "")[:200],
            "confidence": min(1.0, max(0.0, conf)), "source": source}


def key_of(f):
    """The place a finding is about: file and function, or file and a ten-line block outside any function."""
    return f"{f['file']}::{f['function']}" if f.get("function") else f"{f['file']}::line {int(f.get('line') or 0) // 10 * 10}"


def dedupe(findings):
    """One finding per place, the most confident, with `reports` = how many findings named that place. Sorted by place."""
    groups = collections.defaultdict(list)
    for f in findings:
        if f and f.get("file"):
            groups[key_of(f)].append(f)
    out = []
    for k in sorted(groups):
        best = dict(max(groups[k], key=lambda f: (f.get("confidence", 0), -f.get("line", 0), f.get("claim", ""),
                                                  f.get("failing_call", ""), f.get("source", ""))))   # ties broken by content, not order
        best["reports"] = sum(g.get("reports", 1) for g in groups[k])
        out.append(best)
    return out

show_def(finding, key_of, dedupe)
b0 = ANSWER_KEY[0]
demo_found = [finding({"file": "./" + b0["path"], "line": b0["line"], "function": "a_wrong_name", "claim": "x", "confidence": 0.6}, "w1"),
              finding({"file": b0["path"], "line": b0["line"] + 2, "claim": "y", "confidence": 0.9}, "w2"),
              finding({"file": WORK[3], "line": 7, "claim": "z", "confidence": "high"}, "w3")]
for f in demo_found:
    print(f"[finding] {key_of(f):<55} line {f['line']:>4}  confidence {f['confidence']}  from {f['source']}")
print(f"[dedupe] {len(demo_found)} findings -> {len(dedupe(demo_found))} places: " +
      "; ".join(f"{key_of(f)} reported {f['reports']}x" for f in dedupe(demo_found)))

#%% md
**Evidence: run the call, then argue.** Every scan worker must give a failing call and the value it expects (S13). That makes a finding testable. **`evidence(f)`** checks the call with the fence of S15 (one call to a function in that file, literal arguments only), runs it in the sandbox against the audited code, and compares the result with what the finder expected. The comparison is literal where it can be: both sides are parsed as Python values and numbers are compared with a small tolerance. Results are cached, because three skeptics looking at the same finding need the same run only once.

Evidence is not a verdict. A finder can expect the wrong value, and a call can raise for a reason that has nothing to do with the claimed bug. But a skeptic that sees *"returned -1; the finder expected 2"* no longer has to simulate the code in its head, and Part VI measures how much that helps.

#%% code
def same_value(got, expected):
    """Compare a repr from the sandbox with a value a model wrote: True, False, or None when they cannot be compared."""
    def close(a, b):
        if isinstance(a, bool) or isinstance(b, bool):           # True is not 1, as a doctest would also say
            return isinstance(a, bool) and isinstance(b, bool) and a == b
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)
        if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
            return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
        if isinstance(a, dict) and isinstance(b, dict):
            return a.keys() == b.keys() and all(close(a[k], b[k]) for k in a)
        return a == b
    exp = (expected or "").strip()
    if not exp:
        return None
    try:
        return close(ast.literal_eval(got), ast.literal_eval(exp))
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return got.strip().strip("'\"") == exp.strip("'\"")


_EVIDENCE = {}


def evidence(f):
    """Run a finding's failing call in the sandbox; {call, status, got, text}. status: differs, agrees, raised, not run."""
    call = (f.get("failing_call") or "").strip()
    if not call:
        return {"call": "", "status": "not run", "got": "", "text": "no failing call was given"}
    k = (f["file"], call, f.get("expected", ""))
    if k not in _EVIDENCE:
        out = run_call(f["file"], call) if f["file"] in CORPUS else {"ok": False, "error": "rejected: no such file in the library"}
        if not out["ok"]:
            raised = not out["error"].startswith(("rejected", "timeout"))
            text = f"raised {out['error']}" if raised else f"could not run it: {out['error']}"
            _EVIDENCE[k] = {"call": call, "status": "raised" if raised else "not run", "got": out["error"], "text": text}
        else:
            same = same_value(out["value"], f.get("expected", ""))
            status = "agrees" if same else "differs"
            text = (f"returned {out['value']}" + ("" if not f.get("expected") else
                    ", which is what the finder expected" if same else f"; the finder expected {f['expected']}"))
            _EVIDENCE[k] = {"call": call, "status": status, "got": out["value"], "text": text}
    return dict(_EVIDENCE[k])

show_def(same_value, evidence)
for got, exp in (("2", "2.0000001"), ("[1, 2]", "[1, 2]"), ("'abc'", "abc"), ("-1", "2"), ("True", "1"), ("None", "")):
    print(f"[same] got {got:<8} expected {exp!r:<12} -> {same_value(got, exp)}")

#%% md
**Evidence on a real planted bug, and on a correct function.** For the first finding we take a planted bug and one of its *hidden* examples, the ones that fail on the audited code, and write it the way a good finder would: the call, and the value the original code returns. For the second we take a function with no bug and a call whose expected value is right. The sandbox tells the two apart without any model.

#%% code
def callable_example(path, examples):
    """The first (source, want) whose source is one call the fence of S15 accepts and whose want is a Python literal."""
    names = module_names(path)
    for src, want in examples:
        src, want = src.strip(), want.strip()
        try:
            check_call(src, names)
            ast.literal_eval(want)
        except (CallRejected, SyntaxError, ValueError, TypeError):
            continue
        return src, want
    return None


def visible_examples(path):
    """(source, want) of every doctest example still visible in an audited file."""
    tree = ast.parse((AUDITED / path).read_text(encoding="utf-8"))
    return [(ex.source, ex.want) for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))
            for ex in doctest.DocTestParser().get_examples(ast.get_docstring(node) or "")]

show_def(callable_example, visible_examples)
hb, (hb_call, hb_want) = next((b, ce) for b in ANSWER_KEY
                              for ce in [callable_example(b["path"], [(h["source"], h["want"]) for h in b["hidden"]])] if ce)
good_finding = finding({"file": hb["path"], "line": hb["line"], "claim": f"{hb['operator']} on line {hb['line']}",
                        "failing_call": hb_call, "expected": hb_want}, "demo")
planted_paths = {b["path"] for b in ANSWER_KEY}
clean_path, (cl_call, cl_want) = next((p, ce) for p in WORK if p not in planted_paths
                                      for ce in [callable_example(p, visible_examples(p))] if ce)
wrong_finding = finding({"file": clean_path, "line": 1, "claim": "returns the wrong value", "failing_call": cl_call,
                         "expected": cl_want}, "demo")
EV_GOOD, EV_WRONG = evidence(good_finding), evidence(wrong_finding)
print(f"[evidence] planted bug {hb['id']} in {hb['path']}:\n  call {EV_GOOD['call']}\n  {EV_GOOD['text']}  -> {EV_GOOD['status']}")
print(f"[evidence] a correct function in {clean_path}:\n  call {EV_WRONG['call']}\n  {EV_WRONG['text']}  -> {EV_WRONG['status']}")
t0 = time.perf_counter()
evidence(good_finding)
print(f"[evidence] asked again: answered from the cache in {1000 * (time.perf_counter() - t0):.2f} ms")

#%% md
**The skeptic.** A skeptic gets up to six findings, each with the numbered code of the function it is about, the claim, the failing call, the value the finder expected and, when evidence is switched on, what the sandbox saw. Its instruction tells it that most findings it sees are wrong, and that when it cannot confirm a bug it must say *not real*. That default matters: a checker that confirms what it cannot refute adds calls without adding precision. Several skeptics with different sample indexes look at the same batch independently, and **`vote`** keeps a finding when enough of them call it real.

![verify](attachment:verify.png)

#%% code
SKEPTIC_SYSTEM = """You check bug reports about Python code. Each report claims that one line makes a function return a wrong result, or crash, for an input its docstring allows.

Most reports you will see are false alarms. Try to refute each one. A report is real only if the code, exactly as shown, gives a wrong result or crashes for an input the function is meant to handle. Style, speed, naming and missing input validation are never real bugs. When a report says what happened when we ran its failing call, use that: it is what the code really did. But the finder's expected value can itself be wrong, so check it against the function's docstring and logic. When you are unsure, answer real: false.

Answer with one JSON object and nothing else: {"verdicts": [{"report": <number>, "real": true or false, "reason": "<one sentence>"}]}, one verdict per report."""

VERDICTS_SCHEMA = {"type": "object", "required": ["verdicts"], "properties": {"verdicts": {"type": "array", "items": {
    "type": "object", "required": ["report", "real"],
    "properties": {"report": {"type": "integer"}, "real": {"type": "boolean"}, "reason": {"type": "string"}}}}}}


def function_text(path, line, around=30):
    """The numbered lines of the function containing `line` in the audited file; a window if it is long or missing."""
    lines = (AUDITED / path).read_text(encoding="utf-8").splitlines() if path in CORPUS else []
    if not lines:
        return "(no such file)"
    span = next(((a, b) for a, b, name in AUDITED_SPANS.get(path, []) if a <= line <= b and name == function_at(path, line)), None)
    a, b = span if span and span[1] - span[0] <= 2 * around else (max(1, line - around // 2), min(len(lines), line + around // 2))
    return "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(a, b + 1))


def render_candidates(batch, with_evidence=True):
    """The text a skeptic reads: one numbered block per finding."""
    out = []
    for i, f in enumerate(batch, 1):
        ev = evidence(f) if with_evidence else None
        out.append(f"--- report {i} ---\nfile: {f['file']}\nfunction: {f['function'] or '(none)'}\nline: {f['line']}\n"
                   f"claim: {f['claim']}\nfailing call: {f['failing_call'] or '(none given)'}\n"
                   f"expected by the finder: {f['expected'] or '(not given)'}\n"
                   + (f"what happened when we ran it: {ev['text']}\n" if ev else "")
                   + f"code:\n{function_text(f['file'], f['line'])}")
    return "\n\n".join(out)

show_def(function_text, render_candidates)
demo_text = render_candidates([good_finding])
print(f"[skeptic] instruction {len(SKEPTIC_SYSTEM.split())} words; one report renders as {len(demo_text):,} characters:\n")
print(demo_text[:1600])

#%% md
**The report.** At the end, one worker reads every confirmed finding in a compact form and writes the report: findings that describe the same defect in the same function are grouped, each group gets a severity and a title, and the report says which parts of the work it could not cover. It answers with *ids*, not with copies of the findings, so the report stays short however many findings there are. A confirmed finding the report forgets to mention is not dropped: it is added back on its own, and the number of such additions is recorded. And a group that spans several functions is split back into one bug per function: an early live run showed a model grouping dozens of different bugs under one heading such as "returns the wrong variable", which would have thrown away every bug but the first. A summary step that can silently lose findings would be a silent cap of exactly the kind S29 forbids.

#%% code
REPORT_SYSTEM = """You write the final report of a code audit. You get the findings that independent checkers confirmed, one per line, each with an id.

Group findings only when they describe the same defect in the same function, for example two readers reporting one wrong comparison. Findings in different functions are always different bugs, even when the mistake is of the same kind; never group by kind of mistake. Give each group a severity (high: wrong results for ordinary inputs; medium: wrong results at the edges; low: crashes or wrong results only for unusual inputs) and a short title. Mention every id exactly once. Then list anything the audit clearly did not cover, and write a two-sentence summary.

Answer with one JSON object and nothing else: {"bugs": [{"ids": ["C1", "C4"], "severity": "high", "title": "..."}], "not_covered": ["..."], "summary": "..."}."""

REPORT_SCHEMA = {"type": "object", "required": ["bugs", "summary"], "properties": {
    "bugs": {"type": "array", "items": {"type": "object", "required": ["ids"], "properties": {
        "ids": {"type": "array", "items": {"type": "string"}}, "severity": {"enum": ["high", "medium", "low"]},
        "title": {"type": "string"}}}},
    "not_covered": {"type": "array", "items": {"type": "string"}}, "summary": {"type": "string"}}}


def compact_findings(confirmed):
    """One line per confirmed finding, with an id the report can refer to."""
    return "\n".join(f"C{i} | {f['file']}:{f['line']} | {f['function'] or '-'} | {f.get('votes', '?')} votes | {f['claim'][:160]}"
                     for i, f in enumerate(confirmed, 1))

show_def(compact_findings)
print(f"[report] instruction {len(REPORT_SYSTEM.split())} words; a confirmed finding takes about "
      f"{est_tokens(compact_findings([dict(good_finding, votes=3)]))} tokens in the report's input")

#%% md
**Stand-ins for the smoke run.** In smoke mode no model is called, so two more responders join the scripted model of S9. The skeptic responder cheats like the scanner of S13: it reads the answer key, calls a planted bug real most of the time and a false alarm real now and then, and is right more often when the evidence line is present. The report responder groups the findings by function and ranks them by votes. And the scanner of S13 learns to write a failing call: for a planted bug, one of its hidden examples; for a false alarm, a visible example of the same file, so that the evidence path runs too. The shapes are invented and no number from them is quoted. They exist so that every line of every plan below runs in a smoke build. Independent skeptics get independent answers because the scripted model receives each call's sample index (S9).

#%% code
@SCRIPTED.register
def _skeptic(model, messages, params):
    if not messages[0]["content"].startswith("You check bug reports"):
        return None
    text = messages[-1]["content"]
    if text.startswith("Your answer does not match"):
        return '{"verdicts": []}'
    out = []
    for m in re.finditer(r"--- report (\d+) ---\nfile: (\S+)\n.*?\nline: (\d+)\n(.*?)(?=\n--- report |\Z)", text, re.S):
        n, path, line, rest = int(m.group(1)), m.group(2), int(m.group(3)), m.group(4)
        planted = any(b["path"] == path and abs(b["line"] - line) <= 5 for b in ANSWER_KEY)
        accuracy = 0.92 if "what happened when we ran it" in rest else 0.82
        draw = zlib.crc32(f"{path}:{line}:{params.get('sample', 0)}".encode()) % 1000 / 1000
        real = planted if draw < accuracy else not planted
        out.append({"report": n, "real": real, "reason": "the line does what the claim says" if real else "the code is correct here"})
    return json.dumps({"verdicts": out})


@SCRIPTED.register
def _report(model, messages, params):
    if not messages[0]["content"].startswith("You write the final report"):
        return None
    rows = re.findall(r"^(C\d+) \| ([^:|]+):(\d+) \| ([^|]*) \|", messages[-1]["content"], re.M)
    groups = collections.defaultdict(list)
    for cid, path, line, fn in rows:
        groups[(path.strip(), fn.strip())].append(cid)
    bugs = [{"ids": ids, "severity": "medium", "title": f"bug in {fn} ({path})"} for (path, fn), ids in groups.items()]
    return json.dumps({"bugs": bugs, "not_covered": [], "summary": f"{len(bugs)} distinct bugs confirmed."})



@SCRIPTED.register
def _scan_with_calls(model, messages, params):
    text = _scan(model, messages, params)                  # the scripted scanner of S13; None for anything that is not a scan
    if text is None:
        return None
    obj = json.loads(text)
    for f in [f for f in obj["findings"] if not f.get("failing_call")]:
        b = next((b for b in ANSWER_KEY if b["path"] == f["file"] and abs(b["line"] - f["line"]) <= 5), None)
        if f["file"] not in CORPUS:
            continue
        ce = callable_example(f["file"], [(h["source"], h["want"]) for h in b["hidden"]] if b else visible_examples(f["file"]))
        if ce:
            agrees = zlib.crc32(f"{f['file']}:{f['line']}".encode()) % 2 == 0      # half the false alarms bring a call that agrees
            f["failing_call"], f["expected"] = ce[0], (ce[1] if b or agrees else "None")
    return json.dumps(obj)

show_def(_skeptic, _report, _scan_with_calls)

#%% md
**`AuditKit`: the steps, bound to one run.** The kit object holds the run it works for and a **sample offset**. Run number *r* of the same plan adds 100 × *r* to every sample index it uses, so three runs of one plan are three independent looks, while a plan run twice with the same offset asks exactly the same questions and is answered from the ledger. The kit also keeps a **trace**: every shard scanned, every finding, every verdict, every confirmed finding and the final report. Part VII reads these traces to explain, bug by bug, why a planted bug was missed.

#%% code
class AuditKit:
    """The audit's vocabulary for plans: data, steps and helpers, bound to one run, with a trace of everything."""
    STRIDE = 100                       # run r uses sample indexes 100 r, 100 r + 1, ...

    def __init__(self, run, number=0, with_evidence=True):
        self.run, self.offset, self.with_evidence = run, self.STRIDE * number, with_evidence
        self.trace = {"scanned": [], "found": [], "checked": [], "confirmed": [], "reported": [], "left_out": 0}
        self.lock = threading.Lock()

    def note(self, what, items):
        with self.lock:
            self.trace[what].extend(items)

show_def(AuditKit)

#%% md
**`AuditKit.scan(shard, lens)`** runs one scan worker: the S13 instruction plus the lens, the shard rendered with line numbers, the findings schema. It returns a list of finding dicts, empty if the worker failed. **`AuditKit.check(batch)`** runs one skeptic on up to six findings and returns one verdict per finding, with `real` set to `None` where the skeptic gave no verdict.

#%% code
@method_of(AuditKit)
def scan(self, shard, lens="general", sample=0, model="worker"):
    lens = lens if lens in LENS_TEXT else "general"
    label = f"scan:{lens}:{shard[0].split('/')[0]}#{sample}"
    obj = self.run.agent(**scan_task(shard, lens), schema=FINDINGS_SCHEMA, model=model, label=label, role="scan",
                         sample=self.offset + sample)
    found = [finding(f, label) for f in (obj or {}).get("findings", []) if isinstance(f, dict)]
    self.note("scanned", [(p, lens, sample) for p in shard])
    self.note("found", found)
    return found


@method_of(AuditKit)
def check(self, batch, sample=0, model="judge", with_evidence=None):
    batch = [f for f in batch if f][:8]
    if not batch:
        return []
    ev = self.with_evidence if with_evidence is None else with_evidence
    obj = self.run.agent(data=render_candidates(batch, ev), system=SKEPTIC_SYSTEM, schema=VERDICTS_SCHEMA, model=model,
                         label=f"check:{key_of(batch[0]).split('::')[0].split('/')[0]}#{sample}", role="skeptic",
                         sample=self.offset + sample)
    said = {v.get("report"): v for v in (obj or {}).get("verdicts", []) if isinstance(v, dict)}
    out = [{"key": key_of(f), "real": said.get(i, {}).get("real"), "reason": str(said.get(i, {}).get("reason", ""))[:200],
            "sample": sample} for i, f in enumerate(batch, 1)]
    self.note("checked", out)
    return out

show_def(AuditKit.scan, AuditKit.check)

#%% md
**`vote(candidates, verdicts, need)`** keeps the candidates with at least `need` verdicts of *real* and records the count on each. It is a pure function, so it lives outside the kit, and a plan can call it as often as it likes. **`AuditKit.report(confirmed)`** writes the final report and maps its ids back to findings. **`AuditKit.names()`** is the whole vocabulary a plan sees: the runtime's primitives bound to this run, and the kit's data, steps and helpers.

#%% code
def vote(candidates, verdicts, need=2):
    """Candidates with at least `need` real verdicts; each gets `votes`, the number of real verdicts."""
    real = collections.Counter(v["key"] for v in verdicts if v and v.get("real") is True)
    return [dict(c, votes=real[key_of(c)]) for c in candidates if real[key_of(c)] >= need]


@method_of(AuditKit)
def report(self, confirmed, model="lead"):
    confirmed = [f for f in confirmed if f]
    self.note("confirmed", confirmed)
    if not confirmed:
        return {"bugs": [], "not_covered": [], "summary": "No finding was confirmed.", "left_out": 0}
    obj = self.run.agent(data=compact_findings(confirmed), system=REPORT_SYSTEM, schema=REPORT_SCHEMA, model=model, label="report",
                         role="report", sample=self.offset) or {"bugs": [], "summary": "(the report worker failed)"}
    by_id = {f"C{i}": f for i, f in enumerate(confirmed, 1)}
    bugs, used = [], set()
    for g in obj.get("bugs", []):
        ids = [i for i in g.get("ids", []) if i in by_id and i not in used]
        used.update(ids)
        places = collections.defaultdict(list)          # a group that spans functions is split: one bug per function
        for i in ids:
            places[(by_id[i]["file"], by_id[i].get("function", ""))].append(i)
        for same in places.values():
            bugs.append(dict(by_id[same[0]], severity=g.get("severity", "medium"), title=str(g.get("title", ""))[:120], merged=same))
    left = [i for i in by_id if i not in used]
    bugs += [dict(by_id[i], severity="unranked", title=by_id[i]["claim"][:120], merged=[i]) for i in left]
    self.trace["left_out"] = len(left)
    self.note("reported", bugs)
    return {"bugs": bugs, "not_covered": obj.get("not_covered", []), "summary": str(obj.get("summary", ""))[:600],
            "left_out": len(left)}


@method_of(AuditKit)
def names(self):
    run, off = self.run, self.offset

    def agent(prompt="", **kw):
        kw["sample"] = off + int(kw.get("sample", 0))
        return run.agent(prompt, **kw)
    return {"agent": agent, "parallel": run.parallel, "pipeline": run.pipeline, "phase": run.phase, "log": run.log,
            "budget": lambda: budget_left(run.llm), "work": list(WORK), "shards": shards, "batches": batches, "flatten": flatten,
            "render": render_shard, "dedupe": dedupe, "key_of": key_of, "evidence": evidence, "scan": self.scan,
            "check": self.check, "vote": vote, "report": self.report, "LENSES": list(LENSES), "MODELS": sorted(MODELS),
            "SCHEMAS": {"findings": FINDINGS_SCHEMA, "verdicts": VERDICTS_SCHEMA}}


def budget_left(llm):
    """cents the session can still spend through this front door."""
    b = llm.budget
    return round(b.cap - b.spent - b.reserved, 2) if b is not None else round(CAP_CENTS - llm.ledger.spent(), 2)

show_def(vote, AuditKit.report, AuditKit.names, budget_left)

#%% md
**`AuditKit.save()`** writes the trace next to the run's events, and **`outcome(result, kit)`** scores a finished audit: the final report against the answer key, plus the same score at every earlier stage of the trace, so a loss can be placed where it happened.

#%% code
@method_of(AuditKit)
def save(self):
    d = RUNS_DIR / self.run.run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "trace.json").write_text(json.dumps(self.trace, default=str), encoding="utf-8")


def as_findings(dicts):
    """Finding objects for the scorer of S4."""
    return [Finding(file=f["file"], line=int(f.get("line") or 0), function=f.get("function", ""), claim=f.get("claim", ""),
                    failing_call=f.get("failing_call", ""), expected=f.get("expected", ""), source=f.get("source", "")) for f in dicts]


def outcome(result, kit):
    """Score of the final report, and recall at each earlier stage of the trace."""
    final = match(as_findings((result or {}).get("bugs", [])))
    scanned = {p for p, _, _ in kit.trace["scanned"]}
    found = match(as_findings(kit.trace["found"]))
    checked_keys = {v["key"] for v in kit.trace["checked"]}
    checked = match(as_findings([f for f in dedupe(kit.trace["found"]) if key_of(f) in checked_keys]))
    confirmed = match(as_findings(kit.trace["confirmed"]))
    run = kit.run
    return {"recall": final.recall, "precision": final.precision, "tp": final.tp, "fp": final.fp, "bugs_reported": len((result or {}).get("bugs", [])),
            "coverage": len(scanned) / len(WORK), "found_recall": found.recall, "checked_recall": checked.recall,
            "confirmed_recall": confirmed.recall, "findings": len(kit.trace["found"]), "checked": len(checked_keys),
            "confirmed": len(kit.trace["confirmed"]), "left_out": kit.trace["left_out"], "agents": len(run.threads),
            "calls": sum(len(t.replies) for t in run.threads), "cents": round(sum(t.cost for t in run.threads), 2),
            "seconds": round(max([t.ended or 0 for t in run.threads] + [0]), 1), "found_ids": final.found, "status": run.status}

show_def(AuditKit.save, as_findings, outcome)

#%% md
**The kit, tested end to end on one shard.** A short hand-written plan uses every step once. It scans the shard that holds the most planted bugs with two lenses, merges the findings, gives every batch two skeptics with evidence, keeps the findings both call real, and writes the report. This is a real run, small enough to make only a handful of calls; the count is printed below. Every intermediate result is printed, so the flow of a finding through the kit can be followed by eye.

#%% code
kit_shard = max(shards(), key=lambda s: sum(b["path"] in s for b in ANSWER_KEY))
kit_run = Run("the kit on one shard", run_id="s31-kit", concurrency=8)
KIT = AuditKit(kit_run)


def kit_plan(run):
    k = KIT.names()
    k["phase"]("Scan")
    found = k["flatten"](k["parallel"]([lambda lens=lens: k["scan"](kit_shard, lens) for lens in ("boundaries", "logic")]))
    cands = k["dedupe"](found)
    k["log"](f"{len(found)} findings, {len(cands)} places")
    k["phase"]("Check")
    verdicts = k["flatten"](k["parallel"]([lambda b=b, s=s: k["check"](b, sample=s) for b in k["batches"](cands, 6) for s in (0, 1)]))
    confirmed = k["vote"](cands, verdicts, need=2)
    k["phase"]("Report")
    return k["report"](confirmed)

show_def(kit_plan, layer="plan")
kit_result = kit_run.run_sync(kit_plan)
KIT.save()
KIT_OUT = outcome(kit_result, KIT)
print(f"[kit] shard of {len(kit_shard)} files holding {sum(b['path'] in kit_shard for b in ANSWER_KEY)} planted bugs; status {kit_run.status}")
print(f"[kit] scan: {len(KIT.trace['found'])} findings -> dedupe: {len(dedupe(KIT.trace['found']))} places -> "
      f"{len(KIT.trace['checked'])} verdicts -> {len(KIT.trace['confirmed'])} confirmed -> {len(kit_result['bugs'])} in the report "
      f"({kit_result['left_out']} added back)")
for f in kit_result["bugs"][:6]:
    hit = "planted" if match(as_findings([f])).tp else "not planted"
    print(f"  [{f['severity']:<8}] {f['file']}:{f['line']} {f['function']}  votes {f['votes']}  ({hit})")
print(f"[kit] {KIT_OUT['agents']} workers, {KIT_OUT['calls']} calls, {KIT_OUT['cents']:.1f} cents; "
      f"planted bugs in the report: {KIT_OUT['tp']}; places that were not planted bugs: {KIT_OUT['fp']}")

#%% md
One skeptic's thread, read in full: the batch it was given, with the code and the evidence, and the verdicts it answered.

#%% code
skeptic_thread = next((t for t in kit_run.threads if t.label.startswith("check")), None)
print(render_thread(skeptic_thread, width=1400) if skeptic_thread else "(no skeptic ran: the scan found nothing)")

#%% code
save_exp("kit", {"lenses": LENSES, "shard_files": len(kit_shard), "shard_bugs": sum(b["path"] in kit_shard for b in ANSWER_KEY),
                 "found": len(KIT.trace["found"]), "places": len(dedupe(KIT.trace["found"])), "confirmed": len(KIT.trace["confirmed"]),
                 "reported": len(kit_result["bugs"]), "tp": KIT_OUT["tp"], "fp": KIT_OUT["fp"], "calls": KIT_OUT["calls"],
                 "cents": KIT_OUT["cents"], "evidence_good": EV_GOOD["status"], "evidence_wrong": EV_WRONG["status"]})
results = []
expect("every planted kind of bug is the target of exactly one lens", set(aimed) == set(PLANTED_KINDS) and set(aimed.values()) == {1})
expect("shards cover every file exactly once", sorted(p for s in shards() for p in s) == WORK)
expect("dedupe merges two findings about one function and keeps the count", len(dedupe(demo_found)) == 2
       and max(f["reports"] for f in dedupe(demo_found)) == 2)
expect("finding() replaces a wrong function name with the true one", demo_found[0]["function"] == b0["function"])
expect("dedupe gives the same answer whatever the order of its input", dedupe(demo_found) == dedupe(demo_found[::-1]))
expect("the sandbox shows the planted bug: the call does not return what the original returns", EV_GOOD["status"] in ("differs", "raised"))
expect("the sandbox shows the correct function agreeing with its own example", EV_WRONG["status"] == "agrees")
expect("numbers are compared with a tolerance, not as text", same_value("2", "2.0000001") is True and same_value("-1", "2") is False)
expect("True and 1 are different answers, as in a doctest", same_value("True", "1") is False)
expect("the kit run completed and every check returned one verdict per finding",
       kit_run.status == "completed" and all(v["key"] for v in KIT.trace["checked"]))
expect("the report mentions every confirmed finding once, or adds it back",
       len({i for f in kit_result["bugs"] for i in f["merged"]}) == len(KIT.trace["confirmed"]))
