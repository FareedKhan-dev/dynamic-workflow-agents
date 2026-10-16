#%% md
# Part VIII. Same engine, different jobs

**Where this sits.** Everything so far was one job: find bugs in a library. An engine that only does one job is a script. This Part gives the same runtime, the same lead and the same plan language three new jobs, each with its own kit, and one job the engine should refuse to fan out at all. Nothing in Part IV's runtime changes. What changes is the kit, the page the scout writes, and therefore the plan the lead writes.

**By the end of this Part you can**

- build a planted-error benchmark for a new kind of work, with an exact answer key and a leak test;
- measure the "lost in the middle" decay of one agent working down a long list, and compare it with fresh workers;
- reduce ten thousand short texts to a taxonomy with a tree of merges, and score it against hidden labels;
- recognise the jobs where fanning out is the wrong answer, and show it with numbers.

![part8](attachment:part8_map.png)

#%% md
## S59 - Grading 600 homework solutions

**Theory.** The second job is one every teacher knows: a stack of worked solutions to word problems, some right and some wrong, to be graded. The problems come from a public set of grade-school maths word problems (MIT licence, kept in `data/homework/`), each with a reference solution written step by step, with every calculation marked. We take 600 of them and plant one error in 240, of three kinds:

| kind | what changes | what can see it |
|---|---|---|
| **slip** | one result is miscalculated; the expression is right, the answer next to it is not | an exact calculator |
| **operation** | one operation is swapped (+ for −, × for ÷); the arithmetic is then done correctly | reading the logic |
| **misread** | one number from the question is copied wrongly; everything after it is computed correctly | re-reading the question; no calculator can see it |

Each error is **propagated**: every later line that used the changed value is recomputed, as a student who made the mistake would have done, through to the final answer. A **plausibility filter** throws away plants that a student could not plausibly produce: negative quantities, a whole-number answer turning fractional, or an answer more than five times or less than a fifth of the right one.

**In plain terms.** We take correct worked answers, make one realistic mistake in some of them, follow the mistake through to the end, and keep a key of exactly where each mistake is.

**For teams.** A planted-error benchmark is the cheapest way to get an exact answer key for a grading or review task. The work is in making the plants look natural: carry each error through, and filter out anything a person would never write.

#%% code
HW_DIR = DATA / "homework"
HW_ROWS = [json.loads(l) for l in (HW_DIR / "test.jsonl").read_text(encoding="utf-8").splitlines()]
HW_SHA = hashlib.sha256((HW_DIR / "test.jsonl").read_bytes()).hexdigest()
print(f"[homework] {len(HW_ROWS)} problems, file sha256 {HW_SHA[:16]}..., licence: {(HW_DIR / 'LICENSE.md').read_text(encoding='utf-8').splitlines()[0]}")
print(f"[homework] the first problem:\n  {HW_ROWS[0]['question']}\n  reference solution:\n    " + HW_ROWS[0]["answer"].replace("\n", "\n    "))

#%% md
**Reading a reference solution.** Each line may carry calculator notes such as `<<16-3-4=9>>`, which record the exact expression and its result; the last line is the final answer after `####`. **`hw_parse(row)`** returns the lines, the calculator steps with the line each sits on, and the final answer. **`exact(expr)`** evaluates an arithmetic expression exactly, with fractions instead of floating point, and refuses anything that is not plain arithmetic.

#%% code
from fractions import Fraction

CALC_NOTE = re.compile(r"<<([^<>=]+)=([^<>]+)>>")
ARITH = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}


