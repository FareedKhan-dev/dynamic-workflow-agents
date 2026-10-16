#%% md
# Part III. One agent alone, and why it stalls

Before building a team, we measure the strongest single worker we can give the job to.

**Where this sits.** Part II can ask a model one question. Here we give one model a whole audit and the tools a careful human reviewer would use: list a folder, read a file, search for a pattern, run a call to see what it returns, and write down a bug. Then we let it work for 150 turns and watch what happens to its coverage, its findings and its own memory. This is the baseline the rest of the notebook has to beat, and it is built with the same care, because beating a weak baseline proves nothing. The Part ends with a second baseline that is already a kind of team: a lead that hands out shards to helpers one at a time and reads every result itself.

**By the end of this Part you can**

- give an agent tools that cannot reach outside a folder, and run model-written code safely;
- write the loop that turns a model into an agent: ask, act, observe, repeat;
- keep a long-running agent inside its context window by compacting its history;
- explain, with measurements, the three ways a single agent falls short on a big job.

![part3_map](attachment:part3_map.png)

#%% md
## S14 - Tools that cannot leave the audited tree

**Theory.** An agent is a model plus **tools**: functions it can ask the host to run. The model never touches files itself. It writes a request such as `{"tool": "read", "args": {"path": "sorts/quick_sort.py"}}`, the host runs the function, and the result goes back into the conversation. This indirection is what makes an agent safe to build: every effect passes through code we wrote, and that code can refuse. Our six tools all open files through `readable()` from S3, so no path, however clever, reaches the hidden answer key or the original snapshot.

| tool | what it does | limits |
|---|---|---|
| `ls(path)` | lists a folder, with each file's line count | 200 entries |
| `read(path, start, end)` | returns numbered lines of a file | 300 lines per call |
| `grep(pattern, path)` | regex search through the tree | 40 hits |
| `run(file, call)` | runs one call in a sandbox and returns its value | 5 s, 1 GB, no network, no key |
| `report(...)` | records a bug | none |
| `done(summary)` | ends the audit | none |

**In plain terms.** The agent can only ask; our code does the reading and running, and our code says no to anything outside the tree.

**For teams.** Give an agent the tools a careful junior engineer would get, and no more. A tool that can do more than the job needs is a tool whose misuse you will have to explain later.

#%% code
READ_LIMIT, LS_LIMIT, GREP_LIMIT = 300, 200, 40


def tool_ls(path="."):
    """Entries of one folder of the audited tree: sub-folders end with /, files show their line count."""
    p = readable(path) if path not in (".", "", "/") else AUDITED.resolve()
    if not p.is_dir():
        return f"error: {path} is not a folder"
    rows = []
    for q in sorted(p.iterdir())[:LS_LIMIT]:
        if q.is_dir():
            rows.append(f"{q.name}/")
        elif q.suffix == ".py":
            rows.append(f"{q.name}  ({len(q.read_text(encoding='utf-8').splitlines())} lines)")
    more = len(list(p.iterdir())) - LS_LIMIT
    return "\n".join(rows) + (f"\n... {more} more entries not shown" if more > 0 else "")


def tool_read(path, start=1, end=None):
    """Numbered lines start..end of one file, at most READ_LIMIT lines per call."""
    p = readable(path)
    if not p.is_file():
        return f"error: {path} is not a file"
    lines = p.read_text(encoding="utf-8").split("\n")
    start = max(1, int(start or 1))
    end = min(len(lines), int(end or start + READ_LIMIT - 1), start + READ_LIMIT - 1)
    body = "\n".join(f"{i:>5}| {lines[i - 1]}" for i in range(start, end + 1))
    tail = f"\n(lines {start} to {end} of {len(lines)}; read again with start={end + 1} for more)" if end < len(lines) else ""
    return f"### {normalise_path(path)}\n{body}{tail}"


