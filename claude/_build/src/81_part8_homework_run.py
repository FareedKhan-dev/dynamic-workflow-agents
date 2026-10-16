#%% md
**An exact calculator.** The first lens of this job is not a model at all. **`calculator(sub)`** finds every written calculation of the form *expression = result* in a solution, recomputes the expression exactly, and lists the lines where the stated result is off by more than rounding. It can catch a slip whose expression is written out, and by construction it cannot catch an operation error or a misread number, because those lines are correct arithmetic. It is not perfect on real student writing: fractions written as `8/12`, multiplication written without a sign and similar habits produce false alarms, and the table measures how many against the key, before any model is involved.

#%% code
WRITTEN_CALC = re.compile(r"(?<![\d.)/])(?<![\d.)/]\s)"                    # not the tail of a longer expression
                          r"((?:\(?\s*\d[\d,]*(?:\.\d+)?\s*\)?\s*[-+*/x\u00d7\u00f7]\s*)+\(?\s*\d[\d,]*(?:\.\d+)?\s*\)?)"
                          r"\s*=\s*\$?\s*(\d[\d,]*(?:\.\d+)?)(?!\s*[/x\u00d7*\u00f7]\s*\d)")   # a result, not the top of a fraction


def calculator(sub):
    """[(line, written expression, stated result, exact result)] for every written calculation that is off by more than rounding."""
    out = []
    for n, ln in enumerate(sub["lines"], 1):
        for m in WRITTEN_CALC.finditer(ln):
            val = exact(m.group(1).replace("×", "*").replace("÷", "/").replace("x", "*"))
            stated = Fraction(m.group(2).replace(",", ""))
            if val is not None and abs(val - stated) > max(Fraction(1, 100), abs(val) / 100):
                out.append((n, m.group(1).strip(), show_num(stated), show_num(val)))
    return out

show_def(calculator)
SUB_BY_ID = {s["id"]: s for s in SUBMISSIONS}
CALC_FLAGS = {s["id"]: calculator(s) for s in SUBMISSIONS}
calc_rows = []
for kind in HW_KINDS + [None]:
    group = [s for s in SUBMISSIONS if s["kind"] == kind]
    flagged = [s for s in group if CALC_FLAGS[s["id"]]]
    right_line = [s for s in flagged if kind and CALC_FLAGS[s["id"]][0][0] == s["first_wrong"]]
    calc_rows.append({"kind": kind or "correct", "n": len(group), "flagged": len(flagged), "right_line": len(right_line)})
table(calc_rows, [("kind", "planted kind", ""), ("n", "solutions", "d"), ("flagged", "flagged by the calculator", "d"),
                  ("right_line", "on the right line", "d")])

#%% md
**The homework kit.** As in S31, the job's words for plans: `items` (the 600 ids), `grade(batch)` for a grader that reads up to 40 solutions, `recheck(batch, lens)` for a second reader with one lens (`calculator`, which also receives the calculator's report; `logic`; `question`), `merge` to combine verdicts, and `class_report` for the teacher's summary. A grade is a dict: the item's id, whether it is wrong, the first wrong line and the kind.

#%% code
GRADER_SYSTEM = """You grade worked solutions to maths word problems. For each item, decide whether the solution is wrong. A solution is wrong when any line makes a mistake: a calculation done wrongly, an operation that does not match what the question asks, or a number copied wrongly from the question. A wrong final answer always means a wrong solution.

For a wrong solution give the number of the first wrong line and its kind: "slip" for a calculation done wrongly, "operation" for a wrong operation, "misread" for a number copied wrongly from the question.

Answer with one JSON object and nothing else: {"grades": [{"id": <item id>, "wrong": true or false, "first_wrong_line": <line number or null>, "kind": "slip", "operation", "misread" or null}]}, one entry per item."""
HW_LENS_TEXT = {
    "calculator": "Under each item you also get our exact recomputation of every calculation the student wrote. A stated result that differs from the exact one is a slip on that line.",
    "logic": "Check, line by line, that every operation is the one the question calls for: adding where it asks to take away, multiplying where it asks to share, and so on. An operation error can hide behind correct arithmetic.",
    "question": "Re-read the question first. Then compare every number the solution takes from the question with the question itself. A number copied wrongly is a misread, even if every calculation after it is right.",
}
GRADES_SCHEMA = {"type": "object", "required": ["grades"], "properties": {"grades": {"type": "array", "items": {
    "type": "object", "required": ["id", "wrong"], "properties": {"id": {"type": "integer"}, "wrong": {"type": "boolean"},
                                                                  "first_wrong_line": {"type": ["integer", "null"]},
                                                                  "kind": {"enum": ["slip", "operation", "misread", None]}}}}}}


