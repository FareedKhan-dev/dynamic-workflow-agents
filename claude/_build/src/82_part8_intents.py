#%% md
## S60 - What are customers asking about? Ten thousand messages

**Theory.** The third job turns the problem inside out. There is no list of answers to check; there is a pile of short texts, and the question is what is *in* it. The pile is the training split of a public set of messages to a bank's support (CC BY 4.0 licence, kept in `data/intents/`): 10,003 messages, each labelled by its authors with one of 77 intents, from "card arrival" to "contactless not working". The labels are hidden from every worker and used only to score.

This job fans out for a different reason than the audit. The whole pile fits in one context window for *reading*, about 165,000 tokens. What does not fit is the *answer*: a label for each of 10,003 messages is more output than a model will write in one reply. So the plan has to split the writing, and then put the pieces back together into one taxonomy. Putting pieces together is a **reduce**, and when there are too many pieces for one merge, the merge itself is done in a tree: merge groups of labels into topics, then merge the topics.

**In plain terms.** Give a few hundred messages to each worker to tag, merge the tags into a list of topics in a few rounds, then sort every message into one topic and count.

**For teams.** Fan out for output volume, not only for input size. If the answer has one line per item and there are thousands of items, no single call will write it all, and a reply that stops halfway does not say so politely.

#%% code
import csv

INTENT_DIR = DATA / "intents"
with open(INTENT_DIR / "train.csv", encoding="utf-8") as f:
    MESSAGES = [{"id": i + 1, "text": r["text"].strip(), "intent": r["category"]} for i, r in enumerate(csv.DictReader(f))]
MSG_BY_ID = {m["id"]: m for m in MESSAGES}
INTENTS = sorted({m["intent"] for m in MESSAGES})
intent_counts = collections.Counter(m["intent"] for m in MESSAGES)
print(f"[intents] {len(MESSAGES):,} messages, {len(INTENTS)} hidden intents ({min(intent_counts.values())} to "
      f"{max(intent_counts.values())} messages each), about {est_tokens(' '.join(m['text'] for m in MESSAGES)):,} tokens; "
      f"licence: {(INTENT_DIR / 'LICENSE.md').read_text(encoding='utf-8').splitlines()[0]}")
for m in (MESSAGES[0], MESSAGES[5000], MESSAGES[9000]):
    print(f"  {m['id']:>5}: {m['text'][:90]}   (hidden: {m['intent']})")

#%% md
**Scoring a taxonomy.** Three measures, all standard. The **adjusted Rand index** (ARI) asks how often two messages that share an intent also share a topic, corrected for chance, so a random assignment scores about 0 and a perfect one 1. **Normalised mutual information** (NMI) asks how much knowing a message's topic tells about its intent. And because the end product is a count, the **count error**: each topic is matched to the intent it overlaps most (Hungarian matching), and the counts of the 20 largest intents are compared with the counts of their matched topics.

#%% code
from scipy.optimize import linear_sum_assignment


def ari(a, b):
    """Adjusted Rand index of two labelings of the same items."""
    comb = lambda n: n * (n - 1) / 2
    table_ = collections.Counter(zip(a, b))
    sum_ij = sum(comb(n) for n in table_.values())
    sum_a = sum(comb(n) for n in collections.Counter(a).values())
    sum_b = sum(comb(n) for n in collections.Counter(b).values())
    expected = sum_a * sum_b / comb(len(a))
    top = (sum_a + sum_b) / 2
    return (sum_ij - expected) / (top - expected) if top != expected else 1.0


def nmi(a, b):
    """Normalised mutual information of two labelings (arithmetic mean normalisation)."""
    n = len(a)
    pa, pb, pab = collections.Counter(a), collections.Counter(b), collections.Counter(zip(a, b))
    h = lambda c: -sum(v / n * math.log(v / n) for v in c.values())
    mi = sum(v / n * math.log(v * n / (pa[x] * pb[y])) for (x, y), v in pab.items())
    return 2 * mi / (h(pa) + h(pb)) if h(pa) + h(pb) > 0 else 1.0