def tool_grep(pattern, path="."):
    """Lines matching a regular expression, as path:line: text, at most GREP_LIMIT."""
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"error: bad pattern ({e})"
    base = readable(path) if path not in (".", "", "/") else AUDITED.resolve()
    hits = []
    for f in sorted(base.rglob("*.py")) if base.is_dir() else [base]:
        for i, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if rx.search(line):
                hits.append(f"{f.relative_to(AUDITED.resolve())}:{i}: {line.strip()[:120]}")
                if len(hits) >= GREP_LIMIT:
                    return "\n".join(hits) + f"\n(stopped at {GREP_LIMIT} hits; narrow the pattern)"
    return "\n".join(hits) or "no matches"

show_def(tool_ls, tool_read, tool_grep)
print(tool_ls("searches")[:300])
print(tool_read("searches/binary_search.py", 50, 54))
print(tool_grep(r"def bisect_left", "searches"))
for bad in ["../hidden/answer_key.json", "../../pyproject.toml"]:
    try:
        tool_read(bad)
    except PathDenied as e:
        print(f"[guard] read({bad!r}) refused: {e}")

#%% md
## S15 - The fenced sandbox: running calls a model wrote

**Theory.** The most useful tool a bug hunter has is running the code. "I think `binary_search([1, 2, 3], 3)` returns -1 instead of 2" is a guess. The value the call actually returns is evidence. But the call was written by a model, and running text a model wrote is running untrusted code. We fence it in two layers.

The **first layer is a check of the call's syntax tree before anything runs.** A call is allowed only if it calls a function or class defined in the target file (or a short list of harmless builtins such as `list` and `range`), with arguments that are plain literals. There may be no names that start with `_`, no attribute access except a public method on an object the call itself just built, and no arithmetic. That excludes `__import__`, `open`, `eval`, reaching through `__class__`, and expressions like `[0] * 10**10`.

The **second layer is the process.** The call runs in a fresh Python, started with the switches of S1, with an environment that holds only a `PATH` and a hash seed (no API key), inside a temporary folder, with a five-second CPU limit and a one-gigabyte memory limit. Anything the first layer misses meets the second.

Neither layer alone is a security boundary against a determined attacker, and this notebook does not claim it is. Together they make it very unlikely that an honest model's mistake, an infinite loop or a call that allocates a terabyte, does any harm.

**In plain terms.** Before running a call a model wrote, we check it only calls the code under review with simple values, and then we run it in a locked box with a timer.

**For teams.** Separate "is this request allowed?" from "what happens if it misbehaves anyway?" and build both. Each one catches what the other misses.

#%% code
SAFE_BUILTINS = {"list", "tuple", "dict", "set", "range", "sorted", "reversed", "str", "int", "float", "bool",
                 "len", "abs", "min", "max", "sum", "round", "frozenset", "complex", "bytes"}


class CallRejected(ValueError):
    """A model-written call failed the syntax check."""