def render_items(ids, with_calc=False):
    """The text a grader reads: each item's question, numbered solution and final answer."""
    out = []
    for i in ids:
        s = SUB_BY_ID[i]
        block = (f"### item {i}\nQuestion: {s['question']}\nSolution:\n" + "\n".join(f"  {n}. {ln}" for n, ln in enumerate(s["lines"], 1))
                 + f"\nFinal answer: {s['final']}")
        if with_calc:
            issues = CALC_FLAGS[i]
            block += "\nExact recomputation: " + ("; ".join(f"line {n}: {e} = {st} is written, the exact result is {ex}" for n, e, st, ex in issues)
                                                  if issues else "every written calculation is right")
        out.append(block)
    return "\n\n".join(out)

show_def(render_items)
print(f"[grader] instruction {len(GRADER_SYSTEM.split())} words; one item renders as about {est_tokens(render_items([1]))} tokens; "
      f"all 600 as about {est_tokens(render_items(sorted(SUB_BY_ID))):,}")

#%% code
class HomeworkKit:
    """The grading job's vocabulary for plans, bound to one run, with a trace of every verdict."""
    STRIDE = 100

    def __init__(self, run, number=0):
        self.run, self.offset = run, self.STRIDE * number
        self.trace = {"graded": [], "rechecked": []}
        self.lock = threading.Lock()

    def _grades(self, obj, ids):
        said = {g.get("id"): g for g in (obj or {}).get("grades", []) if isinstance(g, dict)}
        return [{"id": i, "wrong": said[i].get("wrong") if i in said else None,
                 "first_wrong_line": said.get(i, {}).get("first_wrong_line"), "kind": said.get(i, {}).get("kind")} for i in ids]

show_def(HomeworkKit)

#%% code
@method_of(HomeworkKit)
def grade(self, ids, sample=0, model="worker"):
    ids = list(ids)[:40]
    obj = self.run.agent(data=render_items(ids), system=GRADER_SYSTEM, schema=GRADES_SCHEMA, model=model, label=f"grade:{ids[0]}#{sample}",
                         role="grade", sample=self.offset + sample)
    out = self._grades(obj, ids)
    with self.lock:
        self.trace["graded"] += out
    return out


@method_of(HomeworkKit)
def recheck(self, ids, lens="calculator", sample=0, model="judge"):
    ids = list(ids)[:40]
    if not ids:
        return []
    obj = self.run.agent(data=render_items(ids, with_calc=lens == "calculator"), system=GRADER_SYSTEM + "\n\n" + HW_LENS_TEXT[lens],
                         schema=GRADES_SCHEMA, model=model, label=f"recheck:{lens}:{ids[0]}#{sample}", role="recheck", sample=self.offset + sample)
    out = [dict(g, lens=lens) for g in self._grades(obj, ids)]
    with self.lock:
        self.trace["rechecked"] += out
    return out


def merge_grades(*lists):
    """One grade per item: wrong if most verdicts that answered say wrong; line and kind from the most common answer."""
    by = collections.defaultdict(list)
    for g in (g for l in lists for g in (l or []) if g and g.get("wrong") is not None):
        by[g["id"]].append(g)
    out = {}
    for i, gs in by.items():
        wrong = sum(g["wrong"] for g in gs) * 2 > len(gs)
        lines = collections.Counter(g["first_wrong_line"] for g in gs if g["wrong"] and g["first_wrong_line"])
        kinds = collections.Counter(g["kind"] for g in gs if g["wrong"] and g["kind"])
        out[i] = {"id": i, "wrong": wrong, "first_wrong_line": lines.most_common(1)[0][0] if wrong and lines else None,
                  "kind": kinds.most_common(1)[0][0] if wrong and kinds else None}
    return [out[i] for i in sorted(out)]

