#%% md
## S46 - Card: how many bugs are left?

**Why.** An audit that reports 60 bugs leaves an obvious question open: out of how many? In this notebook the answer key knows. In real work nobody does, and the question still matters, because it decides whether to keep looking. Ecologists answer the same question about animals with **capture and recapture**: catch some, mark them, release them, catch again. If the second catch contains many marked animals, the first catch had already found most of the population; if it contains few, many animals were never caught. Two independent audits of the same code are two catches, and a bug reported by both is a marked animal caught twice.

**Build.** Two classic estimators:

- **Lincoln and Petersen**, with Chapman's correction for small samples: with *n1* bugs in the first catch, *n2* in the second and *m* in both, the estimate is (*n1*+1)(*n2*+1)/(*m*+1) − 1, with an approximate 95% interval from its variance;
- **Chao1**, for several catches: with *S* bugs seen at all, *f1* seen in exactly one catch and *f2* in exactly two, the estimate is *S* + *f1*(*f1*−1) / (2(*f2*+1)). It is a lower bound by design.

Both assume every bug is equally easy to catch. That is false for bugs, as it is for animals: some bugs are obvious and some are subtle. The test below measures what that does to the estimates before we trust them on our data.

#%% code
def chapman(n1, n2, m):
    """Lincoln-Petersen estimate with Chapman's correction, and an approximate 95% interval."""
    est = (n1 + 1) * (n2 + 1) / (m + 1) - 1
    var = (n1 + 1) * (n2 + 1) * (n1 - m) * (n2 - m) / ((m + 1) ** 2 * (m + 2))
    return est, max(est - 1.96 * var ** 0.5, max(n1, n2)), est + 1.96 * var ** 0.5


def chao1(catches):
    """Chao1 lower-bound estimate of the population from a list of sets (one per catch)."""
    counts = collections.Counter(x for c in catches for x in c)
    f1 = sum(v == 1 for v in counts.values())
    f2 = sum(v == 2 for v in counts.values())
    return len(counts) + f1 * (f1 - 1) / (2 * (f2 + 1))

show_def(chapman, chao1)

#%% md
**Test.** A simulated audit of a population of 100 bugs, caught twice, 2,000 times over. In the *equal* world every bug is caught with probability 0.5 in each catch. In the *unequal* world each bug has its own catchability, drawn from a distribution with the same mean but some bugs very easy and some very hard. The estimators should be close to 100 in the first world, and the second world shows how far real heterogeneity pulls them down.

#%% code
def simulate(n=100, sims=2000, unequal=False, seed=SEED):
    """Chapman estimates and interval coverage over simulated two-catch audits of n bugs."""
    rng_ = np.random.default_rng(seed)
    ests, covered = [], 0
    for _ in range(sims):
        p = rng_.beta(0.6, 0.6, n) if unequal else np.full(n, 0.5)
        c1, c2 = rng_.random(n) < p, rng_.random(n) < p
        est, lo, hi = chapman(int(c1.sum()), int(c2.sum()), int((c1 & c2).sum()))
        ests.append(est)
        covered += lo <= n <= hi
    return np.array(ests), covered / sims

show_def(simulate)
SIM = {"equal": simulate(), "unequal": simulate(unequal=True)}
for k, (e, cov) in SIM.items():
    print(f"[simulate] {k:<7} catchability: median estimate {np.median(e):.0f} of 100; the 95% interval covered the truth {cov:.0%} of the time")

#%% md
**Live.** No new calls. Each of the fixed plan's three runs is one catch: the set of places its verification confirmed. First the estimators are applied the way they would be in real work, to confirmed places, with no key. Then, as a check on the method, to the planted bugs the runs found, which needs the key but isolates the estimator from false alarms.

#%% code
CATCH_PLACES = [{key_of(f) for f in kit.trace["confirmed"]} for _, kit, _ in C_OBJS]
CATCH_BUGS = [set(match(as_findings(kit.trace["confirmed"])).found) for _, kit, _ in C_OBJS]
ESTIMATES_LEFT = []
for name, catches in (("confirmed places (no key)", CATCH_PLACES), ("planted bugs found (with the key)", CATCH_BUGS)):
    n1, n2, m = len(catches[0]), len(catches[1]), len(catches[0] & catches[1])
    est, lo, hi = chapman(n1, n2, m)
    ESTIMATES_LEFT.append({"catches": name, "seen": len(set().union(*catches)), "chapman": est, "low": lo, "high": hi,
                           "chao1": chao1(catches), "n1": n1, "n2": n2, "both": m})