def count_error(assign):
    """Mean absolute error of the counts of the 20 largest intents, after matching topics to intents."""
    topics = sorted({assign[i] for i in assign})
    overlap = np.array([[sum(1 for i in assign if assign[i] == t and MSG_BY_ID[i]["intent"] == it) for t in topics] for it in INTENTS])
    rows_, cols_ = linear_sum_assignment(-overlap)
    matched = {INTENTS[r]: topics[c] for r, c in zip(rows_, cols_)}
    top20 = [it for it, _ in intent_counts.most_common(20)]
    pred = collections.Counter(assign.values())
    return float(np.mean([abs(pred.get(matched.get(it), 0) - intent_counts[it]) for it in top20])), matched

show_def(ari, nmi, count_error)
truth = [m["intent"] for m in MESSAGES]
shuffled = random.Random(SEED).sample(truth, len(truth))
print(f"[score] the hidden labels against themselves: ARI {ari(truth, truth):.2f}, NMI {nmi(truth, truth):.2f}; "
      f"against a shuffle of themselves: ARI {ari(truth, shuffled):+.3f}, NMI {nmi(truth, shuffled):.3f}")

#%% md
**The intents kit.** `messages` are the ids; `tag(batch)` asks a worker for a short label of what each customer wants; `merge(labels, k)` merges a list of labels into at most *k* topics and maps every label to one; `classify(batch, topics)` puts each message in exactly one topic; `count(assignments)` counts. Tagging and classifying are mechanical, so they run with thinking off.

#%% code
TAG_SYSTEM = """You read short messages that customers sent to their bank. For each message, write a label of two to five words saying what the customer wants, for example "card has not arrived" or "refund not received". Use the same label for messages that want the same thing. Answer with one JSON object and nothing else: {"tags": [{"id": <id>, "label": "..."}]}, one per message."""
MERGE_SYSTEM = """You organise labels that describe what bank customers want. Merge the labels below into at most {k} topics: each topic is one thing customers want, specific enough that a support team could act on it. Map every label to exactly one topic. Answer with one JSON object and nothing else: {{"topics": [{{"name": "...", "description": "..."}}], "mapping": {{"<label>": "<topic name>"}}}}."""
ASSIGN_SYSTEM = """You sort messages that customers sent to their bank into topics. Put every message into exactly one of the topics listed, the one that best says what the customer wants. Answer with one JSON object and nothing else: {"assign": [{"id": <id>, "topic": "<topic name>"}]}, one per message."""
TAGS_SCHEMA = {"type": "object", "required": ["tags"], "properties": {"tags": {"type": "array", "items": {
    "type": "object", "required": ["id", "label"], "properties": {"id": {"type": "integer"}, "label": {"type": "string"}}}}}}
MERGE_SCHEMA = {"type": "object", "required": ["topics", "mapping"], "properties": {"topics": {"type": "array"}, "mapping": {"type": "object"}}}
ASSIGN_SCHEMA = {"type": "object", "required": ["assign"], "properties": {"assign": {"type": "array", "items": {
    "type": "object", "required": ["id", "topic"], "properties": {"id": {"type": "integer"}, "topic": {"type": "string"}}}}}}


def render_messages(ids):
    return "\n".join(f"{i}: {MSG_BY_ID[i]['text']}" for i in ids)

show_def(render_messages)


class IntentKit:
    """The customer-questions job's vocabulary for plans, bound to one run, with a trace."""
    STRIDE = 100

    def __init__(self, run, number=0):
        self.run, self.offset = run, self.STRIDE * number
        self.trace = {"tags": {}, "merges": [], "assign": {}}
        self.lock = threading.Lock()

show_def(IntentKit)

#%% code
@method_of(IntentKit)
def tag(self, ids, sample=0, model="fast"):
    ids = list(ids)[:300]
    obj = self.run.agent(data=render_messages(ids), system=TAG_SYSTEM, schema=TAGS_SCHEMA, model=model, label=f"tag:{ids[0]}",
                         role="tag", sample=self.offset + sample, thinking=False, max_tokens=12000)
    said = {t.get("id"): str(t.get("label", "")).strip().lower()[:60] for t in (obj or {}).get("tags", []) if isinstance(t, dict)}
    out = {i: said[i] for i in ids if said.get(i)}
    with self.lock:
        self.trace["tags"].update(out)
    return out


