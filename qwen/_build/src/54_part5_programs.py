#%% md
## S36 - Plans as programs

**Theory.** The second form of plan is a **plan program**: a few lines of Python that call the runtime's primitives and the kit's steps directly. Python, because models write it fluently and people can read it; but a **restricted** Python, for three reasons:

- **checkable**: a program is accepted or refused before it runs, with a list of reasons a model can act on;
- **deterministic**: no clock, no random numbers, no reading of files, so the same answers always produce the same questions, and resume (S28) keeps working;
- **contained**: the program can reach nothing but the names it is given. It cannot import, open files, look at the objects behind its names, or change its own rules.

The restriction is a **whitelist**, built from rules that each forbid one thing. It is validation of a plan, not a security boundary for hostile code: the plans come from our own lead, and the whitelist exists to catch mistakes and keep plans honest and repeatable. The sandbox of S15, which runs code from the audited library, is a separate and stronger fence.

**In plain terms.** A plan program is a tiny Python script that may only use the words we give it. A checker reads the script before it runs and refuses anything outside those words.

**For teams.** If you let a model write code that drives your system, make the language small: a list of allowed names, a list of allowed syntax, nothing else. A whitelist fails safe; a blacklist fails open the first time someone finds a word you forgot.

#%% md
**The plan language, as the lead will read it.** These are all the names a plan program can use. The kit's names come from `AuditKit.names()`; the built-in functions are the short list of S32.

#%% code
PLAN_API_DOC = """RUNTIME
  phase(title)                         open a new phase; every worker started after it belongs to it
  log(message)                         say something into the run's event stream
  agent(prompt, schema=None, model="worker", label="", system="", data=None, sample=0)
                                       one worker; returns its JSON answer as a dict, or None if it failed
  parallel([thunk, ...])               run the thunks (functions of no arguments) at once; results in order, None for failures
  pipeline(items, stage, stage, ...)   each item flows through the stages on its own, with no barrier;
                                       a stage is a function (previous_result, item, index) -> result
  budget()                             Magicubes the session can still spend
THE AUDIT KIT
  work                                 the list of file paths to audit
  shards(tokens)                       the files packed into shards of about `tokens` tokens; a shard is a list of paths
  scan(shard, lens="general", sample=0, model="worker")
                                       one worker reads one shard through one lens; returns a list of findings
  LENSES                               ["boundaries", "logic", "state"]; "general" is also allowed
  dedupe(findings)                     one finding per place (file and function), the most confident one
  key_of(finding)                      the place a finding is about, as a string
  evidence(finding)                    run the finding's failing call in the sandbox; a dict with "status":
                                       "differs", "agrees", "raised" or "not run", and "text"
  batches(items, size)                 consecutive groups of at most `size` items
  check(batch, sample=0, model="judge", with_evidence=True)
                                       one skeptic judges a batch of up to 8 findings; one verdict per finding
  vote(candidates, verdicts, need=2)   the candidates with at least `need` verdicts of real
  report(confirmed, model="lead")      one worker writes the final report; returns a dict with "bugs"
  flatten(lists)                       one list from a list of lists, skipping None
  render(shard)                        the numbered text of a shard, for a custom agent()
  SCHEMAS, MODELS                      the JSON schemas ("findings", "verdicts") and the model roles
BUILT-IN FUNCTIONS
  """ + ", ".join(PLAN_BUILTINS) + """
A finding is a dict with: file, line, function, claim, failing_call, expected, confidence.
The program must assign the final report to the name `result`."""
print(PLAN_API_DOC)
print(f"\n[api] {len(PLAN_API_DOC.split())} words, about {est_tokens(PLAN_API_DOC)} tokens")

#%% md
### The whitelist, one rule at a time

Each rule is a function that takes the parsed program and returns a list of problems, each starting with the line it refers to. **`check_program(src)`** runs them all. The rules are deliberately boring; the interesting part is the tests after them.

**Rule 1: it parses, and it is short.** A plan longer than 80 lines or 6,000 characters is almost always doing something a plan should not do.

#%% code
class PlanRejected(ValueError):
    """A plan program failed the whitelist check or the dry run."""


def rule_parse(src):
    """(tree or None, problems): the program must parse and stay short."""
    problems = []
    if len(src) > 6000 or len(src.splitlines()) > 80:
        problems.append(f"line 1: the program has {len(src.splitlines())} lines and {len(src)} characters; the limit is 80 and 6,000")
    try:
        return ast.parse(src), problems
    except SyntaxError as e:
        return None, problems + [f"line {e.lineno}: this is not valid Python ({e.msg})"]