table(ESTIMATES_LEFT, [("catches", "what is counted", ""), ("n1", "run 0", "d"), ("n2", "run 1", "d"), ("both", "in both", "d"),
                       ("seen", "seen in 3 runs", "d"), ("chapman", "Chapman (runs 0, 1)", ".0f"), ("low", "95% low", ".0f"),
                       ("high", "95% high", ".0f"), ("chao1", "Chao1 (3 runs)", ".0f")])
print(f"[left] the answer key holds {len(ANSWER_KEY)} planted bugs")

#%% code
# FIG  estimating what is left: the method on simulated audits, then on ours
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5))
ax = axes[0]
for k, colour in (("equal", C1), ("unequal", C2)):
    ax.hist(SIM[k][0], bins=40, range=(40, 160), color=colour, alpha=0.6, label=f"{k} catchability ({SIM[k][1]:.0%} covered)")
ax.axvline(100, color=INK, lw=1.2)
ax.set_xlabel("Chapman estimate of a population of 100")
ax.legend(fontsize=7.5)
panel(ax, "the estimator on 2,000 simulated audits")
ax = axes[1]
for i, r in enumerate(ESTIMATES_LEFT):
    ax.errorbar([r["chapman"]], [i], xerr=[[r["chapman"] - r["low"]], [r["high"] - r["chapman"]]], fmt="o", color=C1, capsize=4)
    ax.plot([r["chao1"]], [i - 0.15], "s", color=C7)
    ax.plot([r["seen"]], [i + 0.15], "^", color=MUTED)
ax.axvline(len(ANSWER_KEY), color=C8, lw=1.2)
ax.text(len(ANSWER_KEY), len(ESTIMATES_LEFT) - 0.4, f" {len(ANSWER_KEY)} planted", color=C8, fontsize=8)
ax.set_yticks(range(len(ESTIMATES_LEFT)), [r["catches"] for r in ESTIMATES_LEFT], fontsize=8)
ax.set_ylim(-0.6, len(ESTIMATES_LEFT) - 0.2)
ax.set_xlabel("bugs (circle: Chapman with interval; square: Chao1; triangle: seen)")
panel(ax, "our three runs as three catches")
r_key = ESTIMATES_LEFT[1]
finish(fig, "s46_left", f"From the runs alone, Chapman estimated {r_key['chapman']:.0f} planted bugs in all; the key holds {len(ANSWER_KEY)}",
       "left: 2,000 simulated two-catch audits per world; right: the fixed plan's runs 0 and 1 (Chapman) and all three (Chao1)")

#%% md
**Evidence. Reading FIG {{figures.s46_left}} (s46_left).** Left: when every bug is equally easy to catch, the Chapman estimate centres on the truth and its interval covers it {{left.cover_equal|.0%}} of the time. When catchability varies, the estimate drops below the truth and the interval covers it only {{left.cover_unequal|.0%}} of the time: easy bugs are caught twice, hard bugs never, and the method cannot see the hard ones. Right: on our runs, counting planted bugs, Chapman estimated {{left.est_bugs|.0f}} (interval {{left.low_bugs|.0f}} to {{left.high_bugs|.0f}}) against the {{answer_key.bugs}} in the key. Counting confirmed places without the key, it estimated {{left.est_places|.0f}}. Read the estimate as a floor, not a count: if two independent audits keep reporting the same bugs, there are probably few easy bugs left, and very little can be said about the hard ones.

#%% code
save_exp("left", {"rows": ESTIMATES_LEFT, "cover_equal": SIM["equal"][1], "cover_unequal": SIM["unequal"][1],
                  "median_equal": float(np.median(SIM["equal"][0])), "median_unequal": float(np.median(SIM["unequal"][0])),
                  "est_bugs": ESTIMATES_LEFT[1]["chapman"], "low_bugs": ESTIMATES_LEFT[1]["low"], "high_bugs": ESTIMATES_LEFT[1]["high"],
                  "est_places": ESTIMATES_LEFT[0]["chapman"]})
results = []
expect("with equal catchability the estimator is centred on the truth", abs(np.median(SIM["equal"][0]) - 100) <= 3)
expect("with equal catchability the interval covers the truth at least 90% of the time", SIM["equal"][1] >= 0.9)
expect("unequal catchability pulls the estimate down", np.median(SIM["unequal"][0]) < np.median(SIM["equal"][0]))
expect("Chapman on two identical catches returns their size", abs(chapman(10, 10, 10)[0] - 10) < 1e-9)

