#%% md
## S38 - The lead writes a program

**Theory.** Everything is now in place for the lead to write plans in the full language: the API reference of S36, the whitelist that refuses what a plan must not do, and the dry run that prices a plan for free. The lead's instruction is the JSON instruction of S34 with the plan language swapped: the API reference, two short example programs that show the syntax, and the same rules. A written program goes through two gates before it is accepted: `check_program` (S36), then `dry_run` (S37). The problems from either gate go back to the lead verbatim, and it gets two repairs.

Ten samples measure three things: how often the lead writes a valid program at the first attempt and after repair, which rules its mistakes break, and which features of the language it actually uses. If it never loops, never decides from results and never pipelines, the language bought nothing over JSON.

**In plain terms.** The lead now writes its plan as a small program. A checker and a free rehearsal catch its mistakes, and it fixes them when told.

**For teams.** When a model writes code against your API, measure first-attempt validity, repaired validity and the distribution of errors. The errors tell you where your API reference is unclear; fix the reference before you blame the model.

#%% code
EXAMPLE_MINIMAL = f"""phase("Scan")
found = dedupe(flatten(parallel([lambda s=s: scan(s, "general") for s in shards({SHARD_TOKENS})])))
log(f"{{len(found)}} places found")
phase("Report")
result = report(found)"""
EXAMPLE_LOOP = f"""phase("Scan")
candidates = []
for rnd in range(2):
    found = flatten(parallel([lambda s=s: scan(s, "logic", sample=rnd) for s in shards({SHARD_TOKENS})]))
    new = [f for f in dedupe(found) if key_of(f) not in [key_of(c) for c in candidates]]
    candidates = dedupe(candidates + found)
    if len(new) < 3:
        break
phase("Verify")
verdicts = flatten(parallel([lambda b=b, k=k: check(b, sample=k) for b in batches(candidates, 6) for k in range(2)]))
phase("Report")
result = report(vote(candidates, verdicts, need=2))"""

LEAD_PROGRAM_SYSTEM = f"""You are the lead of a code audit, and you write the plan as a short program. You never read the code yourself: workers do, following your program.

THE PLAN LANGUAGE
A plan program is Python restricted to the names below, plus assignments, for loops, if, comprehensions, lambdas, small functions (def) and f-strings. Methods may be called only on data: {", ".join(sorted(ALLOWED_METHODS))}. A program cannot import anything, use while, try or classes, read attributes (a finding is a dict: use f["file"]), use names that start with an underscore, or read the clock or random numbers. It must assign the final report to `result`.

{PLAN_API_DOC}

HOW A RUN WORKS
Workers started inside one parallel() call run at the same time, about 32 at once. Every worker is one paid call, plus one more if its answer has to be repaired. phase() calls divide the run into the phases a person sees.

RULES
- Billing is per token: a call costs what it sends plus what it gets back, so the long scan calls cost the most.
- Keep the expected cost under half of the budget for this job. Your program is rehearsed against a stand-in model and priced before it runs; plans over the automatic limit wait for a person.
- Every file must be read by at least one scan worker.
- Use what was measured: shard sizes, findings per scan and latencies are in the summary.
- For independent second opinions use the sample argument; never the clock or random numbers.

TWO EXAMPLES OF THE SYNTAX (not recommendations)
```python
{EXAMPLE_MINIMAL}
```
```python
{EXAMPLE_LOOP}
```

Answer with the program in one ```python block and nothing else."""
print(f"[lead] the program instruction: {len(LEAD_PROGRAM_SYSTEM.split())} words, about {est_tokens(LEAD_PROGRAM_SYSTEM)} tokens")
print(f"[check] both examples pass the whitelist: {not check_program(EXAMPLE_MINIMAL) and not check_program(EXAMPLE_LOOP)}")

#%% md
**`extract_code(text)`** takes the program out of the lead's reply: the first fenced Python block, or the whole reply if it has no fence and parses. **`Lead.write_program`** runs the two gates and the repairs, and keeps every attempt.