show_def(PlanRejected, rule_parse)

#%% md
**Rule 2: only the allowed kinds of statement and expression.** Assignments, `for` loops, `if`, small functions, lambdas, comprehensions, calls, literals, arithmetic, comparisons and f-strings. Everything else is refused, and a few refusals get a sentence of explanation: `while` because a plan's loops must state their bound, `import` and `try` because a plan has nothing to import and no reason to hide an error, and `**` because nothing in a plan needs an exponent and huge numbers are how runaway loops begin.

#%% code
ALLOWED_NODES = {
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.For, ast.If, ast.Break, ast.Continue, ast.Return, ast.FunctionDef,
    ast.Lambda, ast.ListComp, ast.DictComp, ast.SetComp, ast.GeneratorExp, ast.comprehension, ast.Call, ast.keyword,
    ast.Name, ast.Attribute, ast.Subscript, ast.Slice, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set, ast.BoolOp,
    ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp, ast.JoinedStr, ast.FormattedValue, ast.arguments, ast.arg, ast.Starred,
    ast.Load, ast.Store, ast.And, ast.Or, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Not, ast.USub,
    ast.UAdd, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot}
WHY_NOT = {ast.While: "use a for loop over range(n), so the loop states its bound", ast.Import: "a plan has nothing to import",
           ast.ImportFrom: "a plan has nothing to import", ast.Try: "a plan must not hide errors; failed workers already return None",
           ast.Pow: "nothing in a plan needs an exponent", ast.ClassDef: "a plan defines no classes",
           ast.Global: "a plan has no globals to change", ast.Nonlocal: "a plan has no outer variables to change"}


def rule_nodes(tree):
    """Problems for every kind of syntax outside the whitelist."""
    out = []
    for n in ast.walk(tree):
        if type(n) not in ALLOWED_NODES:
            why = WHY_NOT.get(type(n)) or "it is not part of the plan language"
            out.append(f"line {getattr(n, 'lineno', 1)}: {type(n).__name__} is not allowed: {why}")
        elif isinstance(n, ast.FunctionDef) and n.decorator_list:
            out.append(f"line {n.lineno}: decorators are not allowed")
        elif isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool) and abs(n.value) > 1_000_000:
            out.append(f"line {n.lineno}: the number {n.value} is larger than any plan needs (limit 1,000,000)")
    return out

show_def(rule_nodes)

#%% md
**Rule 3: only the given names.** Every name a program reads must be one of the plan language's names, one of the allowed built-ins, or a name the program itself defines (by assignment, as a loop variable, as a function or as a parameter). No name may begin with `_`, which closes the door to Python's internals; the one exception is a lone `_`, the usual name for a value a lambda ignores. And the program may not assign to a name of the language, because a plan that redefines `agent` is no longer the plan the reviewer read.

#%% code
def rule_names(tree, api):
    """Problems for names that are unknown, private, or reassign the language."""
    bound = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            bound.add(n.id)
        elif isinstance(n, ast.FunctionDef):
            bound.add(n.name)
        elif isinstance(n, ast.arg):
            bound.add(n.arg)
    out = []
    for n in ast.walk(tree):
        name = n.id if isinstance(n, ast.Name) else n.name if isinstance(n, ast.FunctionDef) else n.arg if isinstance(n, ast.arg) else None
        if name is None:
            continue
        line = getattr(n, "lineno", 1)
        if name.startswith("_") and name != "_":            # a lone _ is the usual name for an unused value
            out.append(f"line {line}: the name '{name}' starts with an underscore, which is not allowed")
        elif name in api and (isinstance(n, (ast.FunctionDef, ast.arg)) or isinstance(getattr(n, "ctx", None), ast.Store)):
            out.append(f"line {line}: '{name}' is part of the plan language and cannot be reassigned")
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and name not in api and name not in PLAN_BUILTINS and name not in bound:
            out.append(f"line {line}: the name '{name}' is not defined; the plan language has no such name")
    return sorted(set(out), key=lambda s: int(s.split(":")[0][5:]))

show_def(rule_names)

#%% md
**Rule 4: attributes only as method calls on data.** `findings.append(f)` and `name.startswith("x")` are fine; reading an attribute is not, and neither is calling a method outside a short list. This rule is what keeps a program from walking from an object to its class, its module and everything else Python can reach. `format` is deliberately missing from the list: a format string such as `"{0.__class__}"` reads attributes by itself, so a program uses f-strings instead, whose parts rules 3 and 4 can see.