@method_of(IntentKit)
def merge(self, labels, k=80, sample=0, model="judge"):
    labels = sorted(set(labels))
    obj = self.run.agent(data="\n".join(labels), system=MERGE_SYSTEM.format(k=k), schema=MERGE_SCHEMA, model=model,
                         label=f"merge:{len(labels)}", role="merge", sample=self.offset + sample, max_tokens=16000)
    mapping = {str(a).strip().lower(): str(b).strip() for a, b in ((obj or {}).get("mapping") or {}).items()}
    out = {lab: mapping.get(lab, "unsorted") for lab in labels}
    with self.lock:
        self.trace["merges"].append({"labels": len(labels), "topics": len(set(out.values())), "unmapped": sum(v == "unsorted" for v in out.values())})
    return out


@method_of(IntentKit)
def classify(self, ids, topics, sample=0, model="fast"):
    ids, topics = list(ids)[:300], sorted(set(topics))
    obj = self.run.agent(data="TOPICS\n" + "\n".join(topics) + "\n\nMESSAGES\n" + render_messages(ids), system=ASSIGN_SYSTEM,
                         schema=ASSIGN_SCHEMA, model=model, label=f"classify:{ids[0]}", role="classify", sample=self.offset + sample,
                         thinking=False, max_tokens=12000)
    said = {a.get("id"): str(a.get("topic", "")).strip() for a in (obj or {}).get("assign", []) if isinstance(a, dict)}
    out = {i: said[i] if said.get(i) in topics else "unsorted" for i in ids}
    with self.lock:
        self.trace["assign"].update(out)
    return out

show_def(IntentKit.tag, IntentKit.merge, IntentKit.classify)

#%% code
def tree_merge(kit, labels, group=300, k=80):
    """Merge labels in a tree: groups of `group` labels into topics, then the topics again, until one merge holds them all."""
    level, mapping = sorted(set(labels)), {lab: lab for lab in set(labels)}
    while len(level) > group:
        parts = kit.run.parallel([lambda g=g: kit.merge(g, k=k) for g in batches(level, group)])
        step = {lab: t for p in parts if p for lab, t in p.items()}
        mapping = {lab: step.get(top, top) for lab, top in mapping.items()}
        level = sorted(set(step.values()))
    final = kit.merge(level, k=k)
    return {lab: final.get(top, "unsorted") for lab, top in mapping.items()}


@method_of(IntentKit)
def names(self):
    run, off = self.run, self.offset

    def agent(prompt="", **kw):
        kw["sample"] = off + int(kw.get("sample", 0))
        return run.agent(prompt, **kw)
    return {"agent": agent, "parallel": run.parallel, "pipeline": run.pipeline, "phase": run.phase, "log": run.log,
            "budget": lambda: budget_left(run.llm), "messages": [m["id"] for m in MESSAGES], "batches": batches, "flatten": flatten,
            "tag": self.tag, "merge": self.merge, "tree_merge": lambda labels, group=300, k=80: tree_merge(self, labels, group, k),
            "classify": self.classify, "count": lambda assign: dict(collections.Counter(assign.values()).most_common()),
            "MODELS": sorted(MODELS)}

show_def(tree_merge, IntentKit.names)

#%% md
**Stand-ins for smoke runs.** The scripted tagger writes the hidden intent back as a label, reworded in one of three ways so that the merge has real work to do; the merger maps each label back to its intent; the classifier is right nine times in ten. The single-call stand-in stops after 2,000 messages, which is roughly where a real 16,000-token reply runs out.

#%% code
def _label_for(i, sample=0):
    words = MSG_BY_ID[i]["intent"].replace("_", " ").split()
    forms = [" ".join(words), " ".join(reversed(words)), "about " + " ".join(words[:3])]
    return forms[zlib.crc32(f"{i}:{sample}".encode()) % 3]