show_def(HomeworkKit.grade, HomeworkKit.recheck, merge_grades)

#%% code
CLASS_REPORT_SYSTEM = """You are a maths teacher's assistant. You get the grading of a class's homework: how many solutions were wrong, the kinds of mistake, and the lines where they happened. Write a short report for the teacher, at most 150 words: what went wrong most often, and what to practise next. Answer with one JSON object and nothing else: {"report": "..."}."""


@method_of(HomeworkKit)
def class_report(self, grades, model="lead"):
    kinds = collections.Counter(g["kind"] for g in grades if g["wrong"])
    summary = (f"{len(grades)} solutions graded, {sum(g['wrong'] for g in grades)} wrong. Mistakes by kind: "
               + ", ".join(f"{k}: {n}" for k, n in kinds.most_common()))
    obj = self.run.agent(data=summary, system=CLASS_REPORT_SYSTEM, schema={"type": "object", "required": ["report"]}, model=model,
                         label="class report", role="report", sample=self.offset)
    return {"grades": grades, "report": (obj or {}).get("report", "")}


@method_of(HomeworkKit)
def names(self):
    run, off = self.run, self.offset

    def agent(prompt="", **kw):
        kw["sample"] = off + int(kw.get("sample", 0))
        return run.agent(prompt, **kw)
    return {"agent": agent, "parallel": run.parallel, "pipeline": run.pipeline, "phase": run.phase, "log": run.log,
            "budget": lambda: budget_left(run.llm), "items": sorted(SUB_BY_ID), "batches": batches, "flatten": flatten,
            "grade": self.grade, "recheck": self.recheck, "merge": merge_grades, "class_report": self.class_report,
            "calculator_flags": lambda i: len(CALC_FLAGS.get(i, [])), "LENSES": list(HW_LENS_TEXT), "MODELS": sorted(MODELS)}

show_def(HomeworkKit.class_report, HomeworkKit.names)

#%% md
**Scoring a grading.** **`hw_score(grades)`** compares each grade with the key: was *wrong or right* decided correctly, and for the wrong solutions that were caught, were the first wrong line and the kind right? An item with no grade counts as a mistake.

#%% code
def hw_score(grades):
    """Accuracy of the wrong/right decision over all 600, recall and precision of 'wrong', and line and kind accuracy on caught items."""
    g = {x["id"]: x for x in grades if x and x.get("wrong") is not None}
    right = [i for i in HW_KEY if i in g and g[i]["wrong"] == HW_KEY[i]["wrong"]]
    caught = [i for i in HW_KEY if HW_KEY[i]["wrong"] and i in g and g[i]["wrong"]]
    said_wrong = [i for i in g if g[i]["wrong"]]
    return {"accuracy": len(right) / len(HW_KEY), "recall": len(caught) / sum(k["wrong"] for k in HW_KEY.values()),
            "precision": len(caught) / max(1, len(said_wrong)), "graded": len(g),
            "line": sum(g[i]["first_wrong_line"] == HW_KEY[i]["first_wrong"] for i in caught) / max(1, len(caught)),
            "kind": sum(g[i]["kind"] == HW_KEY[i]["kind"] for i in caught) / max(1, len(caught)),
            **{f"recall_{k}": sum(1 for i in caught if HW_KEY[i]["kind"] == k) / HW_WRONG_PER_KIND for k in HW_KINDS}}

show_def(hw_score)
perfect = hw_score([{"id": i, "wrong": k["wrong"], "first_wrong_line": k["first_wrong"], "kind": k["kind"]} for i, k in HW_KEY.items()])
calc_only = hw_score([{"id": i, "wrong": bool(CALC_FLAGS[i]), "first_wrong_line": CALC_FLAGS[i][0][0] if CALC_FLAGS[i] else None,
                       "kind": "slip" if CALC_FLAGS[i] else None} for i in HW_KEY])
