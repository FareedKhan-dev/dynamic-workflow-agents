#%% md
## S11 - Probing the models

**Theory.** A capability we have not tested is a capability we should not rely on. Before any experiment, each model in the table gets the same three tiny questions:

- **Does it answer at all?** A one-word reply, with its default settings.
- **Can its thinking be switched off?** The same question with `enable_thinking` set to false, which should come back with no reasoning. Mechanical jobs (tagging a message, formatting a list) do not need a minute of thought, and thinking is billed like any other output, so it costs both time and money.
- **Does JSON mode work?** The same question asking for `{"word": "OK"}`, with the request asking for a JSON object only. Every worker in Part IV answers in JSON, so this one matters most.

The answers set a small table, `CAN`, that later code consults. A worker only asks for JSON mode on a model that passed the JSON probe, and only switches thinking off where the probe showed that works. The probe also records how long each model takes to say one word, which is the floor under every later latency.

**In plain terms.** We ask each model three simple things and write down what it can do and how fast.

**For teams.** Re-run a probe like this whenever a provider updates a model behind an unchanged name. The manifest records the probe dates for exactly that reason.

#%% code
PROBES = {
    "answers":      ({}, "PROBE. Reply with the single word OK."),
    "thinking off": ({"enable_thinking": False}, "PROBE. Reply with the single word OK."),
    "JSON mode":    ({"enable_thinking": False, "response_format": {"type": "json_object"}},
                     'PROBE. Reply with this JSON object and nothing else: {"word": "OK"}'),
}


def passed(name, r):
    """Did reply r pass probe `name`?"""
    if r.finish == "error":
        return False
    if name == "answers":
        return "ok" in r.text.lower()
    if name == "thinking off":
        return "ok" in r.text.lower() and not r.reasoning.strip()
    try:
        return json.loads(r.text.strip().strip("`").removeprefix("json")).get("word", "").upper() == "OK"
    except (ValueError, AttributeError):
        return False


def probe(model):
    """All three probes for one model: what passed, and how long a one-word answer takes."""
    out = {"model": model, "short": model.split("/")[-1]}
    for name, (params, text) in PROBES.items():
        r = FRONT_DOOR.chat(model, [{"role": "user", "content": text}], tag=f"probe:{name}", role="probe",
                            max_tokens=2000, **params)
        out[name] = passed(name, r)
        if name == "answers":
            out.update(seconds=r.seconds, first_byte=r.first_byte, reasoning=len(r.reasoning), error=r.error,
                       quota=quota_line(r), cached=r.cached)
    return out


@SCRIPTED.register
def _probe(model, messages, params):
    text = messages[-1]["content"]
    if not text.startswith("PROBE."):
        return None
    return '{"word": "OK"}' if "JSON object" in text else "OK"

show_def(passed, probe, _probe)

#%% code
with cf.ThreadPoolExecutor(6) as pool:
    PROBE = {p["model"]: p for p in pool.map(probe, list(dict.fromkeys(MODELS.values())))}
CAN = {m: {k for k in PROBES if p[k]} for m, p in PROBE.items()}
rows = [{"model": p["short"], "role": ", ".join(r for r, mm in MODELS.items() if mm == m),
         **{k: "yes" if p[k] else "no" for k in PROBES}, "first_byte": p["first_byte"], "seconds": p["seconds"],
         "reasoning": p["reasoning"]} for m, p in PROBE.items()]
table(rows, [("model", "model", ""), ("role", "role", ""), ("answers", "answers", ""), ("thinking off", "thinking off", ""),
             ("JSON mode", "JSON mode", ""), ("first_byte", "first byte s", ".2f"), ("seconds", "total s", ".2f"),
             ("reasoning", "reasoning chars", "d")])
for m, p in PROBE.items():
    if p["error"]:
        print(f"  [probe] {p['short']}: {p['error'][:100]}")
print(f"[probe] quota after the probe: {PROBE[MODELS['worker']]['quota']}")

#%% code
# FIG  what each model can do, and how long it takes to say OK
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.4), gridspec_kw={"width_ratios": [1.1, 1]})
names = [p["short"] for p in PROBE.values()]
ax = axes[0]
grid = np.array([[1 if p[k] else 0 for k in PROBES] for p in PROBE.values()])
ax.imshow(grid, cmap=matplotlib.colors.ListedColormap([C8, C3]), vmin=0, vmax=1, aspect="auto", alpha=0.85)
for i in range(grid.shape[0]):
    for j in range(grid.shape[1]):
        ax.text(j, i, "yes" if grid[i, j] else "no", ha="center", va="center", fontsize=8, color="white")