@SCRIPTED.register
def _intents(model, messages, params):
    system, text = messages[0]["content"], messages[-1]["content"]
    if system.startswith("You read short messages that customers sent"):
        ids = [int(x) for x in re.findall(r"^(\d+): ", text, re.M)]
        return json.dumps({"tags": [{"id": i, "label": _label_for(i, params.get("sample", 0))} for i in ids[:2000]]})
    if system.startswith("You organise labels"):
        labels = [l for l in text.splitlines() if l.strip()]
        intent_of = {}
        for lab in labels:
            words = set(lab.replace("about ", "").split())
            intent_of[lab] = max(INTENTS, key=lambda it: len(words & set(it.split("_"))) - 0.01 * len(it))
        return json.dumps({"topics": [{"name": t, "description": t} for t in sorted(set(intent_of.values()))], "mapping": intent_of})
    if system.startswith("You sort messages"):
        topics = text.split("\n\nMESSAGES\n")[0].splitlines()[1:]
        ids = [int(x) for x in re.findall(r"^(\d+): ", text.split("\n\nMESSAGES\n")[1], re.M)]
        pick_ = lambda i: MSG_BY_ID[i]["intent"] if MSG_BY_ID[i]["intent"] in topics and zlib.crc32(str(i).encode()) % 10 else topics[i % len(topics)]
        return json.dumps({"assign": [{"id": i, "topic": pick_(i)} for i in ids]})
    return None

show_def(_label_for, _intents)

#%% md
### One call for everything

The obvious first attempt: give one worker every message and ask for a label per message. The input fits. The question is how much of the answer comes back.

#%% code
ALL_IDS = [m["id"] for m in MESSAGES]
one_run = Run("intents in one call", run_id="intents-one-call", concurrency=1)
one_text = one_run.run_sync(lambda r: r.agent(data=render_messages(ALL_IDS), system=TAG_SYSTEM, model="worker", label="tag:all",
                                              role="tag", thinking=False, max_tokens=16000))
one_ids = {int(x) for x in re.findall(r'"id"\s*:\s*(\d+)', one_text or "")} & set(ALL_IDS)      # count what came back, even if cut off
one_reply = one_run.threads[0].replies[-1] if one_run.threads and one_run.threads[0].replies else None
ONE_CALL = {"input_tokens": est_tokens(render_messages(ALL_IDS)), "labelled": len(one_ids), "share": len(one_ids) / len(ALL_IDS),
            "finish": one_reply.finish if one_reply else None, "output_tokens": one_reply.completion_tokens if one_reply else 0}
print(f"[one call] input about {ONE_CALL['input_tokens']:,} tokens; labels came back for {ONE_CALL['labelled']:,} of {len(ALL_IDS):,} messages "
      f"({ONE_CALL['share']:.0%}) in {ONE_CALL['output_tokens']:,} tokens of output; the reply ended with finish reason '{ONE_CALL['finish']}'")

#%% md
### The workflow, planned by the lead

#%% code
INTENT_API_DOC = """RUNTIME: phase(title), log(message), agent(...), parallel([thunk, ...]), pipeline(items, stage, ...), budget()
THE INTENTS KIT
  messages                     the ids of the 10,003 messages
  batches(items, size)         consecutive groups of at most `size` items (a worker reads at most 300 messages)
  tag(batch, sample=0, model="fast")         a short label for each message: {id: label}
  merge(labels, k=80, model="judge")         at most k topics for a list of labels: {label: topic}
  tree_merge(labels, group=300, k=80)        merge in rounds of `group` labels until one merge holds them all: {label: topic}
  classify(batch, topics, model="fast")      exactly one of the topics for each message: {id: topic}
  count(assignments)           messages per topic, largest first
The program must assign {"topics": ..., "counts": ...} to `result`."""
LEAD_INTENT_SYSTEM = (LEAD_HW_SYSTEM.split("THE PLAN LANGUAGE")[0].replace("lead of a homework-grading job", "lead of a customer-research job")
                      .replace("You never grade anything yourself", "You never read the messages yourself")
                      + "THE PLAN LANGUAGE\nThe same restricted Python as for any plan.\n\n" + INTENT_API_DOC
                      + "\n\nRULES\n- Billing is per token. Keep the expected cost under half of the budget.\n- Every message must be "
                      "sorted into a topic.\n\nAnswer with the program in one ```python block and nothing else.")
INTENT_JOB = "Find out what the bank's customers are asking about: a list of topics, and how many of the 10,003 messages fall into each."


def intent_page(budget_cents):
    return (f"THE WORK\n- {len(MESSAGES):,} short messages, about {est_tokens(render_messages(ALL_IDS)):,} tokens in all.\n"
            f"- One call that tried to label them all labelled {ONE_CALL['share']:.0%} before its answer ended.\n\nPRICES AND LIMITS\n"
            "- Prices in dollars per million tokens: " + price_text(("worker", "fast", "judge", "lead"))
            + f". Billing is per token.\n- A worker reads at most 300 messages per call.\n- Budget for this job: {budget_cents} cents.")