print(f"[score] the key graded against itself: accuracy {perfect['accuracy']:.2f}, line {perfect['line']:.2f}, kind {perfect['kind']:.2f}")
print(f"[score] the calculator alone: accuracy {calc_only['accuracy']:.2f}, recall of wrong {calc_only['recall']:.2f} "
      f"(slips {calc_only['recall_slip']:.2f}, operations {calc_only['recall_operation']:.2f}, misreads {calc_only['recall_misread']:.2f}), "
      f"precision {calc_only['precision']:.2f}")

#%% md
**Stand-ins for smoke runs.** The scripted grader reads the key, like every stand-in before it. To give the position test something to find in a smoke run, the single grader's stand-in is right less often the more items it has already graded in its conversation; fresh graders are right at a constant rate. This is an invented shape, there only so the code below runs in every mode.

#%% code
@SCRIPTED.register
def _grader(model, messages, params):
    if not messages[0]["content"].startswith("You grade worked solutions"):
        return None
    text = messages[-1]["content"]
    if text.startswith("Your answer does not match"):
        return '{"grades": []}'
    seen = sum(m["content"].count("### item ") for m in messages[:-1] if m["role"] == "user")
    lens_bonus = 0.1 if "exact recomputation" in messages[0]["content"].lower() or "Re-read the question" in messages[0]["content"] else 0.0
    out = []
    for j, i in enumerate(int(x) for x in re.findall(r"^### item (\d+)$", text, re.M)):
        p = min(0.97, 0.9 + lens_bonus - 0.0006 * (seen + j))
        right = zlib.crc32(f"{i}:{params.get('sample', 0)}:{len(messages)}".encode()) % 1000 / 1000 < p
        k = HW_KEY[i]
        wrong = k["wrong"] if right else not k["wrong"]
        out.append({"id": i, "wrong": wrong, "first_wrong_line": k["first_wrong"] if wrong and k["wrong"] else (1 if wrong else None),
                    "kind": k["kind"] if wrong and k["wrong"] else ("slip" if wrong else None)})
    return json.dumps({"grades": out})


@SCRIPTED.register
def _class_report(model, messages, params):
    if not messages[0]["content"].startswith("You are a maths teacher's assistant"):
        return None
    return json.dumps({"report": "Most mistakes were (scripted stand-in) " + messages[-1]["content"][:120]})

show_def(_grader, _class_report)

#%% md
### One grader, 600 solutions, one conversation

**The single agent.** One grader receives the stack 40 solutions at a time, in one conversation: every earlier batch and every earlier answer stays in its context, as it would for an assistant asked to "keep going". That is fifteen turns, and the context grows to about the size of the whole stack. **H9** asks whether its accuracy falls as it works down the list.