#%% code
def extract_code(text):
    """The first ```python block of a reply, or the reply itself if it parses as Python; None otherwise."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text or "", re.S)
    if m:
        return m.group(1).strip()
    try:
        ast.parse(text or "")
        return (text or "").strip() or None
    except SyntaxError:
        return None


@method_of(Lead)
def write_program(self, job, page, sample=0, budget_cents=300, repairs=2, system=None, kit_class=None, stand_in=None):
    messages = [{"role": "system", "content": system or LEAD_PROGRAM_SYSTEM}, {"role": "user", "content": f"THE JOB\n{job}\n\n{page}"}]
    attempts = []
    for k in range(1 + repairs):
        r = self.ask(messages, f"lead:program#{sample}:try{k + 1}:{budget_cents:.0f}", sample, max_tokens=8000)
        src = extract_code(r.text) if r.finish != "error" else None
        est, problems = (dry_run(src, budget_cents, kit_class=kit_class, stand_in=stand_in) if src
                         else (None, ["line 1: the reply has no ```python block"]))
        attempts.append({"src": src, "problems": problems, "estimate": est})
        if not problems:
            return {"src": src, "valid": True, "tries": k + 1, "attempts": attempts, "estimate": est}
        messages = messages + [{"role": "assistant", "content": r.text[:8000]},
                               {"role": "user", "content": "Your program has these problems:\n- " + "\n- ".join(problems[:8])
                                + "\nSend the whole corrected program in one ```python block."}]
    return {"src": src, "valid": False, "tries": 1 + repairs, "attempts": attempts, "estimate": None}

show_def(extract_code, Lead.write_program)

#%% md
**What a program uses.** **`features(src)`** reads a program's syntax tree and lists the things a data plan could not say: a loop, a decision from results (an `if` that depends on what workers returned, or a filter over evidence), a pipeline, a look at the budget, a custom worker written with `agent()`, and functions of its own.

#%% code
FEATURES = ["loop", "decides from results", "pipeline", "reads the budget", "custom worker", "own function"]


def features(src):
    """Which of FEATURES a plan program uses."""
    tree = ast.parse(src)
    calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    found = set()
    if any(isinstance(n, ast.For) for n in ast.walk(tree)):
        found.add("loop")
    if "evidence" in calls or any(isinstance(n, (ast.If, ast.IfExp)) for n in ast.walk(tree)):
        found.add("decides from results")
    for name, feature in (("pipeline", "pipeline"), ("budget", "reads the budget"), ("agent", "custom worker")):
        if name in calls:
            found.add(feature)
    if any(isinstance(n, ast.FunctionDef) for n in ast.walk(tree)):
        found.add("own function")
    return [f for f in FEATURES if f in found]

show_def(features)
for name, src in GOOD.items():
    print(f"[features] {name:<26} {', '.join(features(src)) or '(none: a data plan could say this)'}")

#%% md
**A scripted lead for smoke runs.** The stand-in writes one of five program shapes, chosen by the sample index. It sizes the plan the way its instruction asks: it tries three lenses and three skeptics first, then fewer, and picks the shard size from the scout's page, until a rough estimate fits half the budget. Four of the ten samples make a typical first mistake (an import, a `while` loop, a forgotten `result`, an attribute read) and correct it when told, so every repair path runs in a smoke build.

#%% code
def _program_shapes(tokens, lenses, skeptics):
    """Five plan programs of different shapes, for the scripted lead."""
    lens_list = repr(lenses)
    verify = (f"verdicts = flatten(parallel([lambda b=b, k=k: check(b, sample=k) for b in batches(candidates, 6) for k in range({skeptics})]))\n"
              f"confirmed = vote(candidates, verdicts, need={skeptics // 2 + 1})")
    scan = f"flatten(parallel([lambda s=s, l=l: scan(s, l) for s in shards({tokens}) for l in {lens_list}]))"
    return [
        f'phase("Scan")\ncandidates = dedupe({scan})\nphase("Verify")\n{verify}\nphase("Report")\nresult = report(confirmed)',
        f'phase("Scan")\ncandidates = []\nfor rnd in range(2):\n    found = flatten(parallel([lambda s=s, l=l: scan(s, l, sample=rnd) for s in shards({tokens}) for l in {lens_list}]))\n'
        f'    new = [f for f in dedupe(found) if key_of(f) not in [key_of(c) for c in candidates]]\n    candidates = dedupe(candidates + found)\n'
        f'    log(f"round {{rnd + 1}}: {{len(new)}} new places")\n    if len(new) < 5:\n        break\nphase("Verify")\n{verify}\nphase("Report")\nresult = report(confirmed)',
        f'phase("Scan")\nfound = dedupe({scan})\nphase("Triage")\ncandidates = [f for f in found if evidence(f)["status"] != "agrees"]\n'
        f'log(f"kept {{len(candidates)}} of {{len(found)}} places after the sandbox")\nphase("Verify")\n{verify}\nphase("Report")\nresult = report(confirmed)',
        f'phase("Scan and verify, per shard")\ndef verify(found, shard, i):\n    candidates = dedupe(found)\n'
        f'    verdicts = flatten([check(b, sample=k) for b in batches(candidates, 6) for k in range({skeptics})])\n'
        f'    return vote(candidates, verdicts, need={skeptics // 2 + 1})\n'
        f'confirmed = flatten(pipeline(shards({tokens}), lambda _, s, i: flatten([scan(s, l) for l in {lens_list}]), verify))\n'
        f'phase("Report")\nresult = report(confirmed)',
        f'lenses = {lens_list} if budget() > 60 else ["general"]\nphase("Scan")\ncandidates = dedupe(flatten(parallel([lambda s=s, l=l: scan(s, l) '
        f'for s in shards({tokens}) for l in lenses])))\nphase("Verify")\n{verify}\nphase("Report")\nresult = report(confirmed)',
    ]


MISTAKES = {2: lambda src: "import math\n" + src, 5: lambda src: src.replace('phase("Verify")', 'n = 0\nwhile n < 1:\n    n = n + 1\nphase("Verify")', 1),
            7: lambda src: src.replace("result = report(confirmed)", "report(confirmed)"),
            9: lambda src: src.replace("candidates = dedupe(", "first = work.count\ncandidates = dedupe(", 1)}


@SCRIPTED.register
def _lead_program(model, messages, params):
    if "and you write the plan as a short program" not in messages[0]["content"][:200]:
        return None
    page = messages[1]["content"]
    budget = float((re.search(r"Budget for this job: ([0-9.]+)", page) or [0, "300"])[1])
    count = {int(t) * 1000: int(n) for t, n in re.findall(r"- (\d+)k tokens: (\d+) shards", page)}
    chosen = int((re.search(r"best shard size is (\d+)k", page) or [0, SHARD_TOKENS // 1000])[1]) * 1000
    order = [t for t in sorted(count) if t >= chosen]          # the measured size first, then larger, cheaper ones
    k = params.get("sample", 0)
    shape = k % 5
    plan = None
    for lenses, skeptics in ((list(LENSES), 3), (["boundaries", "logic"], 3), (["general"], 1)):
        for t in order:
            scans = count[t] * len(lenses) * (2 if shape == 1 else 1)
            cost = 0.2 * (scans + scans * SCAN_STATS[0] * SCAN_STATS[1] / 6 * skeptics) + 0.5
            if cost <= budget / 2:
                plan = (t, lenses, skeptics)
                break
        if plan:
            break
    tokens, lenses, skeptics = plan or (max(count), ["general"], 1)
    src = _program_shapes(tokens, lenses, skeptics)[shape]
    if k in MISTAKES and not messages[-1]["content"].startswith("Your program has these problems"):
        src = MISTAKES[k](src)
    return f"Here is the plan.\n\n```python\n{src}\n```"

show_def(_program_shapes, _lead_program)

#%% md
**Ten programs for the same job.** Sample indexes 0 to 9, a budget of 300 cents. Every program is checked and rehearsed; the table lists what it became and what it cost to get there.

#%% code
PROGRAMS = [LEAD.write_program(JOB, SCOUT_TEXT, sample=k, budget_cents=300) for k in range(10)]
PROG_ROWS = []
for k, w in enumerate(PROGRAMS):
    est = w["estimate"] or {}
    PROG_ROWS.append({"sample": k, "tries": w["tries"], "valid": "yes" if w["valid"] else "no", "lines": len((w["src"] or "").splitlines()),
                      "cents": est.get("cents"), "workers": est.get("agents"),
                      "features": ", ".join(features(w["src"])) if w["valid"] else "-"})
table(PROG_ROWS, [("sample", "sample", "d"), ("tries", "tries", "d"), ("valid", "valid", ""), ("lines", "lines", "d"),
                  ("workers", "workers (est.)", "d"), ("cents", "¢ (est.)", ".1f"), ("features", "uses", "")])


def rule_of(problem):
    """Which gate and rule a problem came from, for counting."""
    p = problem.lower()
    for key, words in (("syntax", ("not valid python",)), ("size", ("characters; the limit",)), ("dry run", ("dry run",)),
                       ("no code block", ("no ```python",)), ("result", ("never assigns",)), ("attributes", ("attribute", "method", "internals")),
                       ("names", ("not defined", "underscore", "reassigned")), ("syntax kinds", ("is not allowed",))):
        if any(w in p for w in words):
            return key
    return "other"

show_def(rule_of)
ERRORS = collections.Counter(rule_of(p) for w in PROGRAMS for a in w["attempts"][:-1] if a["problems"] for p in a["problems"][:1])
FEATURE_COUNT = collections.Counter(f for w in PROGRAMS if w["valid"] for f in features(w["src"]))
print(f"[programs] valid at the first attempt: {sum(w['valid'] and w['tries'] == 1 for w in PROGRAMS)} of 10; after repair: "
      f"{sum(w['valid'] for w in PROGRAMS)} of 10")
print(f"[programs] first problems by rule: {dict(ERRORS)}")
for k, w in enumerate(PROGRAMS):
    for i, a in enumerate(w["attempts"][:-1]):
        print(f"  sample {k}, attempt {i + 1}: {a['problems'][0][:110]}")

#%% md
One of the lead's programs, in full: the first one that uses something a data plan could not say.

#%% code
shown = next((w for w in PROGRAMS if w["valid"] and set(features(w["src"])) - {"decides from results"}), next(w for w in PROGRAMS if w["valid"]))
print(shown["src"])
print(f"\n[program] uses: {', '.join(features(shown['src'])) or 'nothing beyond a data plan'}; "
      f"estimate {shown['estimate']['agents']} workers, {shown['estimate']['cents']:.1f}¢")

#%% code
# FIG  how well the lead writes programs, where it goes wrong, and what it uses
fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.4), gridspec_kw={"width_ratios": [1, 1.2, 1.3]})
ax = axes[0]
by_try = [sum(w["valid"] and w["tries"] == t for w in PROGRAMS) for t in (1, 2, 3)] + [sum(not w["valid"] for w in PROGRAMS)]
ax.bar(["try 1", "try 2", "try 3", "never"], by_try, color=[C3, C1, C7, C8])
ax.set_ylabel("programs (of 10)")
panel(ax, "valid at which attempt")
ax = axes[1]
items = ERRORS.most_common() or [("none", 0)]
ax.barh([k for k, _ in items], [v for _, v in items], color=C4)
ax.invert_yaxis()
ax.set_xlabel("first problems, all failed attempts")
panel(ax, "which gate caught it")
ax = axes[2]
ax.barh(FEATURES, [FEATURE_COUNT[f] for f in FEATURES], color=C1)
ax.invert_yaxis()
ax.set_xlim(0, 10)
ax.set_xlabel("valid programs using it (of 10)")
panel(ax, "what the programs use")
beyond = sum(1 for w in PROGRAMS if w["valid"] and set(features(w["src"])) - {"decides from results"})
finish(fig, "s38_programs", f"{sum(w['valid'] for w in PROGRAMS)} of 10 programs valid after repair; "
       f"{beyond} use a loop, a pipeline or the budget",
       "ten samples of the lead's program for the same job at a budget of 300; each attempt checked by the whitelist and a dry run")

#%% md
**Reading FIG {{figures.s38_programs}} (s38_programs).** Left: {{lead_program.valid_first}} of 10 programs were valid at the first attempt and {{lead_program.valid_final}} of 10 after at most two repairs. Middle: which gate caught the first problem of each failed attempt, the list of places where the API reference could be clearer. In this run no attempt failed, so the panel is empty. Right: what the valid programs used. {{lead_program.beyond}} of the valid programs used at least one thing a data plan cannot express: a loop, a pipeline, the budget, a custom worker or a function of their own. That is the measured answer to S35's question. Given the language, the lead does use it, mostly for loops and decisions from results; none of the ten programs used a pipeline.

#%% code
save_exp("lead_program", {"rows": PROG_ROWS, "valid_first": sum(w["valid"] and w["tries"] == 1 for w in PROGRAMS),
                          "valid_final": sum(w["valid"] for w in PROGRAMS), "errors": dict(ERRORS), "features": dict(FEATURE_COUNT),
                          "beyond": beyond, "instruction_tokens": est_tokens(LEAD_PROGRAM_SYSTEM)})
results = []
expect("at least six of ten programs are valid after repair (the stage 5 go rule)", sum(w["valid"] for w in PROGRAMS) >= 6)
expect("every failed attempt was told why, by line", all(a["problems"] and a["problems"][0].startswith("line ")
                                                       for w in PROGRAMS for a in w["attempts"][:-1]))
expect("every valid program passed both gates", all(not check_program(w["src"]) and w["estimate"] for w in PROGRAMS if w["valid"]))
expect("the repairs are recorded attempt by attempt", all(len(w["attempts"]) == w["tries"] for w in PROGRAMS))