#%% code
ALLOWED_METHODS = {"append", "extend", "get", "items", "keys", "values", "update", "add", "setdefault", "pop", "sort", "split",
                   "strip", "lower", "upper", "join", "startswith", "endswith", "count", "index", "replace"}


def rule_attributes(tree):
    """Problems for attribute reads and for method calls outside the short list."""
    calls = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute):
            if n.attr.startswith("_"):
                out.append(f"line {n.lineno}: '.{n.attr}' reaches into Python's internals, which is not allowed")
            elif id(n) not in calls:
                out.append(f"line {n.lineno}: reading the attribute '.{n.attr}' is not allowed; findings are dicts, use f['{n.attr}']")
            elif n.attr not in ALLOWED_METHODS:
                out.append(f"line {n.lineno}: the method '.{n.attr}()' is not allowed; allowed: {', '.join(sorted(ALLOWED_METHODS))}")
    return out

show_def(rule_attributes)

#%% md
**Rule 5: it produces a result.** The program must assign `result` at its top level, so there is always exactly one thing the lead gets back.

#%% code
def rule_result(tree):
    """A problem unless `result` is assigned at the top level of the program."""
    assigned = any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "result" for t in n.targets) for n in tree.body)
    nested = any(isinstance(n, (ast.For, ast.If)) and any(isinstance(m, ast.Name) and m.id == "result" and isinstance(m.ctx, ast.Store)
                                                       for m in ast.walk(n)) for n in tree.body)
    return [] if assigned or nested else ["line 1: the program never assigns `result`; end it with result = report(...)"]


PLAN_NAMES = set(AuditKit(Run("api", run_id="api-names", llm=FRONT_DOOR)).names())


def check_program(src, api=None):
    """Every problem with a plan program, by line; an empty list means it may go on to the dry run."""
    api = set(api) if api is not None else PLAN_NAMES
    tree, problems = rule_parse(src)
    if tree is None:
        return problems
    return problems + rule_nodes(tree) + rule_names(tree, api) + rule_attributes(tree) + rule_result(tree)

show_def(rule_result, check_program)
print(f"[api] the plan language has {len(PLAN_NAMES)} names and {len(PLAN_BUILTINS)} built-ins; "
      f"{len(ALLOWED_NODES)} kinds of syntax; {len(ALLOWED_METHODS)} methods")
print(f"[check] the compiled fixed plan: {check_program(FIXED_PROGRAM, PLAN_NAMES) or 'no problems'}")

#%% md
### Fourteen hostile programs, and five good ones

Every hostile program below tries one thing a plan must not do. Every good program is a plan we actually want to run, including the three ideas from S35 that JSON could not express. The checker must refuse all of the first group, accept all of the second, and say *why* in words a model can act on.