def module_names(path):
    """Functions and classes defined at the top of an audited file."""
    tree = ast.parse(readable(path).read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


def check_call(expr, names):
    """Raise CallRejected unless expr is one call to a known name with literal arguments."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as e:
        raise CallRejected(f"not a Python expression: {e.msg}")
    if not isinstance(tree.body, ast.Call):
        raise CallRejected("the expression must be a single call")
    allowed = names | SAFE_BUILTINS

    def ok_value(n):
        if isinstance(n, ast.Constant):
            return not isinstance(n.value, (bytes,)) or len(n.value) < 10_000
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)) and isinstance(n.operand, ast.Constant):
            return True
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            return all(ok_value(e) for e in n.elts)
        if isinstance(n, ast.Dict):
            return all(k is not None and ok_value(k) for k in n.keys) and all(ok_value(v) for v in n.values)
        if isinstance(n, ast.Call):
            return ok_call(n)
        return False

    def ok_call(c):
        f = c.func
        if isinstance(f, ast.Name):
            if f.id not in allowed or f.id.startswith("_"):
                return False
        elif isinstance(f, ast.Attribute):
            if f.attr.startswith("_") or not isinstance(f.value, ast.Call) or not ok_call(f.value):
                return False
        else:
            return False
        return all(ok_value(a) for a in c.args) and all(k.arg and not k.arg.startswith("_") and ok_value(k.value) for k in c.keywords)

    if not ok_call(tree.body):
        raise CallRejected("only calls to this file's functions or classes, with literal arguments, are allowed")
    return True

show_def(CallRejected, module_names, check_call)

#%% md
**`run_call(path, expr)`** is the second layer. A small runner script loads the audited file into a fresh module, exactly as the doctest runner did in S1, evaluates the checked expression inside it, and prints the value's `repr`, cut to 500 characters. The limits are set by the operating system in the child process, so they hold even if the code under test ignores every signal.

#%% code
import resource

CALL_RUNNER = r'''
import contextlib, io, json, random, sys, types
root, relpath = sys.argv[1], sys.argv[2]
expr = sys.stdin.read()
random.seed(0)                                   # the same call gives the same answer every time
sys.path.insert(0, root)
name = relpath[:-3].replace("/", ".")
mod = types.ModuleType(name)
mod.__file__ = root + "/" + relpath
sys.modules[name] = mod
try:
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compile(open(mod.__file__, encoding="utf-8").read(), mod.__file__, "exec"), mod.__dict__)
        value = eval(compile(expr, "<call>", "eval"), mod.__dict__)
    print(json.dumps({"ok": True, "value": repr(value)[:500]}))
except BaseException as e:
    print(json.dumps({"ok": False, "error": (type(e).__name__ + ": " + str(e))[:300]}))
'''


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))                      # seconds of CPU
    resource.setrlimit(resource.RLIMIT_AS, (1 << 30, 1 << 30))           # one gigabyte of memory


def run_call(path, expr, timeout=8):
    """Check, then run, one call against an audited file; returns {ok, value or error, seconds}."""
    path = normalise_path(path)
    try:
        check_call(expr, module_names(path))
    except (CallRejected, PathDenied, FileNotFoundError, SyntaxError) as e:
        return {"ok": False, "error": f"rejected: {e}", "seconds": 0.0}
    start = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        try:
            p = subprocess.run([sys.executable, *CLEAN_FLAGS, "-c", CALL_RUNNER, str(AUDITED.resolve()), path], input=expr,
                               capture_output=True, text=True, timeout=timeout, env=CLEAN_ENV, cwd=tmp, preexec_fn=_limits)
            out = json.loads((p.stdout.strip().splitlines() or ['{"ok": false, "error": "no output"}'])[-1])
        except subprocess.TimeoutExpired:
            out = {"ok": False, "error": "timeout: the call ran too long"}
        except ValueError:
            out = {"ok": False, "error": "the call produced unreadable output"}
    out["seconds"] = round(time.perf_counter() - start, 3)
    return out

show_def(_limits, run_call)

#%% md
**Trying to break the fence.** Each line below is a call a careless or curious model might write. The first few should run, and the rest should be stopped, most of them by the syntax check before any process starts.

#%% code
victim = "searches/binary_search.py"
ATTEMPTS_FENCE = [
    ("an honest call", "binary_search([1, 3, 5, 7], 5)"),
    ("nested builtin", "binary_search(list(range(10)), 7)"),
    ("keyword argument", "bisect_left([1, 2, 3], 2, lo=0)"),
    ("import the os module", "__import__('os').system('ls /')"),
    ("open a file", "open('/etc/passwd').read()"),
    ("climb through dunders", "binary_search.__globals__['__builtins__']"),
    ("arithmetic bomb", "binary_search([0] * 10**10, 0)"),
    ("unknown function", "eval('1 + 1')"),
    ("a statement, not a call", "import os"),
    ("huge allocation", "binary_search(list(range(400000000)), 3)"),
]
FENCE = []
for label, expr in ATTEMPTS_FENCE:
    out = run_call(victim, expr)
    FENCE.append({"attempt": label, "expr": expr[:44], "result": (out.get("value") or out.get("error", ""))[:58], "ok": out["ok"]})
table(FENCE, [("attempt", "attempt", ""), ("expr", "call", ""), ("result", "what came back", "")])
results = []
expect("honest calls run and return a value", all(r["ok"] for r in FENCE[:3]))
expect("every hostile call is stopped", not any(r["ok"] for r in FENCE[3:]))
expect("the sandbox's environment holds no API key", KEY_VARIABLE not in CLEAN_ENV and not any(v == API_KEY for v in CLEAN_ENV.values() if API_KEY))