#%% md
## S47 - Card: dedupe, the report, and a completeness critic

**Why.** Three lenses over the same shard often report the same place. Without merging, each duplicate costs skeptic calls of its own; with merging, the duplicates become one place with a higher report count. At the other end, the report groups confirmed places into root causes. And a run that confirmed nothing in a whole folder may have examined it badly rather than found it clean. A **completeness critic** reads the per-folder statistics of a finished audit, and nothing else, and names the folders it would look at again.

**Build.** The critic is one worker. Its input is a table of folders with files, findings, places and confirmed places; its output is up to five folders with a reason each.

**Live.** The dedupe and report numbers come from the fixed plan's three runs, free. The critic makes one call per run. Its value can be measured against the key: if the planted bugs the run missed are concentrated in the folders the critic named, the critic is pointing the next round in the right direction.

#%% code
CRITIC_SYSTEM = """You review the coverage of a finished code audit. You get one line per folder: how many files it has, how many findings the readers reported there, how many distinct places those findings named, and how many places the checkers confirmed.

Name up to five folders where you would look again, because the numbers suggest the readers examined them less well than the rest, not because a folder is large. Answer with one JSON object and nothing else: {"folders": [{"folder": "...", "why": "..."}]}."""
CRITIC_SCHEMA = {"type": "object", "required": ["folders"], "properties": {"folders": {"type": "array", "items": {
    "type": "object", "required": ["folder"], "properties": {"folder": {"type": "string"}, "why": {"type": "string"}}}}}}


def folder_table(kit):
    """Per folder: files, findings, places and confirmed places of one run."""
    rows = {f: {"folder": f, "files": n, "findings": 0, "places": 0, "confirmed": 0}
            for f, n in collections.Counter(p.split("/")[0] for p in WORK).items()}
    for f in kit.trace["found"]:
        if f["file"] in CORPUS:
            rows[f["file"].split("/")[0]]["findings"] += 1
    for f in dedupe(kit.trace["found"]):
        if f["file"] in CORPUS:
            rows[f["file"].split("/")[0]]["places"] += 1
    for f in kit.trace["confirmed"]:
        if f["file"] in CORPUS:
            rows[f["file"].split("/")[0]]["confirmed"] += 1
    return sorted(rows.values(), key=lambda r: r["folder"])


@SCRIPTED.register
def _critic(model, messages, params):
    if not messages[0]["content"].startswith("You review the coverage of a finished code audit"):
        return None
    rows = re.findall(r"^(\S+): (\d+) files, (\d+) findings, (\d+) places, (\d+) confirmed$", messages[-1]["content"], re.M)
    low = sorted(rows, key=lambda r: (int(r[4]) / max(1, int(r[1])), -int(r[1])))[:5]
    return json.dumps({"folders": [{"folder": r[0], "why": "few confirmed places for its size"} for r in low]})

show_def(folder_table, _critic)

#%% code
CRITIC_ROWS = []
for (run, kit, result), r in zip(C_OBJS, range(RUNS)):
    page = "\n".join(f"{x['folder']}: {x['files']} files, {x['findings']} findings, {x['places']} places, {x['confirmed']} confirmed"
                     for x in folder_table(kit))
    crun = Run(f"critic for run {r}", run_id=f"s47-critic-{r}", concurrency=1)
    obj = crun.run_sync(lambda c: c.agent(data=page, system=CRITIC_SYSTEM, schema=CRITIC_SCHEMA, model="lead", label="critic",
                                          role="critic", sample=r))
    named = {x.get("folder", "") for x in (obj or {}).get("folders", [])}
    found_ids = set(outcome(result, kit)["found_ids"])
    missed = [b for b in ANSWER_KEY if b["id"] not in found_ids]
    in_named = sum(b["folder"] in named for b in missed)
    share_files = sum(1 for p in WORK if p.split("/")[0] in named) / len(WORK)
    CRITIC_ROWS.append({"run": r, "named": ", ".join(sorted(named)), "missed": len(missed), "missed_in_named": in_named,
                        "share_missed": in_named / max(1, len(missed)), "share_files": share_files,
                        "lift": (in_named / max(1, len(missed))) / max(share_files, 1e-9), "findings": len(kit.trace["found"]),
                        "places": len(dedupe(kit.trace["found"])), "confirmed": len(kit.trace["confirmed"]),
                        "reported": len(result["bugs"]), "merged": sum(len(b["merged"]) > 1 for b in result["bugs"]),
                        "left_out": result["left_out"]})