@SCRIPTED.register
def _lead_intents(model, messages, params):
    if "lead of a customer-research job" not in messages[0]["content"][:200]:
        return None
    return ("```python\n"
            'phase("Tag")\n'
            "tags = {}\n"
            "for part in parallel([lambda b=b: tag(b) for b in batches(messages, 250)]):\n"
            "    tags.update(part or {})\n"
            'phase("Merge in a tree")\n'
            "topic_of = tree_merge(list(tags.values()), group=300, k=80)\n"
            "topics = sorted(set(topic_of.values()))\n"
            'log(f"{len(set(tags.values()))} distinct labels became {len(topics)} topics")\n'
            'phase("Classify")\n'
            "assign = {}\n"
            "for part in parallel([lambda b=b: classify(b, topics) for b in batches(messages, 250)]):\n"
            "    assign.update(part or {})\n"
            'result = {"topics": topics, "counts": count(assign)}\n```')


DRY_INTENTS = ScriptedModel()
DRY_INTENTS.register(_intents)
show_def(intent_page, _lead_intents)
INTENT_BUDGET = 100
INTENT_PLAN = LEAD.write_program(INTENT_JOB, intent_page(INTENT_BUDGET), sample=0, budget_cents=INTENT_BUDGET, system=LEAD_INTENT_SYSTEM,
                                 kit_class=IntentKit, stand_in=DRY_INTENTS)
print(INTENT_PLAN["src"])
print(f"\n[plan] valid after {INTENT_PLAN['tries']} attempt(s); estimate {INTENT_PLAN['estimate']['agents']} workers, "
      f"{INTENT_PLAN['estimate']['cents']:.1f}¢; gate: {approve(INTENT_PLAN['estimate'], INTENT_BUDGET, person=lambda e: e['cents'] <= INTENT_BUDGET / 2)[0]}")

#%% code
INTENT_RUN = Run("intents: the lead's plan", INTENT_JOB, run_id="intents-workflow", llm=job_door(INTENT_BUDGET), concurrency=32)
INTENT_KIT = IntentKit(INTENT_RUN)
INTENT_RESULT = INTENT_RUN.run_sync(lambda r: run_program(INTENT_PLAN["src"], INTENT_KIT))
ASSIGN = {i: INTENT_KIT.trace["assign"].get(i, "unsorted") for i in ALL_IDS}
pred = [ASSIGN[i] for i in ALL_IDS]
CERR, MATCHED = count_error(ASSIGN)
INTENT_SCORE = {"ari": ari(truth, pred), "nmi": nmi(truth, pred), "topics": len(set(pred)), "unsorted": sum(p == "unsorted" for p in pred),
                "count_error": CERR, "cost": full_price(INTENT_RUN), "labels": len(set(INTENT_KIT.trace["tags"].values())),
                "merges": INTENT_KIT.trace["merges"]}
print(f"[workflow] {INTENT_RUN.status}: {len(INTENT_RUN.threads)} workers, {INTENT_SCORE['cost']:.1f}¢ at full price; "
      f"{INTENT_SCORE['labels']:,} distinct labels -> {INTENT_SCORE['topics']} topics; {INTENT_SCORE['unsorted']} messages unsorted")
print(f"[score] ARI {INTENT_SCORE['ari']:.3f}, NMI {INTENT_SCORE['nmi']:.3f}; count error over the 20 largest intents: {CERR:.1f} messages")

#%% md
**Tree against flat.** The same labels, merged once in a single call (flat) instead of in rounds of 300 (tree). A flat merge must write a mapping line for every distinct label in one reply.

