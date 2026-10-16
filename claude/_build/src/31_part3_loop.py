#%% md
## S16 - The agent loop

**Theory.** An agent is a loop around a model. Each **turn**, the host sends the conversation so far; the model answers with one **action**, a JSON object naming a tool and its arguments; the host runs the tool and appends the result to the conversation; and the loop goes round again. It stops when the model calls `done`, when the turn limit is reached, or when the model keeps sending answers the host cannot read.

The conversation only grows. Every file the agent reads stays in its context, so a few dozen reads fill even a large window, and each turn costs more time than the last because the whole history is sent again. A long-running agent therefore needs **compaction**: when the context passes a threshold, the host replaces the older turns with a short summary of what matters (which files have been read, which bugs have been reported) and keeps only the most recent turns in full. Our host writes that summary itself from its own records, so compaction costs no extra model call and cannot invent anything. The price is that the agent loses the detail of everything it read before. S17 records how often each run compacted, so we can see whether that loss came into play.

**In plain terms.** The agent asks for a tool, we run it and show the result, and we repeat. When its memory gets full, we replace the old part with a short list of what it already did.

**For teams.** Log every turn as a record (action, target, tokens, seconds, context size). Almost every question you will later ask about an agent run, from "why did it stop?" to "what did it cost?", is a query over those records.

![agent_loop](attachment:agent_loop.png)

#%% code
SOLO_SYSTEM = SCAN_SYSTEM.split("The code is several files.")[0].strip() + """

You are auditing a whole codebase of about {n_files} Python files in about {n_folders} folders, alone, using tools. You act by sending exactly one JSON object per turn, of the form {{"tool": "<name>", "args": {{...}}}}. The tools:
- ls: {{"path": "<folder>"}} lists a folder; use "." for the top
- read: {{"path": "<file>", "start": 1, "end": 300}} returns numbered lines, at most 300 per call
- grep: {{"pattern": "<regular expression>", "path": "<folder or file>"}} finds matching lines
- run: {{"file": "<file>", "call": "<one call to a function in that file, with literal arguments>"}} runs it in a sandbox and returns the value
- report: {{"file": "<file>", "line": <number>, "function": "<name>", "claim": "<one sentence>", "failing_call": "<call>", "expected": "<value>"}} records one bug
- done: {{"summary": "<one sentence>"}} ends the audit

Every tool result shows the turn number and your turn limit. Cover as much of the code as you can, report each bug as soon as you are confident about it, and call done only when you have finished or are out of turns."""
COMPACT_AT = 80_000      # tokens of context that trigger compaction; it keeps every turn under the worker's long-prompt price
KEEP_RECENT = 4          # turns kept in full after a compaction
print(f"[solo] instruction: {len(SOLO_SYSTEM.split())} words; compaction at {COMPACT_AT:,} tokens, keeping the last {KEEP_RECENT} turns")

#%% md
**`Turn`** is the record of one turn, and **`Episode`** is the record of one whole audit. They hold everything the figures and the accounts need, so no later analysis has to re-run anything.

#%% code
@dataclass
class Turn:
    n: int                  # turn number, from 1
    tool: str               # the action the model chose, or "none" when the reply could not be read
    target: str             # the path, pattern or call it acted on
    ok: bool                # did the tool run
    context_tokens: int     # size of what the model was sent this turn (our estimate)
    prompt_tokens: int      # as the server counted them
    completion_tokens: int  # what the model wrote back, reasoning included
    seconds: float          # the model's time for this turn
    cached: bool            # answered from the ledger
    reported: int           # bugs reported so far
    files_read: int         # distinct files read so far


@dataclass
class Episode:
    label: str
    findings: list
    turns: list
    files_read: set
    stop: str
    compactions: int
    seconds: float

show_def(Turn, Episode)

#%% md
**`parse_action(text)`** reads one action from a reply, tolerating the usual wrapping (code fences, a sentence before the JSON). **`execute(action)`** runs it and returns the text the model will see; every tool error comes back as text instead of an exception, so a bad action costs the agent a turn, not the run.

#%% code
TOOL_NAMES = ("ls", "read", "grep", "run", "report", "done")


def parse_action(text):
    """(tool, args) from a reply, or (None, reason)."""
    obj = extract_json(text)
    if not isinstance(obj, dict) or obj.get("tool") not in TOOL_NAMES:
        return None, "send one JSON object with a tool from: " + ", ".join(TOOL_NAMES)
    args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
    return obj["tool"], args


