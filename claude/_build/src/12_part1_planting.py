#%% md
## S2 - Planting bugs, and proving each one is real

**Theory.** We need bugs whose location we know exactly, in code nobody has seen with those bugs before. The standard way to get them is **mutation**: take correct code and make one small, deliberate change of the kind programmers really make, such as `<` where `<=` was meant, a `- 1` that should not be there, or two arguments passed in the wrong order. Each kind of change is called a **mutation operator**, and the changed program is a **mutant**.

A mutant is not automatically a bug. Sometimes the change makes no difference at all: flipping `<` to `<=` in a comparison that can never see two equal values changes nothing anyone could observe. Such a mutant is called **equivalent**, and counting it as a bug would punish an agent for correctly saying "this is fine". So we use a **proof rule**: a mutant becomes a planted bug only if at least one of the file's own doctest examples fails because of it. The failing example is the proof. It is also something we can show a reader: here is the input, here is what the code should return, here is what it returns now.

Two more rules keep the bugs fair. A mutant that makes the examples **hang** is thrown away, because an agent testing its own guess would hang too. A mutant that breaks **most** of a file's examples is thrown away as well: we call the share of examples a bug breaks its **loudness**, and we keep only quiet bugs (at most 40%). A loud bug would be found by anybody, and in S3 hiding all its failing examples would leave its file suspiciously bare.

**In plain terms.** We make one small typo-like change in a function, run the function's own examples, and keep the change only if some example now gives a wrong answer, but not if almost every example does.

**For teams.** Seeded mutants are how you can measure a code-review process at all, human or automated: plant a known number of real defects, run the process, and count. Without a known denominator, "the reviewer found 12 bugs" says nothing about how many it missed.

![planting](attachment:planting.png)

#%% md
**`Edit`** is one proposed change: a file, a line, the exact characters to replace, what replaces them, which operator made it and which function it sits in. Every operator below returns a list of these, and nothing touches a file until one is applied.

#%% code
@dataclass
class Edit:
    path: str          # which file
    line: int          # 1-based line in the original file
    col0: int          # first character replaced (a character offset, not a byte offset)
    col1: int          # one past the last character replaced
    old: str           # the text that was there
    new: str           # the text that replaces it
    operator: str      # which mutation operator proposed it
    function: str      # the function it sits in, such as "bisect_left" or "Graph.add_edge"

show_def(Edit)

#%% md
The syntax tree reports column positions in **bytes**, while a Python string is indexed in **characters**, and the two differ as soon as a line holds an accented letter or a symbol. **`char_col`** converts one to the other. Without it an edit on a line such as `# naïve` would cut a character in half.

#%% code
def char_col(line, byte_col):
    """Character offset of a byte offset within one line."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "ignore"))

show_def(char_col)
print(f"[cols] byte 9 of 'x = \"é\" < y' is character {char_col('x = \"é\" < y', 9)}")

#%% md
**`function_spans(tree)`** maps every function to its line range and qualified name (`Graph.add_edge` for a method), and **`enclosing(spans, line)`** finds the innermost function around a line. Every edit records its function this way, and so does the scorer in S4.

#%% code
def function_spans(tree):
    """[(first_line, last_line, qualified_name)] for every function, methods named Class.method."""
    spans = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = prefix + child.name
                spans.append((child.lineno, child.end_lineno, name))
                walk(child, name + ".")
            elif isinstance(child, ast.ClassDef):
                walk(child, prefix + child.name + ".")
            else:
                walk(child, prefix)
    walk(tree, "")
    return spans


def enclosing(spans, line):
    """Qualified name of the innermost function containing line, or None."""
    best = None
    for a, b, name in spans:
        if a <= line <= b and (best is None or a >= best[0]):
            best = (a, b, name)
    return best[2] if best else None

show_def(function_spans, enclosing)

#%% md
**`make_edit`** is the one place where an operator turns a syntax-tree node into an `Edit`. It insists on a node that fits on a single line, sits inside a function, and sits outside the `__main__` demo block, and it refuses an edit that would not change the text. Every operator below calls it, so those rules hold for all of them.

#%% code
def make_edit(ctx, node, old_span, new_text, operator):
    """An Edit replacing the characters of old_span (byte columns from the tree) on node's line, or None."""
    line_no = node.lineno
    if node.end_lineno != line_no or line_no in ctx["main"]:
        return None
    function = enclosing(ctx["spans"], line_no)
    if function is None:
        return None
    line = ctx["lines"][line_no - 1]
    c0, c1 = char_col(line, old_span[0]), char_col(line, old_span[1])
    old = line[c0:c1]
    if not old or old == new_text:
        return None
    return Edit(ctx["path"], line_no, c0, c1, old, new_text, operator, function)