for c in CRITIC_ROWS:
    c["calls_saved"] = 3 * (math.ceil(c["findings"] / 6) - math.ceil(c["places"] / 6))
table(CRITIC_ROWS, [("run", "run", "d"), ("findings", "findings", "d"), ("places", "places", "d"), ("calls_saved", "skeptic calls saved", "d"),
                    ("confirmed", "confirmed", "d"), ("reported", "report entries", "d"), ("merged", "merged groups", "d"),
                    ("left_out", "added back", "d")])
table(CRITIC_ROWS, [("run", "run", "d"), ("named", "folders the critic named", ""), ("missed", "planted bugs missed", "d"),
                    ("missed_in_named", "of them in named folders", "d"), ("share_files", "share of files named", ".2f"),
                    ("lift", "lift", ".1f")])

#%% code
# FIG  what merging saves, and whether the critic points at the misses
fig, axes = plt.subplots(1, 2, figsize=(10.6, 3.5))
ax = axes[0]
stages = ["findings", "places", "confirmed", "reported"]
for c, colour in zip(CRITIC_ROWS, (C1, C7, C3)):
    ax.plot(stages, [c[s] for s in stages], "o-", color=colour, label=f"run {c['run']}")
ax.set_ylabel("count")
ax.legend(fontsize=7.5)
panel(ax, "from findings to the report, per run")
ax = axes[1]
x = np.arange(len(CRITIC_ROWS))
ax.bar(x - 0.18, [c["share_files"] for c in CRITIC_ROWS], 0.36, color=MUTED, label="share of files in the named folders")
ax.bar(x + 0.18, [c["share_missed"] for c in CRITIC_ROWS], 0.36, color=C2, label="share of missed bugs in them")
ax.set_xticks(x, [f"run {c['run']}" for c in CRITIC_ROWS])
ax.set_ylim(0, 1)
ax.legend(fontsize=7.5)
panel(ax, "the critic's folders against the misses")
mean_lift = float(np.mean([c["lift"] for c in CRITIC_ROWS]))
finish(fig, "s47_merge_critic", f"Merging saved {np.mean([c['calls_saved'] for c in CRITIC_ROWS]):.0f} skeptic calls per run; "
       f"the critic's folders held missed bugs at {mean_lift:.1f} times their share of files",
       "the fixed plan's three runs; one critic call per run, which saw only per-folder counts")

#%% md
**Evidence. Reading FIG {{figures.s47_merge_critic}} (s47_merge_critic).** Left: each run went from {{merge.findings|.0f}} findings to {{merge.places|.0f}} places on average, so merging saved about {{merge.calls_saved|.0f}} skeptic calls per run before anything else happened. The report then grouped {{merge.merged|.1f}} sets of places per run into shared root causes and added back {{merge.left_out|.1f}} that it forgot. Right: the folders the critic named held {{merge.share_files|.0%}} of the files and {{merge.share_missed|.0%}} of the planted bugs the run missed, a lift of {{merge.lift|.1f}}. A lift above 1 means the critic's suggestions would aim a second round better than chance; a lift near or below 1 means they would not. One call per run is cheap, but a second round aimed by a critic is not, so the critic is only worth keeping where its lift is clearly above 1; S55 records it without a verdict.

#%% code
save_exp("merge", {"rows": CRITIC_ROWS, "findings": float(np.mean([c["findings"] for c in CRITIC_ROWS])),
                   "places": float(np.mean([c["places"] for c in CRITIC_ROWS])), "calls_saved": float(np.mean([c["calls_saved"] for c in CRITIC_ROWS])),
                   "merged": float(np.mean([c["merged"] for c in CRITIC_ROWS])), "left_out": float(np.mean([c["left_out"] for c in CRITIC_ROWS])),
                   "share_files": float(np.mean([c["share_files"] for c in CRITIC_ROWS])),
                   "share_missed": float(np.mean([c["share_missed"] for c in CRITIC_ROWS])), "lift": mean_lift})
results = []
expect("merging never increases the count", all(c["places"] <= c["findings"] for c in CRITIC_ROWS))
expect("the per-folder table covers every file", all(sum(x["files"] for x in folder_table(kit)) == len(WORK) for _, kit, _ in C_OBJS))
expect("the critic named at least one folder in every run", all(c["named"] for c in CRITIC_ROWS))