#%% code
def single_grader(ids, model="worker", sample=0, per_turn=40):
    """One conversation grading the ids in order, per_turn at a time; returns grades in order and the context size per turn."""
    model = MODELS.get(model, model)
    messages = [{"role": "system", "content": GRADER_SYSTEM}]
    params = {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": 12000}
    if "JSON mode" in CAN.get(model, ()):
        params["response_format"] = {"type": "json_object"}
    grades, ctx = [], []
    for t, chunk in enumerate(batches(ids, per_turn)):
        messages = messages + [{"role": "user", "content": render_items(chunk)}]
        ctx.append(sum(est_tokens(m["content"]) for m in messages))
        r = FRONT_DOOR.chat(model, messages, tag=f"hw-single:turn{t + 1}", role="grade-single", phase="homework", run_id="hw-single",
                            sample=sample, **params)
        obj = extract_json(r.text) if r.finish != "error" else None
        said = {g.get("id"): g for g in (obj or {}).get("grades", []) if isinstance(g, dict)}
        grades += [{"id": i, "position": len(grades) + j + 1, **{k: said.get(i, {}).get(k) for k in ("wrong", "first_wrong_line", "kind")}}
                   for j, i in enumerate(chunk)]
        messages = messages + [{"role": "assistant", "content": (r.text or "")[:16000]}]
    return grades, ctx

show_def(single_grader)
HW_ORDER = sorted(SUB_BY_ID)
SINGLE, SINGLE_CTX = single_grader(HW_ORDER)
SINGLE_SCORE = hw_score(SINGLE)
print(f"[single] {len(SINGLE_CTX)} turns; context grew from {SINGLE_CTX[0]:,} to {SINGLE_CTX[-1]:,} tokens; "
      f"accuracy {SINGLE_SCORE['accuracy']:.2f}, recall of wrong {SINGLE_SCORE['recall']:.2f}, precision {SINGLE_SCORE['precision']:.2f}")

#%% md
### The workflow, planned by the lead

The lead gets the same kind of page as in S33, written for this job, and the plan language with the homework kit's words. Its plan is checked, rehearsed on a blind stand-in, priced and run exactly as in Part V. Nothing in the runtime knows that the job has changed.

#%% code
HW_API_DOC = """RUNTIME: phase(title), log(message), agent(prompt, schema=None, model="worker", label="", system="", data=None, sample=0),
  parallel([thunk, ...]), pipeline(items, stage, ...), budget()
THE HOMEWORK KIT
  items                        the ids of the 600 solutions
  batches(items, size)         consecutive groups of at most `size` items (a grader reads at most 40)
  grade(batch, sample=0, model="worker")
                               one grader decides wrong or right for each item; a list of grades
  recheck(batch, lens="calculator", sample=0, model="judge")
                               a second reader with one lens: "calculator" (also sees our exact recomputation of every
                               written calculation), "logic" (wrong operations) or "question" (numbers misread from the question)
  calculator_flags(item)       how many written calculations of the item are wrong by exact arithmetic (free, no call)
  merge(list_of_grades, ...)   one grade per item, by majority of the verdicts given
  class_report(grades)         one worker writes the teacher's report; returns {"grades": ..., "report": ...}
  flatten(lists), LENSES, MODELS
A grade is a dict: id, wrong, first_wrong_line, kind. The program must assign class_report(...) to `result`."""
HW_EXAMPLE = """phase("Grade")
grades = flatten(parallel([lambda b=b: grade(b) for b in batches(items, 40)]))
phase("Report")
result = class_report(merge(grades))"""
LEAD_HW_SYSTEM = (LEAD_PROGRAM_SYSTEM.split("THE PLAN LANGUAGE")[0].replace("lead of a code audit", "lead of a homework-grading job")
                  .replace("You never read the code yourself: workers do", "You never grade anything yourself: workers do")
                  + "THE PLAN LANGUAGE\nThe same restricted Python as for any plan: assignments, for loops, if, comprehensions, lambdas, "
                  "small functions and f-strings, no imports, no while, no attribute reads, no names starting with an underscore.\n\n"
                  + HW_API_DOC + "\n\nRULES\n- Billing is per token. Keep the expected cost under half of the budget.\n- Every item must be graded "
                  "at least once.\n- Use the calculator where it helps: it is free and exact, but it only sees slips.\n\nAN EXAMPLE OF THE SYNTAX "
                  "(not a recommendation)\n```python\n" + HW_EXAMPLE + "\n```\n\nAnswer with the program in one ```python block and nothing else.")
HW_JOB = "Grade 600 homework solutions to maths word problems: for each, say whether it is wrong and, if so, where and how."


def hw_page(budget_cents):
    """The scout's page for the homework job."""
    return (f"THE WORK\n- {len(SUB_BY_ID)} solutions, about {est_tokens(render_items(HW_ORDER)):,} tokens in all, about "
            f"{est_tokens(render_items(HW_ORDER)) // len(SUB_BY_ID)} tokens each.\n- The free calculator flags written arithmetic that is wrong in "
            f"{sum(1 for v in CALC_FLAGS.values() if v)} of them.\n\nPRICES AND LIMITS\n- Prices in dollars per million tokens: "
            + price_text(("worker", "fast", "judge", "lead"))
            + f". Billing is per token.\n- A grader reads at most 40 solutions per call.\n- Budget for this job: {budget_cents} cents.")

show_def(hw_page)
print(f"[lead] homework instruction: {len(LEAD_HW_SYSTEM.split())} words; the example passes the whitelist: "
      f"{not check_program(HW_EXAMPLE, HomeworkKit(Run('hw api', run_id='hw-api', llm=FRONT_DOOR)).names())}")

#%% code
@SCRIPTED.register
def _lead_hw(model, messages, params):
    if "lead of a homework-grading job" not in messages[0]["content"][:200]:
        return None
    return ("```python\n"
            'phase("Grade")\n'
            "first = flatten(parallel([lambda b=b: grade(b) for b in batches(items, 40)]))\n"
            "flagged = [g[\"id\"] for g in first if g[\"wrong\"] or calculator_flags(g[\"id\"]) > 0]\n"
            'log(f"{len(flagged)} of {len(first)} solutions flagged for a second look")\n'
            'phase("Recheck with three lenses")\n'
            "second = flatten(parallel([lambda b=b, l=l: recheck(b, l) for b in batches(flagged, 40) for l in LENSES]))\n"
            "final = merge(first + second)\n"
            'phase("Report")\n'
            "result = class_report(final)\n```")


DRY_HW = ScriptedModel()
DRY_HW.register(lambda model, messages, params: json.dumps({"grades": [
    {"id": int(i), "wrong": int(i) % 3 == 0, "first_wrong_line": 1 if int(i) % 3 == 0 else None, "kind": "slip" if int(i) % 3 == 0 else None}
    for i in re.findall(r"^### item (\d+)$", messages[-1]["content"], re.M)]}) if messages[0]["content"].startswith("You grade") else None)
DRY_HW.register(_class_report)
show_def(_lead_hw)
HW_BUDGET = 100
HW_PLAN = LEAD.write_program(HW_JOB, hw_page(HW_BUDGET), sample=0, budget_cents=HW_BUDGET, system=LEAD_HW_SYSTEM, kit_class=HomeworkKit, stand_in=DRY_HW)
print(HW_PLAN["src"])
HW_DECISION = approve(HW_PLAN["estimate"], HW_BUDGET, person=lambda est: est["cents"] <= HW_BUDGET / 2)
print(f"\n[plan] valid after {HW_PLAN['tries']} attempt(s); estimate {HW_PLAN['estimate']['agents']} workers, "
      f"{HW_PLAN['estimate']['cents']:.1f}¢; gate: {HW_DECISION[0]} ({HW_DECISION[1]})")

#%% code
HW_RUN = Run("homework: the lead's plan", HW_JOB, run_id="hw-workflow", llm=job_door(HW_BUDGET), concurrency=32)
HW_KIT = HomeworkKit(HW_RUN)
HW_RESULT = HW_RUN.run_sync(lambda r: run_program(HW_PLAN["src"], HW_KIT))
HW_WORKFLOW = HW_RESULT["grades"] if HW_RESULT else []
FIRST_PASS = merge_grades(HW_KIT.trace["graded"])
WF_SCORE, FIRST_SCORE = hw_score(HW_WORKFLOW), hw_score(FIRST_PASS)
print(f"[workflow] {HW_RUN.status}: {len(HW_RUN.threads)} workers, {full_price(HW_RUN):.1f}¢ at full price")
table([{"arm": "one grader, one conversation", **SINGLE_SCORE}, {"arm": "workflow: first pass only", **FIRST_SCORE},
       {"arm": "workflow: after the lenses", **WF_SCORE}, {"arm": "the calculator alone", **calc_only}],
      [("arm", "grader", ""), ("accuracy", "accuracy", ".2f"), ("recall", "wrong caught", ".2f"), ("precision", "precision", ".2f"),
       ("recall_slip", "slips", ".2f"), ("recall_operation", "operations", ".2f"), ("recall_misread", "misreads", ".2f"),
       ("line", "right line", ".2f"), ("kind", "right kind", ".2f")])
print(f"\n[report] {HW_RESULT.get('report', '') if HW_RESULT else ''}")

#%% md
**H9, the position test.** For each grader, a straight line is fitted to correctness (1 if the item was decided right, 0 if not) against the item's position in the stack, and its slope per 100 items gets a bootstrap interval over items. For the single grader, position is how far down its one conversation the item came. For the workflow it is the same position in the stack, but every batch of 40 went to a fresh worker.

#%% code
def position_slope(correct, n=2000, seed=SEED):
    """(slope per 100 items, 95% low, 95% high) of correctness against position, bootstrapped over items."""
    pos = np.arange(1, len(correct) + 1, dtype=float)
    y = np.array(correct, dtype=float)
    fit = lambda idx: np.polyfit(pos[idx], y[idx], 1)[0] * 100
    rng_ = np.random.default_rng(seed)
    draws = [fit(rng_.integers(0, len(y), len(y))) for _ in range(n)]
    return float(fit(np.arange(len(y)))), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))