def context(path, src):
    """Everything the operators need about one file, parsed once."""
    tree = ast.parse(src)
    return {"path": path, "tree": tree, "lines": src.splitlines(), "spans": function_spans(tree),
            "main": main_block_lines(tree)}

show_def(make_edit, context)

#%% md
### The twelve operators

Each operator is a small function from a parsed file to a list of possible edits. They are shown one per cell, each run on a real file of the corpus, so you can see the exact change it proposes. Read them as a catalogue of everyday mistakes.

**1. Flip a comparison.** `<` becomes `<=`, `>` becomes `>=`, and back. This is the classic boundary mistake: the loop runs one step too far, or one step short, or an equal element lands on the wrong side.

#%% code
FLIP = {ast.Lt: "<=", ast.LtE: "<", ast.Gt: ">=", ast.GtE: ">"}
SYMBOL = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">="}


def op_flip_comparison(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.Compare) and len(n.ops) == 1 and type(n.ops[0]) in FLIP:
            if n.left.end_lineno != n.lineno:
                continue
            line = ctx["lines"][n.lineno - 1].encode("utf-8")
            gap = line[n.left.end_col_offset:n.comparators[0].col_offset].decode("utf-8", "ignore")
            sym = SYMBOL[type(n.ops[0])]
            k = gap.find(sym)
            if k < 0:
                continue
            start = n.left.end_col_offset + len(gap[:k].encode("utf-8"))
            e = make_edit(ctx, n, (start, start + len(sym)), FLIP[type(n.ops[0])], "flip comparison")
            if e:
                edits.append(e)
    return edits

show_def(op_flip_comparison)

#%% md
A small helper prints what an operator proposes for one file, so every operator can be seen at work on the same kind of real code.

#%% code
DEMO_FILE = "searches/binary_search.py" if "searches/binary_search.py" in CORPUS else sorted(CORPUS)[0]
DEMO_CTX = context(DEMO_FILE, SOURCES[DEMO_FILE])


def show_edits(edits, k=3):
    """Print the first k proposed edits as before and after."""
    print(f"[op] {len(edits)} possible edits in {DEMO_FILE}")
    for e in edits[:k]:
        line = DEMO_CTX["lines"][e.line - 1] if e.path == DEMO_FILE else SOURCES[e.path].splitlines()[e.line - 1]
        after = line[:e.col0] + e.new + line[e.col1:]
        print(f"    line {e.line:>4} in {e.function}")
        print(f"      before: {line.strip()}")
        print(f"      after : {after.strip()}")

show_def(show_edits)
show_edits(op_flip_comparison(DEMO_CTX))

#%% md
**2. Off by one in a range.** `range(n)` becomes `range(n - 1)`, so the last item is never visited. This is probably the single most common loop bug there is.