def exact(expr):
    """The exact value of + - * / arithmetic on numbers, as a Fraction, or None."""
    try:
        tree = ast.parse(expr.replace(",", "").replace("x", "*").strip(), mode="eval").body
    except SyntaxError:
        return None

    def ev(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
            return Fraction(str(n.value))
        if isinstance(n, ast.BinOp) and type(n.op) in ARITH:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Div) and b == 0:
                raise ZeroDivisionError
            return ARITH[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise ValueError(type(n).__name__)
    try:
        return ev(tree)
    except (ValueError, ZeroDivisionError, TypeError, RecursionError):
        return None


def show_num(v):
    """A Fraction written the way a student would write it."""
    return str(v.numerator) if v.denominator == 1 else f"{float(v):.2f}".rstrip("0").rstrip(".")


def hw_parse(row):
    """(lines, calculator steps, final answer) of a reference solution."""
    lines = row["answer"].split("\n")
    steps = [{"line": i, "expr": m.group(1), "result": m.group(2).strip()} for i, ln in enumerate(lines[:-1]) for m in CALC_NOTE.finditer(ln)]
    return lines[:-1], steps, lines[-1].replace("####", "").strip().replace(",", "")

show_def(exact, show_num, hw_parse)
usable = [r for r in HW_ROWS if hw_parse(r)[1] and all(exact(s["expr"]) is not None for s in hw_parse(r)[1])]
print(f"[parse] {len(usable)} of {len(HW_ROWS)} solutions have calculator steps that are all plain arithmetic")
print(f"[exact] 16-3-4 = {exact('16-3-4')}; 7/2 = {exact('7/2')}; 2**10 = {exact('2**10')}; __import__ = {exact('__import__')}")

#%% md
**Planting one error.** **`hw_plant(row, kind, rng)`** picks a step that can carry the kind of error, changes it, rewrites the visible line to match (the expression as the student wrote it, and the result after it, thousands commas included), then walks down the later steps and recomputes every one that used a changed value. A first version missed results written with commas, such as `$15,000`: it swapped the operation but left the old result on the line, which turned an operation error into a visible slip with the wrong label in the key. The calculator below caught it, by flagging "operation" solutions more often than correct ones. It refuses, by returning `None`, whenever the result would not be plausible, and also when a changed value also appears in the question: then a later use of that number could be the question's own constant rather than the carried result, and the propagation would be guesswork.

#%% code
SWAP_OP = {"+": "-", "-": "+", "*": "/", "/": "*"}
SHOWN_OP = {"+": r"\+", "-": "[-−]", "*": "[*x×]", "/": "[/÷]"}


def hw_tokens(expr):
    return re.findall(r"\d+(?:\.\d+)?|[-+*/()]", expr.replace(",", "").replace(" ", ""))


def digits_pattern(t):
    """A number as a pattern that also matches it written with thousands commas."""
    whole, _, frac = t.partition(".")
    return ",?".join(whole) + (r"\." + frac if frac else "")


def shown_span(line, expr):
    """(start, end) of the expression as written in the visible text before its calculator note, or None."""
    toks = hw_tokens(expr)
    if not toks or "(" in toks or ")" in toks:
        return None
    pat = r"\s*".join(digits_pattern(t) if t[0].isdigit() else SHOWN_OP[t] for t in toks)
    head = line[:line.find("<<")] if "<<" in line else line
    found = list(re.finditer(pat, head))
    return (found[-1].start(), found[-1].end()) if found else None


def nudge(v, rng):
    """A plausible wrong value near a right one: off by 1, 2 or 10, or its last two digits swapped."""
    opts = []
    if v.denominator == 1:
        n = v.numerator
        opts = [n + d for d in (1, -1, 2, -2, 10, -10)]
        if abs(n) >= 10 and str(abs(n))[-1] != str(abs(n))[-2]:
            s = str(abs(n))
            opts.append(int(s[:-2] + s[-1] + s[-2]))
    else:
        opts = [v + Fraction(1, 2), v - Fraction(1, 2)]
    opts = [Fraction(o) for o in opts if Fraction(o) != v and Fraction(o) >= 0]
    return rng.choice(opts) if opts else None

show_def(hw_tokens, digits_pattern, shown_span, nudge)

#%% code
def hw_plant(row, kind, rng):
    """(visible lines, final answer, first wrong line, kind) with one planted error, or None when no plausible plant exists."""
    lines, steps, final = hw_parse(row)
    lines = list(lines)
    q_nums = set(re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?![\w.])", row["question"].replace(",", "")))
    ok = lambda s: exact(s["expr"]) is not None
    if kind == "slip":
        cand = [k for k, s in enumerate(steps) if ok(s)]
    elif kind == "operation":
        cand = [k for k, s in enumerate(steps) if ok(s) and any(t in SWAP_OP for t in hw_tokens(s["expr"])[1:]) and shown_span(lines[s["line"]], s["expr"])]
    else:
        cand = [k for k, s in enumerate(steps) if ok(s) and set(hw_tokens(s["expr"])) & q_nums and shown_span(lines[s["line"]], s["expr"])]
    if not cand:
        return None
    k = rng.choice(cand)
    s, toks = steps[k], hw_tokens(steps[k]["expr"])
    old = exact(s["expr"])
    if kind == "slip":
        new_toks, new = toks, nudge(old, rng)
    elif kind == "operation":
        i = rng.choice([i for i, t in enumerate(toks) if t in SWAP_OP and i > 0])
        new_toks = toks[:i] + [SWAP_OP[toks[i]]] + toks[i + 1:]
        new = exact("".join(new_toks))
    else:
        i = rng.choice([i for i, t in enumerate(toks) if t in q_nums])
        alt = nudge(Fraction(toks[i]), rng)
        new_toks = toks[:i] + [show_num(alt)] + toks[i + 1:] if alt is not None else toks
        new = exact("".join(new_toks))
    if new is None or new == old or new < 0:
        return None
    changed = {show_num(old): show_num(new)}

    def rewrite(step, new_toks, new):
        ln = lines[step["line"]]
        span = shown_span(ln, step["expr"])
        note, new_note = f"<<{step['expr']}={step['result']}>>", f"<<{''.join(new_toks)}={show_num(new)}>>"
        at = ln.find(note) + len(note)
        shown = re.match(r"\s*\$?\s*(\d[\d,]*(?:\.\d+)?)", ln[at:])        # the result as the student wrote it, commas and all
        if shown and shown.group(1).replace(",", "") == step["result"].replace(",", ""):
            text = show_num(new)
            if "," in shown.group(1) and "." not in text:
                text = f"{int(text):,}"
            ln = ln[:at + shown.start(1)] + text + ln[at + shown.end(1):]
        elif shown is None or shown.group(1).replace(",", "") != step["result"].replace(",", ""):
            return False                                       # the visible result cannot be found: no clean rewrite
        ln = ln.replace(note, new_note, 1)
        if span and new_toks != hw_tokens(step["expr"]):
            shown = ln[span[0]:span[1]]
            text = (" " if " " in shown else "").join(new_toks)
            ln = ln[:span[0]] + (text.replace("*", "x") if "x" in shown else text) + ln[span[1]:]
        lines[step["line"]] = ln
        return True

    if not rewrite(s, new_toks, new):
        return None
    for s2 in steps[k + 1:]:
        t2 = hw_tokens(s2["expr"])
        n2 = [changed.get(t, t) for t in t2]
        if n2 == t2:
            continue
        v2 = exact("".join(n2))
        if v2 is None or v2 < 0:
            return None
        if v2 != exact(s2["expr"]):                        # a change can cancel out, as in x * 0; then nothing more moves
            changed[show_num(exact(s2["expr"]))] = show_num(v2)
        if not rewrite(s2, n2, v2):
            return None
    if set(changed) & q_nums or final not in changed or changed[final] == final:
        return None
    f_old, f_new = Fraction(final), Fraction(changed[final])
    if (f_old.denominator == 1 and f_new.denominator != 1) or (f_old > 0 and not (f_old / 5 <= f_new <= 5 * f_old)):
        return None
    return [CALC_NOTE.sub("", ln) for ln in lines], changed[final], s["line"] + 1, kind

show_def(hw_plant)
demo_row = next(r for r in usable if all(hw_plant(r, k, random.Random(f"{SEED}:demo:{k}")) for k in ("slip", "operation", "misread")))
print(f"[plant] {demo_row['question']}")
for kind in ("slip", "operation", "misread"):
    out = hw_plant(demo_row, kind, random.Random(f"{SEED}:demo:{kind}"))
    print(f"--- {kind}" + (f": first wrong line {out[2]}, final answer {hw_parse(demo_row)[2]} -> {out[1]}" if out else ": no plausible plant"))
    if out:
        print("    " + "\n    ".join(out[0]))

#%% md
**The 600 submissions.** **`build_submissions()`** draws 600 usable problems with the seed, plants 80 errors of each kind in 240 of them, and leaves 360 correct. Every problem is tried with every kind first, so the draw knows which problems can carry which error. The order of the 600 is shuffled, so wrong solutions are spread evenly down the stack, which matters for the position test of H9.

#%% code
HW_N, HW_WRONG_PER_KIND = 600, 80
HW_KINDS = ["slip", "operation", "misread"]


def build_submissions():
    """600 submissions, 80 of each error kind and 360 correct, shuffled; and how many plants each kind could make."""
    rng_ = random.Random(SEED)
    pool = sorted(usable, key=lambda r: hashlib.sha256(r["question"].encode()).hexdigest())
    rng_.shuffle(pool)
    can = {kind: {i for i, r in enumerate(pool) if hw_plant(r, kind, random.Random(f"{SEED}:{i}:{kind}"))} for kind in HW_KINDS}
    chosen, used = [], set()
    for kind in sorted(HW_KINDS, key=lambda k: len(can[k])):          # the scarcest kind chooses first
        picks = [i for i in sorted(can[kind]) if i not in used][:HW_WRONG_PER_KIND]
        used |= set(picks)
        for i in picks:
            vis, fin, first, _ = hw_plant(pool[i], kind, random.Random(f"{SEED}:{i}:{kind}"))
            chosen.append({"question": pool[i]["question"], "lines": vis, "final": fin, "wrong": True, "first_wrong": first, "kind": kind})
    for i in [i for i in range(len(pool)) if i not in used][:HW_N - len(chosen)]:
        lines, _, fin = hw_parse(pool[i])
        chosen.append({"question": pool[i]["question"], "lines": [CALC_NOTE.sub("", ln) for ln in lines], "final": fin,
                       "wrong": False, "first_wrong": None, "kind": None})
    rng_.shuffle(chosen)
    for n, sub in enumerate(chosen, 1):
        sub["id"] = n
    return chosen, {k: len(v) for k, v in can.items()}

show_def(build_submissions)
SUBMISSIONS, PLANTABLE = build_submissions()
HW_KEY = {s["id"]: {k: s[k] for k in ("wrong", "first_wrong", "kind")} for s in SUBMISSIONS}
print(f"[submissions] {len(SUBMISSIONS)} built; wrong {sum(s['wrong'] for s in SUBMISSIONS)}: "
      + ", ".join(f"{k} {sum(s['kind'] == k for s in SUBMISSIONS)}" for k in HW_KINDS))
print(f"[plantable] of {len(usable)} usable problems, plausible plants exist for: " + ", ".join(f"{k} {v}" for k, v in PLANTABLE.items()))
key_bytes = (DATA / "homework" / "answer_key.json").write_text(json.dumps(HW_KEY, indent=1), encoding="utf-8")
print(f"[key] answer key written to {rel(DATA / 'homework' / 'answer_key.json')}: wrong or not, first wrong line, kind, for each of 600")

#%% code
# FIG  the three kinds of planted error, with one example of each
fig, axes = plt.subplots(1, 2, figsize=(10.8, 3.8), gridspec_kw={"width_ratios": [1, 2.2]})
ax = axes[0]
ax.bar(HW_KINDS, [PLANTABLE[k] for k in HW_KINDS], color=[C2, C7, C4], alpha=0.35, label="problems that can carry it")
ax.bar(HW_KINDS, [sum(s["kind"] == k for s in SUBMISSIONS) for k in HW_KINDS], color=[C2, C7, C4], label="planted in the 600")
ax.set_ylabel("problems")
ax.legend(fontsize=7.5)
panel(ax, "plausible plants per kind")
ax = axes[1]
ax.axis("off")
y = 0.98
for kind, colour in zip(HW_KINDS, (C2, C7, C4)):
    ex = next(s for s in SUBMISSIONS if s["kind"] == kind and len(s["lines"]) <= 4 and max(len(l) for l in s["lines"]) < 95)
    ax.text(0, y, f"{kind}: line {ex['first_wrong']} is wrong; final answer {ex['final']}", fontsize=8.5, weight="bold", color=colour,
            transform=ax.transAxes, va="top")
    y -= 0.07
    for i, ln in enumerate(ex["lines"], 1):
        ax.text(0.02, y, f"{i}. {ln[:110]}", fontsize=7.4, transform=ax.transAxes, va="top",
                color=INK if i == ex["first_wrong"] else INK2, weight="bold" if i == ex["first_wrong"] else "normal")
        y -= 0.06
    y -= 0.04
finish(fig, "s59_error_kinds", "Three kinds of planted error, each carried through to the final answer",
       f"left: how many of the {len(usable)} usable problems can carry each kind plausibly; right: one planted example of each, the wrong line in bold")

#%% md
**Reading FIG {{figures.s59_error_kinds}} (s59_error_kinds).** Left: of the {{homework.usable}} usable problems, {{homework.plantable_slip}} can carry a plausible slip, {{homework.plantable_operation}} a swapped operation and {{homework.plantable_misread}} a misread number; 80 of each were planted. Right: one planted solution of each kind, with the first wrong line in bold. Every line after it is consistent with the mistake, exactly as a student's would be, which is what makes the operation and misread errors hard: each line, checked on its own, is correct arithmetic.

#%% md
**A leak test, as in S3.** If wrong solutions could be told apart from right ones by something other than their mathematics, such as their length or the shape of their numbers, a grader could score well without understanding anything. Three trivial features are tested: the number of lines, the number of characters, and whether any line contains a decimal point. Each is scored as a classifier of "wrong" with the AUROC of S2, where 0.5 means it tells nothing.

#%% code
def hw_features(s):
    return {"lines": len(s["lines"]), "characters": sum(len(l) for l in s["lines"]),
            "has a decimal": float(any(re.search(r"\d\.\d", l) for l in s["lines"]))}

show_def(hw_features)
HW_LEAK = {}
for feat in ("lines", "characters", "has a decimal"):
    pos = [hw_features(s)[feat] for s in SUBMISSIONS if s["wrong"]]
    neg = [hw_features(s)[feat] for s in SUBMISSIONS if not s["wrong"]]
    a = auroc(pos, neg)
    HW_LEAK[feat] = max(a, 1 - a)
    print(f"[leak] {feat:<14} AUROC {HW_LEAK[feat]:.3f}")
save_exp("homework", {"usable": len(usable), "problems": len(HW_ROWS), "n": len(SUBMISSIONS), "wrong": sum(s["wrong"] for s in SUBMISSIONS),
                      **{f"plantable_{k}": v for k, v in PLANTABLE.items()}, "leak": HW_LEAK, "sha256": HW_SHA})
results = []
expect("exact arithmetic refuses anything but arithmetic", exact("__import__") is None and exact("2**10") is None and exact("7/2") == Fraction(7, 2))
expect("80 planted errors of each kind and 360 correct solutions", all(sum(s["kind"] == k for s in SUBMISSIONS) == 80 for k in HW_KINDS)
       and sum(not s["wrong"] for s in SUBMISSIONS) == 360)
expect("every planted error changed the final answer", all(s["final"] != hw_parse(next(r for r in usable if r["question"] == s["question"]))[2]
                                                         for s in SUBMISSIONS if s["wrong"]))
expect("no trivial feature tells wrong from right (AUROC below 0.6)", max(HW_LEAK.values()) < 0.6)
expect("building the submissions twice gives the same 600", build_submissions()[0] == SUBMISSIONS)