show_def(position_slope)
single_g = {g["id"]: g for g in SINGLE}
wf_g = {g["id"]: g for g in HW_WORKFLOW}
correct_single = [single_g.get(i, {}).get("wrong") == HW_KEY[i]["wrong"] for i in HW_ORDER]
correct_wf = [wf_g.get(i, {}).get("wrong") == HW_KEY[i]["wrong"] for i in HW_ORDER]
SLOPE_SINGLE, SLOPE_WF = position_slope(correct_single), position_slope(correct_wf)
print(f"[H9] single grader: {SLOPE_SINGLE[0]:+.3f} accuracy per 100 items (95% {SLOPE_SINGLE[1]:+.3f} to {SLOPE_SINGLE[2]:+.3f})")
print(f"[H9] workflow:      {SLOPE_WF[0]:+.3f} accuracy per 100 items (95% {SLOPE_WF[1]:+.3f} to {SLOPE_WF[2]:+.3f})")
H9_HOLDS = SLOPE_SINGLE[2] < 0 and SLOPE_WF[1] <= 0 <= SLOPE_WF[2]

#%% code
# FIG  accuracy down the stack: one long conversation against fresh workers
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.6), gridspec_kw={"width_ratios": [1.6, 1]})
ax = axes[0]
for corr, colour, label in ((correct_single, C2, "one grader, one conversation"), (correct_wf, C7, "workflow, fresh workers")):
    xs = np.arange(1, len(corr) + 1)
    roll = np.convolve(np.array(corr, dtype=float), np.ones(60) / 60, mode="valid")
    ax.plot(xs[59:], roll, color=colour, lw=1.8, label=label)