#%% code
def op_off_by_one_range(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "range" and 1 <= len(n.args) <= 3:
            stop = n.args[0] if len(n.args) == 1 else n.args[1]
            seg = ast.get_source_segment("\n".join(ctx["lines"]), stop)
            if seg is None or "\n" in seg or isinstance(stop, ast.BoolOp):
                continue
            if isinstance(stop, ast.Constant) and isinstance(stop.value, int):
                new = str(stop.value - 1)
            elif isinstance(stop, (ast.Name, ast.Attribute, ast.Call, ast.Subscript, ast.BinOp)):
                new = f"{seg} - 1"
            else:
                continue
            e = make_edit(ctx, n, (stop.col_offset, stop.end_col_offset), new, "off-by-one range")
            if e:
                edits.append(e)
    return edits

show_def(op_off_by_one_range)
show_edits(op_off_by_one_range(DEMO_CTX))

#%% md
**3. Off by one in a slice.** `items[:k]` becomes `items[:k - 1]` and `items[i:]` becomes `items[i + 1:]`: the slice silently loses an element at one end.

#%% code
def op_off_by_one_slice(ctx):
    edits = []
    src = "\n".join(ctx["lines"])
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice) and n.slice.step is None:
            bound, delta = (n.slice.upper, " - 1") if n.slice.upper is not None else (n.slice.lower, " + 1")
            if bound is None:
                continue
            seg = ast.get_source_segment(src, bound)
            if seg is None or "\n" in seg:
                continue
            new = str(bound.value - 1 if delta == " - 1" else bound.value + 1) \
                if isinstance(bound, ast.Constant) and isinstance(bound.value, int) else seg + delta
            e = make_edit(ctx, n, (bound.col_offset, bound.end_col_offset), new, "off-by-one slice")
            if e:
                edits.append(e)
    return edits

show_def(op_off_by_one_slice)
show_edits(op_off_by_one_slice(DEMO_CTX))

#%% md
**4. Swap plus and minus.** `a + b` becomes `a - b`. In arithmetic code this is the slip of a tired hand, and it is often caught only by an example that exercises that exact line.

#%% code
def _op_between(ctx, n, left, right, mapping, operator):
    """Edit replacing the operator symbol between two sibling nodes on one line."""
    if left.end_lineno != n.lineno or right.lineno != n.lineno:
        return None
    line = ctx["lines"][n.lineno - 1].encode("utf-8")
    gap = line[left.end_col_offset:right.col_offset].decode("utf-8", "ignore")
    for old, new in mapping:
        k = gap.find(old)
        if k >= 0 and gap.strip() == old.strip():
            start = left.end_col_offset + len(gap[:k].encode("utf-8"))
            return make_edit(ctx, n, (start, start + len(old.encode("utf-8"))), new, operator)
    return None


def op_swap_plus_minus(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub)):
            mapping = [("+", "-")] if isinstance(n.op, ast.Add) else [("-", "+")]
            e = _op_between(ctx, n, n.left, n.right, mapping, "swap + and -")
            if e:
                edits.append(e)
    return edits

show_def(_op_between, op_swap_plus_minus)
show_edits(op_swap_plus_minus(DEMO_CTX))

#%% md
**5. Swap `and` and `or`.** A guard that should need both conditions now accepts either one, or the other way round. Logic bugs of this kind survive for a long time because they only show on the combination of inputs nobody tried.

#%% code
def op_swap_and_or(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.BoolOp) and len(n.values) >= 2:
            mapping = [("and", "or")] if isinstance(n.op, ast.And) else [("or", "and")]
            e = _op_between(ctx, n, n.values[0], n.values[1], mapping, "swap and / or")
            if e:
                edits.append(e)
    return edits

show_def(op_swap_and_or)
show_edits(op_swap_and_or(DEMO_CTX))

#%% md
**6. Drop a `not`.** `if not seen:` becomes `if seen:`. The branch now runs exactly when it should not.