def execute(tool, args, state):
    """Run one tool; return the text the model sees. state holds findings and files read."""
    try:
        if tool == "ls":
            return tool_ls(args.get("path", "."))
        if tool == "read":
            out = tool_read(args.get("path", ""), args.get("start", 1), args.get("end"))
            state["files"].add(normalise_path(args.get("path", "")))
            return out
        if tool == "grep":
            return tool_grep(args.get("pattern", ""), args.get("path", "."))
        if tool == "run":
            out = run_call(args.get("file", ""), args.get("call", ""))
            return f"value: {out['value']}" if out["ok"] else f"error: {out['error']}"
        if tool == "report":
            state["findings"].append(Finding(file=normalise_path(args.get("file", "")), line=int(args.get("line", 0) or 0),
                                             function=str(args.get("function", "")), claim=str(args.get("claim", "")),
                                             failing_call=str(args.get("failing_call", "")), expected=str(args.get("expected", "")),
                                             source=state["label"]))
            return f"recorded ({len(state['findings'])} bugs reported so far)"
        if tool == "done":
            return "audit closed"
    except PathDenied as e:
        return f"error: {e}"
    except (ValueError, TypeError, OSError) as e:
        return f"error: {type(e).__name__}: {e}"
    return "error: unknown tool"

show_def(parse_action, execute)

#%% md
**`compact(messages, state)`** replaces everything between the task and the last few turns with one message the host writes: the files already read and the bugs already reported. Nothing in it comes from a model, so nothing in it can be wrong.

#%% code
def compact(messages, state):
    """System, task, a host-written summary, then the last KEEP_RECENT turns."""
    head, tail = messages[:2], messages[-2 * KEEP_RECENT:]
    files = sorted(state["files"])
    found = [f"{f.file}:{f.line} ({f.claim[:60]})" for f in state["findings"]]
    summary = ("Earlier turns were removed to save space. What you did before this point:\n"
               f"- files read ({len(files)}): " + ", ".join(files) + "\n"
               f"- bugs reported ({len(found)}): " + ("; ".join(found) if found else "none") + "\n"
               "Do not read those files again unless you must. Continue the audit.")
    return head + [{"role": "user", "content": summary}] + tail

show_def(compact)

#%% md
**`solo_audit(...)`** is the loop. Each turn it measures the context, compacts if needed, asks the model, parses the action, runs it and records the turn. All turns of one episode use the same sample index, so three episodes with indices 0, 1 and 2 are three independent audits that each replay exactly.

#%% code
def solo_audit(label, model=None, max_turns=150, sample=0, task_files=None, run_id=""):
    """One agent, alone with its tools, auditing the tree. Returns an Episode."""
    model = model or MODELS["worker"]
    files = task_files or sorted(CORPUS)
    system = SOLO_SYSTEM.format(n_files=len(files), n_folders=len({p.split("/")[0] for p in files}))
    task = ("Audit the code for behaviour bugs. Here is the top folder to start from:\n" + tool_ls(".")
            if task_files is None else "Audit these files for behaviour bugs:\n" + "\n".join(files))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": task}]
    state = {"files": set(), "findings": [], "label": label}
    turns, compactions, bad_in_row, stop = [], 0, 0, "max turns"
    params = {"temperature": TEMPERATURE, "top_p": TOP_P, "max_tokens": 8000}
    if "JSON mode" in CAN.get(model, ()):
        params["response_format"] = {"type": "json_object"}
    start = time.perf_counter()
    for n in range(1, max_turns + 1):
        ctx = sum(est_tokens(m["content"]) for m in messages)
        if ctx > COMPACT_AT:
            messages = compact(messages, state)
            compactions += 1
            ctx = sum(est_tokens(m["content"]) for m in messages)
        r = FRONT_DOOR.chat(model, messages, tag=f"{label}:turn{n}", role="solo", phase="solo", run_id=run_id,
                            sample=sample, **params)
        if r.finish == "error":
            stop = f"error: {r.error}"
            break
        tool, args = parse_action(r.text)
        if tool is None:
            bad_in_row += 1
            out, target = f"error: {args}", ""
        else:
            bad_in_row = 0
            out = execute(tool, args, state)
            target = str(args.get("path") or args.get("file") or args.get("pattern") or "")[:60]
        turns.append(Turn(n, tool or "none", target, tool is not None and not out.startswith("error"), ctx,
                          r.prompt_tokens, r.completion_tokens, r.seconds, r.cached, len(state["findings"]), len(state["files"])))
        if tool == "done":
            stop = "done"
            break
        if bad_in_row >= 3:
            stop = "three unreadable replies in a row"
            break
        messages += [{"role": "assistant", "content": r.text[:4000]},
                     {"role": "user", "content": f"<result tool={tool} turn={n}/{max_turns}>\n{out}\n</result>"}]
    return Episode(label, state["findings"], turns, state["files"], stop, compactions, time.perf_counter() - start)

show_def(solo_audit)

#%% md
**A scripted auditor for smoke runs.** It lists the top folder, then reads files in alphabetical order, one per turn. After reading a file that holds a planted bug, it reports the bug with a probability that falls as the turns go by. That is an invented stand-in for fatigue, there only so the figures below have something to draw in a smoke run.

#%% code
ALPHA = sorted(CORPUS)