ax.set_xlabel("position in the stack")
ax.set_ylabel("accuracy, rolling over 60 items")
ax.set_ylim(0, 1.02)
ax.legend(fontsize=7.5, loc="lower left")
panel(ax, "down the stack")
ax = axes[1]
for x, (s, colour) in enumerate(((SLOPE_SINGLE, C2), (SLOPE_WF, C7))):
    ax.errorbar([x], [s[0]], yerr=[[s[0] - s[1]], [s[2] - s[0]]], fmt="o", color=colour, capsize=5, ms=7)
ax.axhline(0, color=INK, lw=1)
ax.set_xticks([0, 1], ["one grader", "workflow"])
ax.set_xlim(-0.6, 1.6)
ax.set_ylabel("change in accuracy per 100 items")
panel(ax, "fitted slope, 95% interval")
finish(fig, "s59_position", f"Down the stack, one grader's accuracy changed by {SLOPE_SINGLE[0]:+.3f} per 100 items; the workflow's by {SLOPE_WF[0]:+.3f}",
       "correct = the wrong-or-right decision matched the key; rolling mean over 60 items; slopes from a straight-line fit")

#%% md
**Reading FIG {{figures.s59_position}} (s59_position).** Left: accuracy down the stack, as a rolling mean. Right: the fitted slopes. The single grader's accuracy changed by {{hw_run.slope_single|+.3f}} per 100 items (95% interval {{hw_run.slope_single_lo|+.3f}} to {{hw_run.slope_single_hi|+.3f}}); the workflow's by {{hw_run.slope_wf|+.3f}} ({{hw_run.slope_wf_lo|+.3f}} to {{hw_run.slope_wf_hi|+.3f}}). In the table above, the workflow's first pass reached {{hw_run.first_acc|.2f}} accuracy and {{hw_run.wf_acc|.2f}} after the second look, against {{hw_run.single_acc|.2f}} for one grader; by kind, the workflow caught {{hw_run.wf_slip|.2f}} of slips, {{hw_run.wf_operation|.2f}} of operation errors and {{hw_run.wf_misread|.2f}} of misreads. The calculator alone caught {{hw_run.calc_slip|.2f}} of the slips for free and almost none of the operation or misread errors, which is what the logic and question lenses are for.