#%% code
def op_drop_not(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and n.operand.lineno == n.lineno:
            e = make_edit(ctx, n, (n.col_offset, n.operand.col_offset), "", "drop not")
            if e:
                edits.append(e)
    return edits

show_def(op_drop_not)
show_edits(op_drop_not(DEMO_CTX))

#%% md
**7. The wrong end of a sequence.** `items[0]` becomes `items[-1]` and back: the first element where the last was meant.

#%% code
def op_wrong_index(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if not isinstance(n, ast.Subscript):
            continue
        s = n.slice
        if isinstance(s, ast.Constant) and s.value == 0 and not isinstance(s.value, bool):
            new = "-1"
        elif isinstance(s, ast.UnaryOp) and isinstance(s.op, ast.USub) and isinstance(s.operand, ast.Constant) and s.operand.value == 1:
            new = "0"
        else:
            continue
        e = make_edit(ctx, n, (s.col_offset, s.end_col_offset), new, "wrong index")
        if e:
            edits.append(e)
    return edits

show_def(op_wrong_index)
show_edits(op_wrong_index(DEMO_CTX))

#%% md
**8. A wrong starting value.** `total = 0` becomes `total = 1`, `count = 1` becomes `count = 0`. Accumulators that start one off are a favourite of interview questions for a reason.

#%% code
def op_wrong_constant(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if (isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name)
                and isinstance(n.value, ast.Constant) and type(n.value.value) is int):
            v = n.value.value
            new = "1" if v == 0 else "0" if v == 1 else str(v + 1)
            e = make_edit(ctx, n, (n.value.col_offset, n.value.end_col_offset), new, "wrong start value")
            if e:
                edits.append(e)
    return edits

show_def(op_wrong_constant)
show_edits(op_wrong_constant(DEMO_CTX))

#%% md
**9. Swap two arguments.** `power(base, exponent)` becomes `power(exponent, base)`. Nothing crashes, the types still match, and the answer is quietly wrong.

#%% code
SIMPLE = (ast.Name, ast.Constant, ast.Attribute, ast.Subscript)


def op_swap_args(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if (isinstance(n, ast.Call) and len(n.args) >= 2 and not any(isinstance(a, ast.Starred) for a in n.args)
                and isinstance(n.args[0], SIMPLE) and isinstance(n.args[1], SIMPLE)
                and not (isinstance(n.func, ast.Name) and n.func.id in ("print", "range", "isinstance", "setattr", "getattr"))):
            a, b = n.args[0], n.args[1]
            if a.lineno != n.lineno or b.end_lineno != n.lineno:
                continue
            line = ctx["lines"][n.lineno - 1].encode("utf-8")
            sa = line[a.col_offset:a.end_col_offset].decode("utf-8", "ignore")
            sep = line[a.end_col_offset:b.col_offset].decode("utf-8", "ignore")
            sb = line[b.col_offset:b.end_col_offset].decode("utf-8", "ignore")
            if sa == sb:
                continue
            e = make_edit(ctx, n, (a.col_offset, b.end_col_offset), sb + sep + sa, "swap arguments")
            if e:
                edits.append(e)
    return edits

show_def(op_swap_args)
show_edits(op_swap_args(DEMO_CTX))

#%% md
**10. Return the wrong variable.** `return result` becomes `return items`: the function does its work and then hands back the wrong thing, a mistake that happens when names are similar or code was copied from elsewhere.

#%% code
def op_wrong_return(ctx):
    edits = []
    for fn in ast.walk(ctx["tree"]):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        names = sorted({t.id for t in ast.walk(fn) if isinstance(t, ast.Name) and isinstance(t.ctx, ast.Store)}
                       | {a.arg for a in fn.args.args if a.arg not in ("self", "cls")})
        for r in ast.walk(fn):
            if isinstance(r, ast.Return) and isinstance(r.value, ast.Name):
                others = [x for x in names if x != r.value.id]
                if not others:
                    continue
                pick = others[zlib.crc32(f"{ctx['path']}:{r.lineno}".encode()) % len(others)]   # the same pick every run
                e = make_edit(ctx, r, (r.value.col_offset, r.value.end_col_offset), pick, "wrong return value")
                if e:
                    edits.append(e)
    return edits

show_def(op_wrong_return)
show_edits(op_wrong_return(DEMO_CTX))

#%% md
**11. Remove an early return.** In `if n < 2: return n` the `return` becomes `pass`. A guard or a base case disappears, and the function falls through into code that was never meant to see that input.

#%% code
def op_remove_early_return(ctx):
    edits = []
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.If) and len(n.body) == 1 and isinstance(n.body[0], ast.Return) and not n.orelse:
            r = n.body[0]
            e = make_edit(ctx, r, (r.col_offset, r.end_col_offset), "pass", "remove early return")
            if e:
                edits.append(e)
    return edits

show_def(op_remove_early_return)
show_edits(op_remove_early_return(DEMO_CTX))

#%% md
**12. Change an update.** `total += x` becomes `total -= x`, and `x *= 2` becomes `x += 2`. The running value drifts with every step of the loop.

#%% code
def op_change_update(ctx):
    edits = []
    swap = {ast.Add: ("+=", "-="), ast.Sub: ("-=", "+="), ast.Mult: ("*=", "+=")}
    for n in ast.walk(ctx["tree"]):
        if isinstance(n, ast.AugAssign) and type(n.op) in swap:
            e = _op_between(ctx, n, n.target, n.value, [swap[type(n.op)]], "change update")
            if e:
                edits.append(e)
    return edits

show_def(op_change_update)
show_edits(op_change_update(DEMO_CTX))

#%% md
**Applying an edit.** **`apply_edit(src, edit)`** returns the source with one edit made, and refuses to return anything that does not parse. Every edit is a single-line text replacement, so the rest of the file, its comments and its formatting are left exactly as they were.

#%% code
OPERATORS = [op_flip_comparison, op_off_by_one_range, op_off_by_one_slice, op_swap_plus_minus, op_swap_and_or,
             op_drop_not, op_wrong_index, op_wrong_constant, op_swap_args, op_wrong_return,
             op_remove_early_return, op_change_update]


def apply_edit(src, e):
    """The source with one edit applied, or None when the result does not parse."""
    lines = src.split("\n")
    line = lines[e.line - 1]
    if line[e.col0:e.col1] != e.old:
        raise ValueError(f"edit does not match its line: {e}")
    lines[e.line - 1] = line[:e.col0] + e.new + line[e.col1:]
    out = "\n".join(lines)
    try:
        ast.parse(out)
    except SyntaxError:
        return None
    return out

show_def(apply_edit)
first = op_flip_comparison(DEMO_CTX)[0]
print(f"[apply] {first.operator} at {DEMO_FILE}:{first.line}: {first.old!r} -> {first.new!r}; parses: "
      f"{apply_edit(SOURCES[DEMO_FILE], first) is not None}")

#%% md
**How many places could hold a bug?** Every operator runs on every file that may hold one (files imported by other files are excluded, see S1). The counts show that we are choosing a few dozen bugs out of many thousands of possible ones.

#%% code
TARGETS = sorted(p for p in CORPUS if p not in IMPORTED)
SITES = {op.__name__: [] for op in OPERATORS}
for p in TARGETS:
    ctx = context(p, SOURCES[p])
    for op in OPERATORS:
        SITES[op.__name__].extend(op(ctx))
table([{"operator": op.__name__[3:].replace("_", " "), "sites": len(SITES[op.__name__]),
        "files": len({e.path for e in SITES[op.__name__]})} for op in OPERATORS],
      [("operator", "operator", ""), ("sites", "possible edits", ","), ("files", "files with one", ",")])
print(f"[sites] {sum(len(v) for v in SITES.values()):,} possible edits in {len(TARGETS)} files")

#%% md
### The proof rule, applied

**`prove(edit)`** runs the file's examples with the edit applied. It returns the verdict and the evidence: how many examples failed, which ones, and the loudness. The verdicts are `planted` (proven and quiet), `survives` (no example noticed the change, so it may be equivalent), `too loud`, `hangs`, `breaks import` and `flaky`. That last one exists because a few files use random numbers inside their examples: a mutant there can fail an example on one run and pass it on the next. A proof has to repeat exactly, so every `planted` verdict is confirmed by a second run under a different seed (for string hashing and for `random`, as in S1), and a mutant whose failures move between runs is thrown away.

#%% code
def prove(e):
    """Run the file's examples with edit e applied, and classify the mutant."""
    mutated = apply_edit(SOURCES[e.path], e)
    if mutated is None:
        return {"verdict": "does not parse"}
    rep = run_doctests(ORIGINAL, e.path, mutated, timeout=30)
    if not rep.get("ok"):
        return {"verdict": "hangs" if rep.get("error") == "timeout" else "breaks import"}
    failed = [x["line"] for x in rep["examples"] if not x["passed"]]
    loud = len(failed) / max(1, len(rep["examples"]))
    verdict = "survives" if not failed else "too loud" if loud > MAX_LOUDNESS else "planted"
    if verdict == "planted":                                   # a proof must repeat exactly, or it is no proof
        again = run_doctests(ORIGINAL, e.path, mutated, timeout=30, hash_seed=SEED + 7)
        if not again.get("ok") or [x["line"] for x in again["examples"] if not x["passed"]] != failed:
            verdict = "flaky"
    return {"verdict": verdict, "failed": failed, "examples": len(rep["examples"]), "loudness": round(loud, 4)}

show_def(prove)
for e in op_off_by_one_range(DEMO_CTX)[:2] + op_wrong_return(DEMO_CTX)[:1]:
    r = prove(e)
    print(f"[prove] {e.operator:<20} line {e.line:>4}: {r['verdict']:<9} "
          + (f"{len(r['failed'])} of {r['examples']} examples fail (loudness {r['loudness']:.2f})" if 'failed' in r else ""))

#%% md
**Choosing the candidates.** For each operator we pick **one possible edit per file**, shuffle the files with the notebook's seed and spread them over folders, so no folder gets all the bugs of one kind. Picking a file first matters: a long file holds more possible edits than a short one, so picking edits directly would plant bugs mostly in long files. The files also take turns by **length quarter** (the shortest quarter of the corpus, the next, and so on), because the proof rule itself favours long files, which carry more examples. The leak test in S3 checks that the final selection leaves no length signal. Then we prove them in batches, four at a time, until the operator has three times as many quiet, proven candidates as it needs. Three times, because S3 can still reject a candidate: its failing examples must be hideable without breaking the examples around them. Every attempt is recorded, including the rejected ones, because FIG {{figures.s2_proof_rule}} is built from them.

#%% code
LENGTHS = {p: len(SOURCES[p].splitlines()) for p in CORPUS}
CUTS = np.quantile([LENGTHS[p] for p in CORPUS if p not in IMPORTED], [0.25, 0.5, 0.75])
QUARTER = {p: int(np.searchsorted(CUTS, LENGTHS[p], side="right")) for p in CORPUS}   # 0 = shortest quarter


def spread(edits, rng):
    """One random edit per file, files shuffled and interleaved by length quarter and by folder.

    Picking edits uniformly would favour long files, which hold more possible edits; picking a file
    first and then one of its edits gives every file the same chance, whatever its length."""
    by_file = collections.defaultdict(list)
    for e in edits:
        by_file[e.path].append(e)
    picks = [rng.choice(by_file[p]) for p in sorted(by_file)]
    rng.shuffle(picks)
    lanes = collections.defaultdict(list)                 # one lane per (length quarter, folder)
    for e in picks:
        lanes[(QUARTER[e.path], e.path.split("/")[0])].append(e)
    keys = sorted(lanes, key=lambda k: (rng.random(), k))
    out = []
    while any(lanes.values()):
        for q in range(4):                                 # quarters take turns, so short files get their share
            for k in keys:
                if k[0] == q and lanes[k]:
                    out.append(lanes[k].pop())
                    break
    return out


def find_candidates(op_name, want, rng, max_tries=160, batch=8):
    """Proven, quiet candidates for one operator, at most one per file, and the log of every attempt."""
    queue, found, log, used = spread(SITES[op_name], rng), [], [], set()
    while queue and len(found) < want and len(log) < max_tries:
        chunk = []
        while queue and len(chunk) < batch:
            e = queue.pop(0)
            if e.path not in used:
                chunk.append(e)
                used.add(e.path)
        with cf.ThreadPoolExecutor(4) as pool:
            for e, r in zip(chunk, pool.map(prove, chunk)):
                log.append((e, r))
                if r["verdict"] == "planted" and len(found) < want:
                    found.append((e, r))
    return found, log

show_def(spread, find_candidates)

#%% md
**Why pick files first, measured.** The bias is visible with arithmetic alone, before a single test runs. We draw 72 files three ways, 300 times each, and ask how well file length alone would separate the chosen files from the rest. The measure is the **AUROC**: 0.5 means length says nothing, and higher values mean the bugs sit in suspiciously long files. The first way picks edits uniformly from all the possible edits counted above, as a straightforward script would. The second picks files uniformly. The third picks files uniformly within each length quarter, which is what `spread` does.

#%% code
from scipy.stats import ks_2samp, mannwhitneyu


def auroc(pos, neg):
    """Probability that a positive scores above a negative, ties counted as half, folded to be at least 0.5."""
    u = mannwhitneyu(pos, neg, alternative="two-sided").statistic
    a = u / (len(pos) * len(neg))
    return max(a, 1 - a)


def selection_bias(draw, n=72, trials=300, seed=SEED):
    """Mean and 5th to 95th percentile of the length AUROC of n files chosen by draw(rng, n)."""
    rng = random.Random(seed)
    vals = []
    for _ in range(trials):
        chosen = draw(rng, n)
        rest = [LENGTHS[p] for p in TARGETS if p not in chosen]
        vals.append(auroc([LENGTHS[p] for p in chosen], rest))
    return float(np.mean(vals)), float(np.percentile(vals, 5)), float(np.percentile(vals, 95))

show_def(auroc, selection_bias)
ALL_EDITS = [e.path for v in SITES.values() for e in v]
with_sites = sorted(set(ALL_EDITS))


def draw_edits(rng, n):
    chosen = set()
    while len(chosen) < n:
        chosen.add(rng.choice(ALL_EDITS))          # a file with 40 possible edits is 40 times as likely
    return chosen


def draw_files(rng, n):
    return set(rng.sample(with_sites, n))


def draw_quarters(rng, n):
    return set(itertools.chain.from_iterable(rng.sample([p for p in with_sites if QUARTER[p] == q], n // 4) for q in range(4)))


show_def(draw_edits, draw_files, draw_quarters)
BIAS = [{"method": m, **dict(zip(("mean", "low", "high"), selection_bias(d)))}
        for m, d in [("pick edits uniformly", draw_edits), ("pick files uniformly", draw_files),
                     ("pick files per length quarter", draw_quarters)]]
table(BIAS, [("method", "how the 72 files are chosen", ""), ("mean", "length AUROC", ".3f"),
             ("low", "5th pct", ".3f"), ("high", "95th pct", ".3f")])
save_exp("selection_bias", {**{r["method"]: r for r in BIAS}, "uniform_mean": BIAS[0]["mean"]})

#%% md
The first row is the trap. Picking edits uniformly gives a length AUROC around {{selection_bias.uniform_mean|.2f}}: the buggy files would be clearly longer than the rest, and an agent could find them faster by sorting files by size than by reading them. Picking files uniformly removes most of the effect, and balancing the length quarters pins it near 0.5. The proof rule adds a smaller bias of its own (long files carry more examples, so a bug in them is easier to prove quietly), which is why the final selection in S3 also balances quarters.

#%% code
t0 = time.perf_counter()
rng = random.Random(SEED)
CANDIDATES, ATTEMPTS = {}, {}
for op in OPERATORS:
    CANDIDATES[op.__name__], ATTEMPTS[op.__name__] = find_candidates(op.__name__, 3 * N_BUGS_PER_OPERATOR, rng)
    v = collections.Counter(r["verdict"] for _, r in ATTEMPTS[op.__name__])
    print(f"  {op.__name__[3:]:<20} tried {len(ATTEMPTS[op.__name__]):>3}: planted {v['planted']:>2}, survives {v['survives']:>3}, "
          f"too loud {v['too loud']:>3}, hangs {v['hangs']:>2}, flaky {v['flaky']:>2}, breaks import {v['breaks import']:>2}")
print(f"[candidates] {sum(len(c) for c in CANDIDATES.values())} proven, quiet candidates in {time.perf_counter() - t0:.0f} s")

#%% md
### Figure: what the proof rule throws away

#%% code
# FIG  every attempt, by operator and verdict
verdicts = ["planted", "too loud", "survives", "hangs", "flaky", "breaks import"]
colour = {"planted": C3, "too loud": C4, "survives": MUTED, "hangs": C8, "flaky": C5, "breaks import": C7}
ops = [op.__name__ for op in OPERATORS]
verdicts = [v for v in verdicts if any(r.get("verdict") == v for a in ATTEMPTS.values() for _, r in a)]   # drop empty kinds
fig, ax = plt.subplots(figsize=(10.6, 4.4))
left = np.zeros(len(ops))
for v in verdicts:
    vals = np.array([sum(r.get("verdict") == v for _, r in ATTEMPTS[o]) for o in ops], dtype=float)
    ax.barh(range(len(ops)), vals, left=left, color=colour[v], height=0.66, label=v)
    for i, (l, x) in enumerate(zip(left, vals)):
        if x >= 6:
            ax.text(l + x / 2, i, f"{int(x)}", ha="center", va="center", fontsize=7, color="white")
    left += vals
ax.set_yticks(range(len(ops)), [o[3:].replace("_", " ") for o in ops], fontsize=8.5)
ax.invert_yaxis()
ax.set_xlabel("attempts")
ax.legend(ncol=len(verdicts), fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0))
tot = sum(len(a) for a in ATTEMPTS.values())
kept = sum(r.get("verdict") == "planted" for a in ATTEMPTS.values() for _, r in a)
finish(fig, "s2_proof_rule", f"{kept} of {tot} attempted mutants passed the proof rule",
       "green: proven and quiet; grey: no example noticed (possibly equivalent); amber: too loud; red: hangs")

#%% code
def survival_summary():
    """Per operator: the share of attempts no example noticed, and the share too loud to keep."""
    rows = []
    for o in ops:
        v = collections.Counter(r.get("verdict") for _, r in ATTEMPTS[o])
        n = sum(v.values())
        rows.append({"operator": o[3:].replace("_", " "), "attempts": n, "survives": v["survives"] / n,
                     "too_loud": v["too loud"] / n, "planted": v["planted"] / n})
    return rows

show_def(survival_summary)
SURV = sorted(survival_summary(), key=lambda r: -r["survives"])
table(SURV, [("operator", "operator", ""), ("attempts", "attempts", "d"), ("survives", "unnoticed", ".0%"),
             ("too_loud", "too loud", ".0%"), ("planted", "proven and quiet", ".0%")])
save_exp("planting_summary", {"most_unnoticed": SURV[0]["operator"], "most_unnoticed_share": SURV[0]["survives"],
                              "least_unnoticed": SURV[-1]["operator"], "least_unnoticed_share": SURV[-1]["survives"],
                              "loudest": max(SURV, key=lambda r: r["too_loud"])["operator"],
                              "loudest_share": max(r["too_loud"] for r in SURV),
                              "attempts": tot, "candidates": kept, "unnoticed_total": sum(r["survives"] * r["attempts"] for r in SURV)})

#%% md
**Reading FIG {{figures.s2_proof_rule}} (s2_proof_rule).** Each bar is one operator, and its segments say what happened to every mutant we tried. The grey segments are the reason the proof rule exists: these changes went unnoticed by every example in their file, and some of them would not change behaviour at all. Counting them as bugs would have planted defects that may not exist. The operator most often unnoticed was **{{planting_summary.most_unnoticed}}** ({{planting_summary.most_unnoticed_share|.0%}} of its attempts): its changes often land on a case that no example in the file exercises. The least often unnoticed was {{planting_summary.least_unnoticed}} ({{planting_summary.least_unnoticed_share|.0%}}). The amber segments are bugs too loud to be fair, most often from {{planting_summary.loudest}} ({{planting_summary.loudest_share|.0%}} of its attempts), and the few red ones are mutants that turned a loop into an infinite one.

#%% code
save_exp("planting_attempts", {op[3:]: dict(collections.Counter(r.get("verdict") for _, r in ATTEMPTS[op])) for op in ops}
         | {"_total_attempts": tot, "_candidates": kept, "_sites": sum(len(v) for v in SITES.values())})
results = []
expect("every operator has proven candidates", all(len(CANDIDATES[o]) >= N_BUGS_PER_OPERATOR for o in ops))
expect("no candidate is louder than the limit", all(r["loudness"] <= MAX_LOUDNESS for c in CANDIDATES.values() for _, r in c))
expect("every candidate breaks at least one example", all(r["failed"] for c in CANDIDATES.values() for _, r in c))
expect("no candidate sits in a file other files import", all(e.path not in IMPORTED for c in CANDIDATES.values() for e, _ in c))