ax.set_xticks(range(len(PROBES)), list(PROBES), fontsize=8)
ax.set_yticks(range(len(names)), names, fontsize=8)
ax.grid(False)
panel(ax, "a capability is only used where it passed")
ax = axes[1]
y = np.arange(len(names))
ax.barh(y, [p["seconds"] or 0 for p in PROBE.values()], 0.6, color=C1, label="whole reply")
ax.barh(y, [p["first_byte"] or 0 for p in PROBE.values()], 0.6, color=C7, label="first byte")
for i, p in enumerate(PROBE.values()):
    ax.text((p["seconds"] or 0) + 0.05, i, f"{p['reasoning']} reasoning chars", va="center", fontsize=7, color=INK2)
ax.set_yticks(y, [])
ax.invert_yaxis()
ax.set_xlabel("seconds to answer 'reply OK'")
ax.legend(loc="lower right", fontsize=7.5)
panel(ax, "even a one-word answer comes after reasoning")
finish(fig, "s11_probe", f"{sum(p['answers'] for p in PROBE.values())} of {len(PROBE)} models answer; "
       f"{sum(p['JSON mode'] for p in PROBE.values())} honour JSON mode; "
       f"{sum(p['thinking off'] for p in PROBE.values())} can stop thinking",
       "smoke runs show the scripted stand-in; the committed notebook shows the live probe")

#%% md
**Reading FIG {{figures.s11_probe}} (s11_probe).** The left panel is the capability table every later section consults, and the right panel is the time to say one word. On the live service, {{probe.answers}} of {{probe.models}} models answered, {{probe.json_mode}} honoured JSON mode and {{probe.thinking_off}} could have their thinking switched off. The violet part of each bar is the wait before the first byte arrived; the rest is the model writing, and the label is how much it reasoned before saying "OK". The slowest model took {{probe.slowest_s|.1f}} s to say one word, which is a reminder that a model call is never instant and that fifty of them in a row are minutes, not seconds.

#%% code
save_exp("probe", {"models": len(PROBE), "answers": sum(p["answers"] for p in PROBE.values()),
                   "json_mode": sum(p["JSON mode"] for p in PROBE.values()),
                   "thinking_off": sum(p["thinking off"] for p in PROBE.values()),
                   "slowest_s": max((p["seconds"] or 0) for p in PROBE.values()),
                   "rows": rows, "can": {m: sorted(c) for m, c in CAN.items()}})
results = []
expect("at least four models answer", sum(p["answers"] for p in PROBE.values()) >= 4)
expect("the worker model honours JSON mode", "JSON mode" in CAN[MODELS["worker"]])
expect("the lead model answers", PROBE[MODELS["lead"]]["answers"])

#%% md
## S12 - Structured output, checked and repaired

**Theory.** Every worker in the system answers in JSON, because a plan has to *use* what a worker found: count it, merge it, pass it to the next phase. JSON mode makes a model return syntactically valid JSON, but valid JSON can still have the wrong **shape**: a missing field, a number where a list was promised, a key with a different name. So every structured answer is checked against a **JSON schema**, a small document that says exactly which fields must exist and what type each one has. When the check fails, the worker gets **one repair turn**: the model sees its own answer, the list of what is wrong with it, and is asked to send a corrected version. A second failure is a failure; the worker returns nothing rather than something malformed.

We measure this on a task where the right answer is known exactly. Each model reads a small file and lists its functions with the number of parameters each one takes. The syntax tree gives the true answer, so we can count three things separately: answers with the right shape, answers that needed the repair turn, and answers that are actually correct.

**In plain terms.** We tell the model the exact form we need, check every answer against that form, and give it one chance to fix a mistake.

**For teams.** Shape checking catches a different failure from correctness checking. Report both, or a "100% valid JSON" figure will hide answers that are well formed and wrong.

#%% code
from jsonschema import Draft202012Validator


def extract_json(text):
    """The first JSON object in a reply, tolerating code fences and stray prose around it."""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        pass
    start = t.find("{")
    while start >= 0:
        depth = 0
        for i in range(start, len(t)):
            depth += {"{": 1, "}": -1}.get(t[i], 0)
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except ValueError:
                    break
        start = t.find("{", start + 1)
    return None


def validate(obj, schema):
    """Short, readable messages for everything wrong with obj; an empty list when it fits the schema."""
    if obj is None:
        return ["the reply is not a JSON object"]
    errs = sorted(Draft202012Validator(schema).iter_errors(obj), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or 'top level'}: {e.message[:120]}" for e in errs[:8]]