#%% code
# FIG  which lens catches which kind of error
lens_rows = []
for lens in HW_LENS_TEXT:
    said = {g["id"]: g for g in HW_KIT.trace["rechecked"] if g.get("lens") == lens and g.get("wrong") is not None}
    lens_rows.append([sum(1 for i, g in said.items() if HW_KEY[i]["kind"] == k and g["wrong"]) / max(1, sum(1 for i in said if HW_KEY[i]["kind"] == k))
                      for k in HW_KINDS])
fig, ax = plt.subplots(figsize=(6.4, 3.2))
im = ax.imshow(np.array(lens_rows), cmap="Purples", vmin=0, vmax=1)
ax.grid(False)
for r in range(len(lens_rows)):
    for c in range(len(HW_KINDS)):
        ax.text(c, r, f"{lens_rows[r][c]:.2f}", ha="center", va="center", fontsize=9, color=INK if lens_rows[r][c] < 0.6 else "white")
ax.set_xticks(range(len(HW_KINDS)), HW_KINDS)
ax.set_yticks(range(len(lens_rows)), list(HW_LENS_TEXT))
fig.colorbar(im, ax=ax, fraction=0.04, label="share of that kind called wrong")
used_lenses = [l for l in HW_LENS_TEXT if any(g.get("lens") == l for g in HW_KIT.trace["rechecked"])]
finish(fig, "s59_lenses", f"The second look used {len(used_lenses)} of {len(HW_LENS_TEXT)} lenses: {', '.join(used_lenses) or 'none'}",
       "the second look of the workflow: share of rechecked solutions of each planted kind that the lens called wrong")

#%% md
**Reading FIG {{figures.s59_lenses}} (s59_lenses).** Each row is one lens of the second look, each column one planted kind, and each cell the share of rechecked solutions of that kind the lens called wrong; a row of zeros is a lens the plan never called. A lens that works would be bright in its own column only. In the live run the lead's plan sent the flagged solutions to the calculator lens alone, and that lens called every solution it saw wrong, correct ones included (S64 measures it). That is why accuracy went from {{hw_run.first_acc|.2f}} after the first pass to {{hw_run.wf_acc|.2f}} after the second look. Unlike S41, the narrow second look did not earn its place on this job.

#%% code
save_exp("hw_run", {"single": SINGLE_SCORE, "workflow": WF_SCORE, "first": FIRST_SCORE, "calculator": calc_only,
                    "single_acc": SINGLE_SCORE["accuracy"], "wf_acc": WF_SCORE["accuracy"], "first_acc": FIRST_SCORE["accuracy"],
                    "wf_slip": WF_SCORE["recall_slip"], "wf_operation": WF_SCORE["recall_operation"], "wf_misread": WF_SCORE["recall_misread"],
                    "calc_slip": calc_only["recall_slip"], "slope_single": SLOPE_SINGLE[0], "slope_single_lo": SLOPE_SINGLE[1],
                    "slope_single_hi": SLOPE_SINGLE[2], "slope_wf": SLOPE_WF[0], "slope_wf_lo": SLOPE_WF[1], "slope_wf_hi": SLOPE_WF[2],
                    "h9": H9_HOLDS, "plan": HW_PLAN["src"], "cost_wf": full_price(HW_RUN), "cost_single": round(sum(r["cents"] or 0 for r in FRONT_DOOR.ledger.accounts("run_id", "run_id = ?", ("hw-single",))), 2),
                    "context_last": SINGLE_CTX[-1], "lens_matrix": lens_rows})
results = []
expect("the key graded against itself scores 1 everywhere", perfect["accuracy"] == 1 and perfect["line"] == 1 and perfect["kind"] == 1)
false_alarm = calc_rows[-1]["flagged"] / calc_rows[-1]["n"]
expect("the calculator flags operation and misread errors no more often than correct solutions",
       all(r["flagged"] / r["n"] <= false_alarm + 0.05 for r in calc_rows if r["kind"] in ("operation", "misread")))
expect("the single grader graded every item once, in order", [g["id"] for g in SINGLE] == HW_ORDER)
expect("the workflow graded every item", len(HW_WORKFLOW) == len(HW_ORDER))
