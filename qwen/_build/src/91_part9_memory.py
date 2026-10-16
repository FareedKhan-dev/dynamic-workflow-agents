#%% md
## S65 - Do the models remember this library?

**Theory.** The library audited here is public and popular, so the models have probably read it during training. That matters: a worker that *remembers* what a function should look like can spot a changed line by recall rather than by reasoning, and every recall figure in this notebook would then measure memory as much as skill. The probe is direct. For each function that holds a planted bug, the worker is shown only the original function's first line and docstring and asked to write the rest. The more closely its body matches the original, the more it remembers. Then the bugs are split by how well their function is remembered, and recall is compared across the split.

**In plain terms.** Ask the model to finish a function from the library from its name and description alone. If it writes it nearly word for word, it has seen it before.

**For teams.** If your evaluation uses public code or public text, measure memorization before you report results, and report results split by it.

#%% code
def header_and_body(path, func):
    """(header: the def line and docstring, body: the rest) of a function in the original file, or None."""
    src = (ORIGINAL / path).read_text(encoding="utf-8")
    lines = src.splitlines()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func.split(".")[-1]:
            body = node.body[1:] if node.body and isinstance(node.body[0], ast.Expr) and isinstance(getattr(node.body[0], "value", None), ast.Constant) else node.body
            if not body:
                return None
            cut = body[0].lineno - 1
            return "\n".join(lines[node.lineno - 1:cut]), "\n".join(lines[cut:node.end_lineno])
    return None


def code_similarity(a, b):
    """Similarity of two code bodies, 0 to 1, ignoring blank lines, comments and indentation."""
    norm = lambda s: [ln.split("#")[0].strip() for ln in s.splitlines() if ln.split("#")[0].strip()]
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()

show_def(header_and_body, code_similarity)
MEM_SYSTEM = """You complete Python functions. You get the first line and the docstring of a function from a well-known public collection of algorithm implementations. Write the rest of the function's body exactly as you believe it appears there. Answer with the code of the body only, in one ```python block."""


@SCRIPTED.register
def _memory(model, messages, params):
    if not messages[0]["content"].startswith("You complete Python functions"):
        return None
    head = messages[-1]["content"]
    b = next((b for b in ANSWER_KEY if b["function"].split(".")[-1] in head.split("(")[0]), None)
    hb = header_and_body(b["path"], b["function"]) if b else None
    body = hb[1] if hb else "    pass"
    keep = 0.95 if zlib.crc32(head.encode()) % 3 == 0 else 0.4             # the stand-in remembers about a third of them well
    lines = body.splitlines()
    out = [ln if zlib.crc32(f"{i}:{ln}".encode()) % 100 < keep * 100 else "    x = 0" for i, ln in enumerate(lines)]
    return "```python\n" + "\n".join(out) + "\n```"

show_def(_memory)

#%% code
MEM_RUN = Run("memorization probe", run_id="s65-memory", concurrency=32)
mem_targets = [(b, header_and_body(b["path"], b["function"])) for b in ANSWER_KEY]
mem_targets = [(b, hb) for b, hb in mem_targets if hb]
MEM_OUT = MEM_RUN.run_sync(lambda r: r.parallel([lambda b=b, hb=hb: r.agent(data=hb[0], system=MEM_SYSTEM, model="worker", label=f"recall:{b['id']}",
                                                                          role="memory", thinking=False, max_tokens=4000)
                                                 for b, hb in mem_targets]))
MEMORY = {b["id"]: code_similarity(extract_code(text) or "", hb[1]) for (b, hb), text in zip(mem_targets, MEM_OUT)}
mem_median = float(np.median(list(MEMORY.values())))
print(f"[memory] {len(MEMORY)} functions probed; similarity of the written body to the original: median {mem_median:.2f}, "
      f"{sum(v >= 0.8 for v in MEMORY.values())} at 0.8 or more")

#%% code
def recall_split(rows, ids):
    """Mean recall over runs restricted to the planted bugs in `ids`."""
    return float(np.mean([sum(i in set(r["found_ids"]) for i in ids) / max(1, len(ids)) for r in rows])) if ids else None

show_def(recall_split)
remembered = [i for i, v in MEMORY.items() if v >= mem_median]
not_remembered = [i for i, v in MEMORY.items() if v < mem_median]
MEM_SPLIT = {k: {"remembered": recall_split(by_arm[k], remembered), "not remembered": recall_split(by_arm[k], not_remembered)} for k in ("A", "C", "D")}
table([{"arm": k, **v} for k, v in MEM_SPLIT.items()], [("arm", "arm", ""), ("remembered", "recall, better-remembered half", ".2f"),
                                                        ("not remembered", "recall, less-remembered half", ".2f")])