def repair_message(errors, schema):
    """What the model is told when its answer does not fit."""
    return ("Your answer does not match the required JSON schema. Problems:\n- " + "\n- ".join(errors) +
            "\nSend the corrected JSON object only, no prose. The schema is:\n" + json.dumps(schema))

show_def(extract_json, validate, repair_message)
print(f"[json] {extract_json('Sure! Here it is: ```json' + chr(10) + '{\"a\": [1, 2]}' + chr(10) + '``` hope that helps')}")
print(f"[json] {validate({'a': 'x'}, {'type': 'object', 'required': ['a', 'b'], 'properties': {'a': {'type': 'integer'}}})}")

#%% md
**`ask_json`** puts the three pieces together: ask with JSON mode where the model supports it, parse, validate, and repair once. It returns the object (or `None`), the number of turns used, the errors of the last try, and the last reply, whose timing and token counts later sections record. Part IV's `agent()` grows out of this function.

#%% code
def ask_json(model, system, user, schema, *, tag="", role="", phase="", run_id="", sample=0, thinking=True, max_tokens=8000):
    """(object or None, turns used, last errors, last reply): one call, one schema check, at most one repair turn."""
    params = {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": max_tokens}
    if "JSON mode" in CAN.get(model, ()):
        params["response_format"] = {"type": "json_object"}
    if not thinking and "thinking off" in CAN.get(model, ()):
        params["enable_thinking"] = False
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    r = FRONT_DOOR.chat(model, messages, tag=tag, role=role, phase=phase, run_id=run_id, sample=sample, **params)
    if r.finish == "error":
        return None, 1, [r.error or "error"], r
    obj = extract_json(r.text)
    errors = validate(obj, schema)
    if not errors:
        return obj, 1, [], r
    messages += [{"role": "assistant", "content": r.text[:6000]}, {"role": "user", "content": repair_message(errors, schema)}]
    r2 = FRONT_DOOR.chat(model, messages, tag=tag + ":repair", role=role, phase=phase, run_id=run_id, sample=sample, **params)
    obj2 = extract_json(r2.text) if r2.finish != "error" else None
    errors2 = validate(obj2, schema)
    return (obj2 if not errors2 else None), 2, errors2, r2

show_def(ask_json)

#%% md
**The measurement.** Eight small files, chosen with the notebook's seed among clean files with three to eight functions, go to four models: the worker, the fast model, the judge and the lead. Each model returns `{"functions": [{"name": ..., "parameters": ...}]}`. We record whether the first answer fit the schema, whether the repair rescued it, and whether the final answer matched the syntax tree exactly.

#%% code
FUNCS_SCHEMA = {"type": "object", "required": ["functions"], "additionalProperties": False,
                "properties": {"functions": {"type": "array", "items": {
                    "type": "object", "required": ["name", "parameters"], "additionalProperties": False,
                    "properties": {"name": {"type": "string"}, "parameters": {"type": "integer", "minimum": 0}}}}}}
FUNCS_SYSTEM = ("You read Python source code and list its functions. Answer with one JSON object of the form "
                '{"functions": [{"name": "<function name>", "parameters": <number of parameters>}]}. '
                "List every function defined with def, including methods, in the order they appear. "
                "Count every parameter in the signature, including self and parameters with defaults.")


def true_functions(src):
    """The right answer, from the syntax tree."""
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            a = n.args
            out.append((n.name, len(a.posonlyargs) + len(a.args) + len(a.kwonlyargs) + bool(a.vararg) + bool(a.kwarg)))
    return sorted(out)

show_def(true_functions)
rng = random.Random(SEED)
clean = [p for p in sorted(CORPUS) if p not in {b["path"] for b in ANSWER_KEY} and 3 <= len(true_functions(SOURCES[p])) <= 8
         and len(SOURCES[p]) < 6000]
JSON_FILES = rng.sample(clean, 8)
print(f"[json] {len(JSON_FILES)} files, {sum(len(true_functions(SOURCES[p])) for p in JSON_FILES)} functions to list: "
      + ", ".join(Path(p).name for p in JSON_FILES[:4]) + ", ...")


@SCRIPTED.register
def _funcs(model, messages, params):
    if not messages[0]["content"].startswith("You read Python source code and list its functions"):
        return None
    if messages[-1]["role"] == "user" and messages[-1]["content"].startswith("Your answer does not match"):
        src = messages[1]["content"]
        return json.dumps({"functions": [{"name": n, "parameters": k} for n, k in true_functions(src)]})
    src = messages[-1]["content"]
    fns = true_functions(src)
    if zlib.crc32((model + src[:50]).encode()) % 4 == 0:      # a scripted slip: a wrong type, so the repair has work to do
        return json.dumps({"functions": [{"name": n, "parameters": str(k)} for n, k in fns]})
    return json.dumps({"functions": [{"name": n, "parameters": k} for n, k in fns]})

show_def(_funcs)

#%% code
def json_trial(job):
    model, path = job
    obj, turns, errs, _ = ask_json(model, FUNCS_SYSTEM, SOURCES[path], FUNCS_SCHEMA, tag=f"json:{Path(path).name}",
                                role="json-test", thinking=False)
    got = sorted((f["name"], f["parameters"]) for f in obj["functions"]) if obj else None
    return {"model": model.split("/")[-1], "file": path, "first_try": turns == 1 and obj is not None,
            "repaired": turns == 2 and obj is not None, "valid": obj is not None, "correct": got == true_functions(SOURCES[path])}

show_def(json_trial)
JSON_MODELS = [MODELS[r] for r in ("worker", "fast", "judge", "lead")]
with cf.ThreadPoolExecutor(8) as pool:
    JSONT = list(pool.map(json_trial, [(m, p) for m in JSON_MODELS for p in JSON_FILES]))
agg = []
for m in JSON_MODELS:
    rs = [r for r in JSONT if r["model"] == m.split("/")[-1]]
    agg.append({"model": m.split("/")[-1], "first_try": sum(r["first_try"] for r in rs) / len(rs),
                "after_repair": sum(r["valid"] for r in rs) / len(rs), "correct": sum(r["correct"] for r in rs) / len(rs)})
table(agg, [("model", "model", ""), ("first_try", "valid at first try", ".0%"), ("after_repair", "valid after repair", ".0%"),
            ("correct", "exactly correct", ".0%")])

#%% code
# FIG  shape before and after the repair turn, and correctness
fig, ax = plt.subplots(figsize=(9.6, 3.4))
x = np.arange(len(agg))
ax.bar(x - 0.27, [a["first_try"] for a in agg], 0.26, color=MUTED, label="valid at first try")
ax.bar(x, [a["after_repair"] for a in agg], 0.26, color=C1, label="valid after one repair")
ax.bar(x + 0.27, [a["correct"] for a in agg], 0.26, color=C3, label="exactly correct")
for i, a in enumerate(agg):
    for dx, k in ((-0.27, "first_try"), (0, "after_repair"), (0.27, "correct")):
        ax.text(i + dx, a[k] + 0.01, f"{a[k]:.0%}", ha="center", va="bottom", fontsize=7.5)
ax.set_xticks(x, [a["model"] for a in agg], fontsize=8.5)
ax.set_ylim(0, 1.15)
ax.set_ylabel("share of 8 files")
ax.legend(fontsize=8, ncol=3, loc="upper center")
finish(fig, "s12_json", f"After one repair turn, {np.mean([a['after_repair'] for a in agg]):.0%} of answers fit the schema; "
       f"{np.mean([a['correct'] for a in agg]):.0%} are also right",
       "task: list every function and its parameter count; the syntax tree gives the true answer")

#%% md
**Reading FIG {{figures.s12_json}} (s12_json).** For each model, the grey bar is the share of answers that fit the schema at once, the blue bar the share that fit after the repair turn, and the green bar the share that matched the syntax tree exactly. Averaged over the four models, {{json_repair.first_try|.0%}} fit at first try and {{json_repair.after_repair|.0%}} after one repair, while {{json_repair.correct|.0%}} were exactly right. The gap between blue and green is the important one: shape and truth are different properties, and only the first can be checked without an answer key. Everything a worker returns from here on passes the shape check, and the truth is what Parts VI and VII measure.

#%% code
save_exp("json_repair", {"first_try": float(np.mean([a["first_try"] for a in agg])),
                         "after_repair": float(np.mean([a["after_repair"] for a in agg])),
                         "correct": float(np.mean([a["correct"] for a in agg])), "per_model": agg, "files": JSON_FILES})
results = []
expect("extract_json survives code fences and prose", extract_json("text ```json\n{\"k\": 1}\n``` more") == {"k": 1})
expect("validate names the missing field", any("required" in e or "is a required property" in e for e in validate({}, FUNCS_SCHEMA)))
expect("the repair turn never makes things worse", all(a["after_repair"] >= a["first_try"] for a in agg))