@SCRIPTED.register
def _solo(model, messages, params):
    if "auditing a whole codebase" not in messages[0]["content"]:
        return None
    m = re.search(r"turn=(\d+)/(\d+)", messages[-1]["content"])
    t, limit = (int(m.group(1)) + 1, int(m.group(2))) if m else (1, 150)
    if t >= limit:
        return json.dumps({"tool": "done", "args": {"summary": "out of turns"}})
    if t == 1:
        return json.dumps({"tool": "ls", "args": {"path": "."}})
    last = re.search(r"^### (\S+)$", messages[-1]["content"], re.M)
    if last:
        bug = next((b for b in ANSWER_KEY if b["path"] == last.group(1)), None)
        if bug and (zlib.crc32(f"{bug['id']}:{t}".encode()) % 100) / 100 < 0.75 - t / 300:
            return json.dumps({"tool": "report", "args": {"file": bug["path"], "line": bug["line"], "function": bug["function"],
                                                          "claim": "this line looks wrong", "failing_call": "", "expected": ""}})
    return json.dumps({"tool": "read", "args": {"path": ALPHA[(t * 7) % len(ALPHA)], "start": 1, "end": 300}})

show_def(_solo)

#%% md
**One short episode, turn by turn.** Before the long runs, a short episode on three files (one of them holding a planted bug) shows the loop at work. Every turn prints the action, its target, the context the model was sent and how long it took.

#%% code
toy_bug = next(b for b in ANSWER_KEY if FILE_TOKENS[b["path"]] < 2500)
toy_files = [toy_bug["path"]] + [p for p in ALPHA if p.split("/")[0] == toy_bug["folder"] and p != toy_bug["path"]][:2]
toy = solo_audit("toy", max_turns=8, task_files=toy_files)
for t in toy.turns:
    print(f"  turn {t.n}  {t.tool:<6} {t.target:<44} context {t.context_tokens:>6,} tokens  {t.seconds:5.1f}s  {'ok' if t.ok else 'ERR'}")
print(f"[toy] stop: {toy.stop}; reported {len(toy.findings)}; the planted bug was {toy_bug['path']}:{toy_bug['line']} "
      f"({toy_bug['operator']}); matched: {match(toy.findings, key=[toy_bug]).tp == 1}")

#%% md
## S17 - Baseline A: one agent, the whole codebase, 150 turns

**Theory.** The first baseline is the obvious design: one capable model, the full set of tools, and the whole job. It gets 150 turns, which is far more than most agent frameworks allow by default and enough to read about 120 files if it does nothing else. We run it three times with three sample indices, because a single run of a sampling model is an anecdote: the spread between runs is as much a result as the mean. The three runs are independent, so they run side by side.

What we expected before the runs were three limits; the figures below check which of them the live runs actually reached:

- **Coverage:** 150 turns cannot touch 850 files.
- **Memory:** compaction throws away what was read, so cross-file reasoning suffers.
- **Attention:** a model deep into a long session may notice less than it did at the start.

**In plain terms.** We give one agent the whole job and plenty of turns, three times over, and watch how far it gets.

#%% code
def cost_of(run_id):
    """Calls and cents the ledger charged to one run, whatever mode the notebook is in now."""
    row = LEDGER.query("SELECT COUNT(*), COALESCE(SUM(cents), 0) FROM calls WHERE run_id = ?", (run_id,))[0]
    return {"calls": row[0], "cents": row[1]}

show_def(cost_of)
SOLO_TURNS = 150
t0 = time.perf_counter()
with cf.ThreadPoolExecutor(RUNS) as pool:
    SOLO = list(pool.map(lambda r: solo_audit(f"solo-{r}", max_turns=SOLO_TURNS, sample=r, run_id=f"solo-{r}"), range(RUNS)))
SOLO_SCORES = [match(e.findings) for e in SOLO]
SOLO_ROWS = [{"run": e.label, "turns": len(e.turns), "stop": e.stop, "files_read": len(e.files_read),
              "coverage": len(e.files_read & set(CORPUS)) / len(CORPUS), "reported": len(e.findings), "found": s.tp,
              "recall": s.recall, "precision": s.precision, "compactions": e.compactions,
              "cents": cost_of(e.label)["cents"],
              "minutes": sum(t.seconds for t in e.turns) / 60} for e, s in zip(SOLO, SOLO_SCORES)]
table(SOLO_ROWS, [("run", "run", ""), ("turns", "turns", "d"), ("stop", "stopped because", ""), ("coverage", "files read", ".0%"),
                  ("reported", "reported", "d"), ("found", f"found of {len(ANSWER_KEY)}", "d"), ("recall", "recall", ".2f"),
                  ("precision", "precision", ".2f"), ("compactions", "compactions", "d"), ("cents", "cents", ".1f"),
                  ("minutes", "model minutes", ".0f")])
print(f"[solo] {RUNS} runs in {time.perf_counter() - t0:.0f} s of wall clock")