#%% code
FLAT_RUN = Run("intents: one flat merge", run_id="intents-flat", concurrency=1)
FLAT_KIT = IntentKit(FLAT_RUN)
flat_map = FLAT_RUN.run_sync(lambda r: FLAT_KIT.merge(list(INTENT_KIT.trace["tags"].values()), k=80))
FLAT = {"labels": len(flat_map or {}), "mapped": sum(v != "unsorted" for v in (flat_map or {}).values())}
FLAT["share"] = FLAT["mapped"] / max(1, FLAT["labels"])
tree_merges = INTENT_KIT.trace["merges"]
print(f"[flat] one merge of {FLAT['labels']:,} labels mapped {FLAT['mapped']:,} ({FLAT['share']:.0%}); "
      f"the tree used {len(tree_merges)} merges, each of at most {max(m['labels'] for m in tree_merges) if tree_merges else 0} labels, "
      f"leaving {sum(m['unmapped'] for m in tree_merges)} unmapped")

#%% code
# FIG  ten thousand messages: how the work was split, and what came back
fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.6), gridspec_kw={"width_ratios": [1, 1.3, 1.3]})
ax = axes[0]
ax.bar(["one call", "workflow"], [ONE_CALL["share"], 1 - INTENT_SCORE["unsorted"] / len(ALL_IDS)], color=[MUTED, C7])
ax.set_ylim(0, 1)
ax.set_ylabel("share of messages labelled")
panel(ax, "what came back")
ax = axes[1]
top20 = [it for it, _ in intent_counts.most_common(20)]
predc = collections.Counter(pred)
ax.scatter([intent_counts[it] for it in top20], [predc.get(MATCHED.get(it), 0) for it in top20], color=C7, s=30)
lim = max(intent_counts.values()) * 1.1
ax.plot([0, lim], [0, lim], ":", color=INK2)
ax.set_xlabel("true messages per intent")
ax.set_ylabel("messages in the matched topic")
panel(ax, f"the 20 largest intents; error {CERR:.0f}")
ax = axes[2]
ax.bar(["flat merge", "tree merge"], [FLAT["share"], 1 - sum(m["unmapped"] for m in tree_merges) / max(1, INTENT_SCORE["labels"])],
       color=[MUTED, C7])
ax.set_ylim(0, 1)
ax.set_ylabel("share of labels mapped to a topic")
panel(ax, "flat against tree")
finish(fig, "s60_intents", f"Ten thousand messages: one call labelled {ONE_CALL['share']:.0%}, the workflow sorted all but "
       f"{INTENT_SCORE['unsorted']}, ARI {INTENT_SCORE['ari']:.2f}", "hidden intents used only for scoring; counts matched by the Hungarian method")

#%% md
**Reading FIG {{figures.s60_intents}} (s60_intents).** Left: one call that was asked to label every message returned labels for {{intents.one_share|.0%}} of them before its answer ended; the workflow sorted all but {{intents.unsorted}}. Middle: for the 20 largest intents, the true number of messages against the number in the topic matched to it; points on the dotted line are exact counts, and the mean error was {{intents.count_error|.1f}} messages. Right: a flat merge in one call mapped {{intents.flat_share|.0%}} of the distinct labels; the tree, in merges of at most 300 labels, left {{intents.tree_unmapped}} unmapped. The tree's merges ended with {{intents.topics}} topics for 77 hidden intents, from {{intents.labels}} distinct labels. The taxonomy scored an adjusted Rand index of {{intents.ari|.2f}} and a normalised mutual information of {{intents.nmi|.2f}} against the 77 hidden intents, for {{intents.cost|.1f}} cents.

#%% code
save_exp("intents", {"one_share": ONE_CALL["share"], "one_labelled": ONE_CALL["labelled"], "unsorted": INTENT_SCORE["unsorted"],
                     "count_error": CERR, "flat_share": FLAT["share"], "tree_unmapped": sum(m["unmapped"] for m in tree_merges),
                     "ari": INTENT_SCORE["ari"], "nmi": INTENT_SCORE["nmi"], "cost": INTENT_SCORE["cost"], "topics": INTENT_SCORE["topics"],
                     "labels": INTENT_SCORE["labels"], "plan": INTENT_PLAN["src"], "messages": len(MESSAGES)})
results = []
expect("ARI and NMI are 1 for identical labelings and near 0 for a shuffle", ari(truth, truth) == 1 and abs(ari(truth, shuffled)) < 0.01)
expect("the workflow assigned every message to some topic or to 'unsorted'", len(ASSIGN) == len(ALL_IDS))
expect("the lead's plan for this job passed both gates", INTENT_PLAN["valid"])