#%% code
HOSTILE = {
    "import a module": "import os\nresult = report([])",
    "reach builtins through a dunder": "x = __import__('os')\nresult = report([])",
    "open a file": "data = open('/etc/passwd')\nresult = report([])",
    "read a function's globals": "g = scan.__globals__\nresult = report([])",
    "format-string attribute walk": "s = '{0.__class__}'.format(scan)\nresult = report([])",
    "an unbounded loop": "while True:\n    log('again')\nresult = report([])",
    "run arbitrary code": "exec('import os')\nresult = report([])",
    "define a class": "class Escape:\n    pass\nresult = report([])",
    "redefine a primitive": "agent = lambda *a, **k: None\nresult = report([])",
    "getattr by name": "f = getattr(scan, 'x')\nresult = report([])",
    "hide failures": "try:\n    x = 1\nexcept Exception:\n    x = 2\nresult = report([])",
    "walk to the base classes": "b = [c for c in ().__class__.__bases__]\nresult = report([])",
    "an attribute inside an f-string": "log(f'{scan.__name__}')\nresult = report([])",
    "a huge number": "for i in range(10 ** 12):\n    log(i)\nresult = report([])",
}
GOOD = {
    "the fixed plan, compiled": FIXED_PROGRAM,
    "loop until nothing new": """phase("Scan")
candidates = []
for rnd in range(3):
    found = flatten(parallel([lambda s=s: scan(s, "general", sample=rnd) for s in shards(40000)]))
    new = [f for f in dedupe(found) if key_of(f) not in [key_of(c) for c in candidates]]
    candidates = dedupe(candidates + found)
    log(f"round {rnd + 1}: {len(new)} new places")
    if len(new) < 5:
        break
phase("Verify")
verdicts = flatten(parallel([lambda b=b, k=k: check(b, sample=k) for b in batches(candidates, 6) for k in range(3)]))
phase("Report")
result = report(vote(candidates, verdicts, need=2))""",
    "decide from the evidence": """phase("Scan")
found = dedupe(flatten(parallel([lambda s=s, lens=lens: scan(s, lens) for s in shards(40000) for lens in LENSES])))
phase("Triage")
keep = [f for f in found if evidence(f)["status"] != "agrees"]
log(f"{len(found) - len(keep)} places dropped: their own failing call agreed with the finder")
phase("Verify")
verdicts = flatten(parallel([lambda b=b, k=k: check(b, sample=k) for b in batches(keep, 6) for k in range(3)]))
phase("Report")
result = report(vote(keep, verdicts, need=2))""",
    "pipeline per shard": """phase("Scan and verify, per shard")
def verify(found, shard, i):
    places = dedupe(found)
    verdicts = flatten([check(b, sample=k) for b in batches(places, 6) for k in range(3)])
    return vote(places, verdicts, need=2)
confirmed = flatten(pipeline(shards(40000), lambda _, s, i: flatten([scan(s, lens) for lens in LENSES]), verify))
phase("Report")
result = report(confirmed)""",
    "fit the budget": """lenses = LENSES if budget() > 100 else ["general"]
skeptics = 3 if budget() > 100 else 1
phase("Scan")
found = dedupe(flatten(parallel([lambda s=s, l=l: scan(s, l) for s in shards(40000) for l in lenses])))
phase("Verify")
verdicts = flatten(parallel([lambda b=b, k=k: check(b, sample=k) for b in batches(found, 6) for k in range(skeptics)]))
phase("Report")
result = report(vote(found, verdicts, need=skeptics // 2 + 1))""",
}
rows = []
for name, src in HOSTILE.items():
    probs = check_program(src, PLAN_NAMES)
    rows.append({"program": name, "group": "hostile", "verdict": "refused" if probs else "ACCEPTED", "reason": (probs or [""])[0][:96]})
for name, src in GOOD.items():
    probs = check_program(src, PLAN_NAMES)
    rows.append({"program": name, "group": "good", "verdict": "accepted" if not probs else "REFUSED", "reason": (probs or ["-"])[0][:96]})
CHECK_ROWS = rows
table(rows, [("group", "group", ""), ("program", "program", ""), ("verdict", "verdict", ""), ("reason", "first reason given", "")])

#%% md
Two of the hostile programs are worth a closer look. The format-string walk would pass a checker that allowed the `format` method, because the attribute names hide inside a string where no syntax rule can see them; that is why `format` is not in the list. And the huge number is refused for its size, but a determined program could still multiply two allowed numbers. Rules cannot bound a program's running time in general, so S37 adds a time limit to the dry run, and the agent limit of S29 bounds what a runaway plan can spend.

**`run_program` grows a gate.** From now on every program, written by us or by the lead, is checked before it runs. The function is redefined here with exactly one new step at the top.

#%% code
def run_program(src, kit):
    """Check, then execute plan code with only the kit's names and a few built-ins; return what it assigns to `result`."""
    problems = check_program(src, kit.names())
    if problems:
        raise PlanRejected("; ".join(problems[:5]))
    env = dict(kit.names())
    env["__builtins__"] = {n: getattr(builtins, n) for n in PLAN_BUILTINS}
    exec(compile(src, f"<plan {kit.run.run_id}>", "exec"), env)
    return env.get("result")

show_def(run_program)
try:
    run_program(HOSTILE["import a module"], AuditKit(Run("gate test", run_id="s36-gate", llm=FRONT_DOOR)))
    gate_held = False
except PlanRejected as e:
    gate_held = True
    print(f"[gate] refused before running: {e}")

#%% code
save_exp("programs", {"api_words": len(PLAN_API_DOC.split()), "api_tokens": est_tokens(PLAN_API_DOC), "names": len(PLAN_NAMES),
                      "hostile": len(HOSTILE), "hostile_refused": sum(r["verdict"] == "refused" for r in rows),
                      "good": len(GOOD), "good_accepted": sum(r["verdict"] == "accepted" for r in rows), "rows": rows})
results = []
expect("every hostile program is refused", all(r["verdict"] == "refused" for r in rows if r["group"] == "hostile"))
expect("every good program is accepted", all(r["verdict"] == "accepted" for r in rows if r["group"] == "good"))
expect("every refusal names a line", all(r["reason"].startswith("line ") for r in rows if r["verdict"] == "refused"))
expect("the gate refuses a hostile program before any of it runs", gate_held)