#%% code
# FIG  how well the worker remembers each function, and whether that predicts finding its bug
fig, axes = plt.subplots(1, 2, figsize=(10.4, 3.4))
ax = axes[0]
ax.hist(list(MEMORY.values()), bins=20, range=(0, 1), color=C1)
ax.axvline(mem_median, color=INK, ls="--", lw=1)
ax.set_xlabel("similarity of the written body to the original")
ax.set_ylabel("functions with a planted bug")
panel(ax, "what the worker remembers")
ax = axes[1]
x = np.arange(3)
ax.bar(x - 0.18, [MEM_SPLIT[k]["remembered"] or 0 for k in ("A", "C", "D")], 0.36, color=C1, label="better-remembered half")
ax.bar(x + 0.18, [MEM_SPLIT[k]["not remembered"] or 0 for k in ("A", "C", "D")], 0.36, color=MUTED, label="less-remembered half")
ax.set_xticks(x, ["A: one agent", "C: fixed plan", "D: dynamic"])
ax.set_ylim(0, 1)
ax.set_ylabel("recall")
ax.legend(fontsize=7.5)
panel(ax, "recall, split at the median similarity")
gap = (MEM_SPLIT["D"]["remembered"] or 0) - (MEM_SPLIT["D"]["not remembered"] or 0)
finish(fig, "s65_memory", f"The worker rewrote half the functions with similarity {mem_median:.2f} or more; the workflow's recall "
       f"was {gap:+.2f} higher on the better-remembered half", "each function's first line and docstring were shown; its body was asked for")

#%% md
**Reading FIG {{figures.s65_memory}} (s65_memory).** Left: how closely the worker rewrote each function's body from its name and docstring alone; the median similarity was {{memory.median|.2f}}, and {{memory.high}} functions came back at 0.8 or more, nearly line for line. Right: recall on the bugs in the better-remembered half against the less-remembered half. For the dynamic workflow the difference was {{memory.gap_D|+.2f}}; for one agent alone {{memory.gap_A|+.2f}}. A large positive gap would mean memory does part of the work, and the absolute recall figures elsewhere should be read as an upper bound for unseen code. The comparison between designs is less affected, because every arm used the same worker model and the same library.

#%% code
save_exp("memory", {"median": mem_median, "high": sum(v >= 0.8 for v in MEMORY.values()), "split": MEM_SPLIT, "gap_D": gap,
                    "gap_A": (MEM_SPLIT["A"]["remembered"] or 0) - (MEM_SPLIT["A"]["not remembered"] or 0), "similarity": MEMORY})
results = []
expect("identical bodies are similar 1.0 and unrelated ones far less", code_similarity("a = 1\nreturn a", "a = 1\nreturn a") == 1.0
       and code_similarity("a = 1\nreturn a", "for x in y:\n    pass") < 0.5)
expect("every probed function has a similarity", len(MEMORY) == len(mem_targets))

#%% md
## S66 - Bugs we did not plant

**Theory.** Some findings match no planted bug and still describe real behaviour. The library was written by many people and is not free of bugs. A finding is a candidate for a real, unplanted bug when its failing call, run on the **original** code, does not return what the finder expected. That is a cautious test: the finder's expectation can itself be wrong, and some functions are deliberately limited. So the list below is a list of candidates, each with its evidence, not a list of bugs; the cautious reading is to count them apart from the main precision, which is what this notebook does.

**In plain terms.** When a worker reports a problem we did not plant, run its example on the untouched code. If the code still disagrees with the worker, a person should take a look.

#%% code
def unplanted_candidates(kits):
    """Confirmed places that match no planted bug and whose failing call, on the original code, disagrees with the finder."""
    out, seen = [], set()
    for kit in kits:
        for f in kit.trace["confirmed"]:
            if key_of(f) in seen or is_planted(f) or not f.get("failing_call") or f["file"] not in CORPUS:
                continue
            seen.add(key_of(f))
            r = run_call_in(ORIGINAL, f["file"], f["failing_call"])
            if r.get("error") == "rejected":
                continue
            got = r.get("value") if r.get("ok") else f"raised {r.get('error', '')[:60]}"
            agree = r.get("ok") and same_value(r["value"], f.get("expected", ""))
            if not agree:
                out.append({"place": key_of(f), "call": f["failing_call"][:60], "expected": f.get("expected", "")[:30], "original gives": str(got)[:40],
                            "claim": f["claim"][:80]})
    return out

show_def(unplanted_candidates)
UNPLANTED = unplanted_candidates([k for _, k, _ in [o for o in D_OBJS if o]] + [k for _, k, _ in C_OBJS])
print(f"[unplanted] {len(UNPLANTED)} candidate real bugs in the original library, from the confirmed findings of the C and D runs")
table(UNPLANTED[:12], [("place", "place", ""), ("call", "failing call", ""), ("expected", "finder expected", ""), ("original gives", "original gives", "")])
save_exp("unplanted", {"candidates": len(UNPLANTED), "rows": UNPLANTED})
