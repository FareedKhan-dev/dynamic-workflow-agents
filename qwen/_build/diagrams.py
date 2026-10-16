"""Draw every diagram of the notebook as a PNG in _build/diagrams/.

    .venv/bin/python _build/diagrams.py            draw all
    .venv/bin/python _build/diagrams.py part1_map  draw one

The diagrams share the notebook's palette and one visual language: rounded boxes for things,
arrows for what flows, blue for the system being built, grey for what is outside it, red for
failure paths, and short labels a student can read without the prose.
"""
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Circle

OUT = Path(__file__).resolve().parent / "diagrams"
C1, C2, C3, C4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
C5, C6, C7, C8 = "#e87ba4", "#008300", "#4a3aa7", "#e34948"
INK, INK2, MUTED, GRID, SURF = "#0b0b0b", "#52514e", "#8a8880", "#e6e5e1", "#fcfcfb"
LIGHT = {C1: "#e3eefb", C2: "#fdebe2", C3: "#e0f5ec", C4: "#fdf1d6", C7: "#e7e4f5", C8: "#fbe3e3", MUTED: "#f0efec"}
REGISTRY = {}


def diagram(name):
    def reg(fn):
        REGISTRY[name] = fn
        return fn
    return reg


def canvas(w, h):
    fig = plt.figure(figsize=(w, h), dpi=110)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.axis("off")
    fig.patch.set_facecolor(SURF)
    return fig, ax


def box(ax, x, y, w, h, text, color=C1, fill=True, size=9, weight="normal", text_color=INK, ls="-"):
    """A rounded box centred on (x, y)."""
    face = LIGHT.get(color, "#ffffff") if fill else SURF
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h, boxstyle="round,pad=0.02,rounding_size=0.08",
                                linewidth=1.3, edgecolor=color, facecolor=face, linestyle=ls))
    ax.text(x, y, text, ha="center", va="center", fontsize=size, color=text_color, weight=weight, wrap=True)


def arrow(ax, x0, y0, x1, y1, color=INK2, text=None, size=8, rad=0.0, lw=1.2, style="-|>"):
    ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle=style, mutation_scale=11, color=color,
                                 linewidth=lw, connectionstyle=f"arc3,rad={rad}"))
    if text:
        ax.text((x0 + x1) / 2, (y0 + y1) / 2 + 0.12, text, ha="center", va="bottom", fontsize=size, color=INK2)


def title(ax, x, y, text, size=12):
    ax.text(x, y, text, ha="left", va="top", fontsize=size, color=INK, weight="bold")


def save(fig, name):
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.png", facecolor=SURF)
    plt.close(fig)


def part_map(name, part, heading, steps, color=C1):
    """A Part map: the Part's sections as a row of boxes, read left to right."""
    n = len(steps)
    w = max(9.5, 1.85 * n + 0.6)
    fig, ax = canvas(w, 2.3)
    title(ax, 0.3, 2.15, f"{part}  {heading}", 11)
    bw = (w - 0.6) / n - 0.25
    for i, (sec, label) in enumerate(steps):
        x = 0.3 + (bw + 0.25) * i + bw / 2
        box(ax, x, 1.0, bw, 1.0, f"{sec}\n{label}", color=color, size=8.2)
        if i < n - 1:
            arrow(ax, x + bw / 2 + 0.02, 1.0, x + bw / 2 + 0.23, 1.0)
    save(fig, name)


@diagram("part1_map")
def _part1():
    part_map("part1_map", "Part I", "the problem, measured before anything is built",
             [("S0", "setup and\nhouse style"), ("S1", "the library\n(102k lines)"), ("S2", "planting\nbugs"),
              ("S3", "hiding the\nanswer key"), ("S4", "the scorer")], color=MUTED)




@diagram("planting")
def _planting():
    fig, ax = canvas(10.5, 2.7)
    title(ax, 0.3, 2.55, "Planting a bug: change one line, then prove the change matters", 11)
    steps = [("correct file\n(all examples pass)", MUTED), ("one small edit\n(mutation operator)", C2),
             ("run its examples\nin a clean Python", C1), ("some fail, but\nat most 40%", C3), ("planted bug\n+ its evidence", C3)]
    xs = [1.15, 3.2, 5.25, 7.3, 9.35]
    for (t, c), x in zip(steps, xs):
        box(ax, x, 1.45, 1.75, 0.95, t, color=c, size=8.5)
    for a, b in zip(xs, xs[1:]):
        arrow(ax, a + 0.9, 1.45, b - 0.9, 1.45)
    ax.text(5.25, 0.55, "none fail: discarded (maybe equivalent)    most fail: discarded (too loud)    hangs: discarded",
            ha="center", fontsize=8, color=C8)
    arrow(ax, 6.2, 0.98, 6.2, 0.72, color=C8)
    save(fig, "planting")



@diagram("part2_map")
def _part2():
    part_map("part2_map", "Part II", "talking to models",
             [("S5", "credentials"), ("S6", "streaming\nclient"), ("S7", "quota\nheaders"), ("S8", "the ledger"),
              ("S9", "front door +\nscripted model"), ("S10", "rate control\n(AIMD)"), ("S11", "probing\nsix models"),
              ("S12", "structured\noutput"), ("S13", "decision\nmeasurement")], color=C1)



@diagram("aimd")
def _aimd():
    fig, ax = canvas(10.5, 2.9)
    title(ax, 0.3, 2.75, "Slow start, then AIMD: how the gate finds the server's limit", 11)
    box(ax, 1.4, 1.35, 2.0, 1.0, "slow start\ndouble the limit\nafter each good window", color=C3, size=8.2)
    box(ax, 4.6, 1.35, 2.2, 1.0, "additive increase\n+1 after each\ngood window", color=C1, size=8.2)
    box(ax, 8.2, 1.35, 2.4, 1.0, "multiplicative decrease\nhalve the limit\non a 429", color=C8, size=8.2)
    arrow(ax, 2.45, 1.35, 3.45, 1.35, text="first 429", color=C8)
    arrow(ax, 5.75, 1.55, 6.95, 1.55, text="429", color=C8)
    arrow(ax, 6.95, 1.15, 5.75, 1.15, text="next good window", color=C1)
    ax.text(5.25, 0.35, "a 'good window' is as many successful calls as the current limit; the limit never drops below 1",
            ha="center", fontsize=8, color=INK2)
    save(fig, "aimd")



@diagram("part3_map")
def _part3():
    part_map("part3_map", "Part III", "one agent alone, and why it stalls",
             [("S14", "tools behind\nthe path guard"), ("S15", "the fenced\nsandbox"), ("S16", "the agent\nloop"),
              ("S17", "baseline A:\none agent alone"), ("S18", "baseline B:\nlead + helpers"), ("S19", "what the\nbaselines teach")], color=MUTED)


@diagram("agent_loop")
def _agent_loop():
    fig, ax = canvas(10.5, 3.0)
    title(ax, 0.3, 2.85, "The agent loop: ask, act, observe, repeat", 11)
    box(ax, 1.4, 1.5, 2.0, 0.9, "conversation\n(system, task,\nturns so far)", color=MUTED, size=8.2)
    box(ax, 4.2, 1.5, 1.9, 0.9, "model\nreplies with one\nJSON action", color=C1, size=8.2)
    box(ax, 7.0, 1.5, 1.9, 0.9, "harness runs\nthe tool through\nthe path guard", color=C3, size=8.2)
    box(ax, 9.5, 1.5, 1.5, 0.9, "result\nappended", color=MUTED, size=8.2)
    arrow(ax, 2.45, 1.5, 3.2, 1.5)
    arrow(ax, 5.2, 1.5, 6.0, 1.5)
    arrow(ax, 8.0, 1.5, 8.7, 1.5)
    arrow(ax, 9.5, 1.0, 1.4, 1.0, rad=-0.25, color=INK2)
    ax.text(5.4, 0.25, "context too big? the harness replaces old turns with a summary it writes itself (compaction)",
            ha="center", fontsize=8, color=C8)
    save(fig, "agent_loop")



@diagram("part4_map")
def _part4():
    part_map("part4_map", "Part IV", "the runtime, one primitive at a time",
             [("S20", "a worker and\nits thread"), ("S21", "events"), ("S22", "the run and\nagent()"), ("S23", "parallel()\nand stragglers"),
              ("S24", "pipeline()"), ("S25", "hedged\nrequests"), ("S26", "the budget"), ("S27", "background\nruns"),
              ("S28", "resume"), ("S29", "backstops"), ("S30", "watching\na run")], color=C1)


@diagram("events")
def _events():
    fig, ax = canvas(10.5, 2.6)
    title(ax, 0.3, 2.45, "The event stream of one run", 11)
    ax.plot([0.6, 10.0], [1.2, 1.2], color=INK2, lw=1.2)
    marks = [(0.8, "created"), (1.8, "phase_started"), (2.8, "agent_started x 12"), (4.3, "agent_ended x 12"),
             (5.6, "phase_ended"), (6.6, "phase_started"), (7.6, "paused"), (8.4, "resumed"), (9.6, "ended")]
    for x, label in marks:
        colour = C8 if label in ("paused", "resumed") else C1
        ax.plot([x], [1.2], "o", color=colour, ms=7)
        ax.text(x, 1.45 if marks.index((x, label)) % 2 == 0 else 0.75, "run." + label, ha="center", fontsize=7.5,
                color=INK if colour == C1 else C8)
    ax.text(5.3, 0.25, "listeners subscribe with wildcards such as run.phase_*; a listener that crashes is counted, never fatal",
            ha="center", fontsize=8, color=INK2)
    save(fig, "events")


@diagram("budget")
def _budget():
    fig, ax = canvas(10.5, 2.7)
    title(ax, 0.3, 2.55, "One budget for the session, runs included", 11)
    box(ax, 1.5, 1.35, 2.1, 1.0, "a call asks to start\nreserve its price", color=C1, size=8.5)
    box(ax, 4.6, 1.35, 2.3, 1.0, "spent + reserved + price\nwithin the cap?", color=MUTED, size=8.5)
    box(ax, 7.6, 1.85, 1.9, 0.7, "yes: the call runs,\nthen settles", color=C3, size=8.2)
    box(ax, 7.6, 0.8, 1.9, 0.7, "no: it waits\n(the run is paused)", color=C4, size=8.2)
    box(ax, 9.8, 0.8, 1.0, 0.7, "cap\nraised", color=C8, size=8.2)
    arrow(ax, 2.6, 1.35, 3.45, 1.35)
    arrow(ax, 5.75, 1.55, 6.65, 1.85)
    arrow(ax, 5.75, 1.15, 6.65, 0.8)
    arrow(ax, 9.3, 0.8, 8.55, 0.8, color=C8)
    arrow(ax, 7.6, 1.15, 7.6, 1.5, color=C3)
    ax.text(5.3, 0.15, "the lead's calls and every run's calls go through the same meter; nothing is cancelled at the cap",
            ha="center", fontsize=8, color=INK2)
    save(fig, "budget")


@diagram("part5_map")
def _part5():
    part_map("part5_map", "Part V", "the lead writes the plan",
             [("S31", "the task\nkit"), ("S32", "plans as\ndata"), ("S33", "the scout"), ("S34", "the lead\nwrites JSON"),
              ("S35", "what JSON\ncannot say"), ("S36", "plans as\nprograms"), ("S37", "dry run and\napproval"),
              ("S38", "the lead writes\na program"), ("S39", "the showcase\nrun"), ("S40", "smaller\nbudget")], color=C7)


@diagram("verify")
def _verify():
    fig, ax = canvas(10.5, 3.0)
    title(ax, 0.3, 2.85, "Checking a finding: run its call, then let skeptics argue", 11)
    box(ax, 1.35, 1.45, 2.0, 1.1, "a finding\nfile, line, claim,\nfailing call, expected", color=C1, size=8.2)
    box(ax, 3.85, 1.45, 2.0, 1.1, "evidence\nthe call, run in\nthe sandbox", color=C3, size=8.2)
    for k, y in enumerate((2.2, 1.45, 0.7)):
        box(ax, 6.35, y, 1.75, 0.55, f"skeptic, sample {k}", color=C4, size=8.2)
        arrow(ax, 4.9, 1.45, 5.45, y)
        arrow(ax, 7.25, y, 7.95, 1.45)
    box(ax, 8.55, 1.45, 1.1, 0.8, "vote\n2 of 3", color=MUTED, size=8.4)
    box(ax, 9.85, 1.45, 1.0, 0.8, "confirmed", color=C3, size=8.2)
    arrow(ax, 2.38, 1.45, 2.82, 1.45)
    arrow(ax, 9.12, 1.45, 9.33, 1.45)
    ax.text(5.3, 0.12, "a skeptic sees the numbered function, the claim and what the code really returned; when unsure it says not real",
            ha="center", fontsize=8, color=INK2)
    save(fig, "verify")


@diagram("plans")
def _plans():
    fig, ax = canvas(10.5, 3.3)
    title(ax, 0.3, 3.15, "Two forms of plan, one path to a run", 11)
    box(ax, 1.25, 2.3, 1.9, 0.75, "plan as data\n(JSON)", color=C7, size=8.5)
    box(ax, 3.45, 2.3, 1.7, 0.75, "validate,\nthen compile", color=MUTED, size=8.3)
    box(ax, 1.25, 0.95, 1.9, 0.75, "plan as program\n(restricted Python)", color=C7, size=8.3)
    box(ax, 3.45, 0.95, 1.7, 0.75, "whitelist\ncheck", color=MUTED, size=8.3)
    box(ax, 5.6, 1.6, 1.6, 0.85, "dry run:\ncalls, Magicubes,\nphases", color=C1, size=8.0)
    box(ax, 7.45, 1.6, 1.4, 0.85, "approval\ngate", color=C4, size=8.3)
    box(ax, 9.35, 1.6, 1.6, 0.85, "run in the\nbackground", color=C3, size=8.3)
    arrow(ax, 2.2, 2.3, 2.6, 2.3)
    arrow(ax, 2.2, 0.95, 2.6, 0.95)
    arrow(ax, 4.3, 2.3, 4.8, 1.75, text="program text")
    arrow(ax, 4.3, 0.95, 4.8, 1.45)
    arrow(ax, 6.4, 1.6, 6.75, 1.6)
    arrow(ax, 8.15, 1.6, 8.55, 1.6)
    ax.text(5.3, 0.12, "errors go back to the lead for at most two repairs; nothing is paid for before the gate",
            ha="center", fontsize=8, color=INK2)
    save(fig, "plans")


@diagram("part6_map")
def _part6():
    part_map("part6_map", "Part VI", "quality patterns, one feature card each",
             [("S41", "lenses"), ("S42", "executable\nevidence"), ("S43", "how many\nskeptics"), ("S44", "judge from\nanother generation"),
              ("S45", "loop until\ndry"), ("S46", "how many\nbugs are left"), ("S47", "merging and\nthe critic"),
              ("S48", "model\nrouting"), ("S49", "shard size,\nwhole system")], color=C3)


@diagram("part7_map")
def _part7():
    part_map("part7_map", "Part VII", "experiments, registered before they are run",
             [("S50", "pre-\nregistration"), ("S51", "runner and\nguard"), ("S52", "five arms,\ncompared"), ("S53", "consistency"),
              ("S54", "a checked\nsimulator"), ("S55", "ablation\nledger"), ("S56", "error\nbudget"), ("S57", "crash and\nresume"),
              ("S58", "who finds\nwhat")], color=C2)


@diagram("part8_map")
def _part8():
    part_map("part8_map", "Part VIII", "same engine, different jobs",
             [("S59", "grading 600\nhomework solutions"), ("S60", "ten thousand\ncustomer messages"), ("S61", "when not\nto use it"),
              ("S62", "four plans,\nside by side")], color=C4)


@diagram("part9_map")
def _part9():
    part_map("part9_map", "Part IX", "checking our own work",
             [("S63", "was the\nscorer right?"), ("S64", "judges that\nearn their votes"), ("S65", "do the models\nremember it?"),
              ("S66", "bugs we\ndid not plant"), ("S67", "our own\nbugs"), ("S68", "threats to\nvalidity"), ("S69", "the claims\nthat survive"),
              ("S70", "what is\nstill open")], color=C7)


@diagram("part10_map")
def _part10():
    part_map("part10_map", "Part X", "operating it",
             [("S71", "where calls and\nMagicubes went"), ("S72", "your own\ntask"), ("S73", "what to\nswitch on first"),
              ("S74", "reproducing\nthis notebook"), ("S75", "the\nmanifest")], color=MUTED)


@diagram("system")
def _system():
    """The whole system on one page."""
    fig, ax = canvas(12.4, 6.2)
    title(ax, 0.3, 6.05, "The whole system on one page")
    box(ax, 1.1, 4.5, 1.5, 0.8, "your job\n(a big task)", color=MUTED, size=8.5)
    ax.add_patch(FancyBboxPatch((2.35, 2.95), 2.6, 2.55, boxstyle="round,pad=0.02,rounding_size=0.1", linewidth=1.4,
                                edgecolor=C7, facecolor=LIGHT[C7]))
    ax.text(3.65, 5.3, "the lead", ha="center", fontsize=10, weight="bold", color=C7)
    for i, s in enumerate(["scout the job", "write a plan (JSON or program)", "check it", "dry run: price it", "approve, or ask"]):
        ax.text(2.55, 4.85 - 0.38 * i, f"{i + 1}. {s}", fontsize=8.2, color=INK, va="center")
    arrow(ax, 1.85, 4.5, 2.33, 4.5)
    # the runtime
    ax.add_patch(FancyBboxPatch((5.45, 2.65), 4.9, 3.0, boxstyle="round,pad=0.02,rounding_size=0.1", linewidth=1.4,
                                edgecolor=C1, facecolor=LIGHT[C1]))
    ax.text(7.9, 5.42, "the runtime, in the background", ha="center", fontsize=10, weight="bold", color=C1)
    phases = [("phase 1\nscan", 6), ("phase 2\nverify", 4), ("phase 3\ncombine", 1)]
    for p, (label, n) in enumerate(phases):
        x = 6.25 + 1.6 * p
        ax.text(x, 4.95, label, ha="center", va="center", fontsize=8.2, color=INK)
        for k in range(n):
            ax.add_patch(Circle((x - 0.3 + 0.3 * (k % 3), 4.3 - 0.36 * (k // 3)), 0.12, color=C1, alpha=0.85))
        if p < 2:
            ax.plot([x + 0.72, x + 0.72], [3.0, 5.15], color=INK2, lw=1, ls=(0, (3, 2)))
    ax.text(7.9, 2.85, "dashed lines: barriers (a phase waits for its slowest worker)", ha="center", fontsize=7.4, color=INK2)
    arrow(ax, 4.97, 4.3, 5.43, 4.3, text="plan")
    box(ax, 11.4, 4.3, 1.5, 0.9, "one answer\nback to the lead", color=C3, size=8.2)
    arrow(ax, 10.37, 4.3, 10.63, 4.3)
    arrow(ax, 11.4, 4.78, 3.65, 5.58, rad=0.18, color=C3)
    ax.text(11.95, 5.25, "the lead\nwrites its memo", ha="center", fontsize=7.6, color=C3)
    # shared services
    services = [("budget", "pauses at the cap,\nresumes when raised", C2), ("ledger", "every call stored;\nreplay is free", C4),
                ("events", "a stream you\ncan follow", C1), ("threads", "each worker's\nlog, readable", C7),
                ("gate", "per-model\nrate control", C3)]
    for i, (name, text, col) in enumerate(services):
        x = 1.35 + 2.25 * i
        box(ax, x, 1.35, 2.0, 0.95, f"{name}\n{text}", color=col, size=7.8)
        arrow(ax, x, 1.85, min(max(x, 5.7), 10.1) if i else 3.6, 2.62 if i else 2.93, color=MUTED, lw=0.9)
    ax.text(6.2, 0.45, "shared by the lead and every run: one budget, one ledger, one event stream", ha="center", fontsize=8, color=INK2)
    save(fig, "system")


@diagram("one_run")
def _one_run():
    """One run, start to finish, as the events it emits."""
    fig, ax = canvas(12.4, 4.4)
    title(ax, 0.3, 4.25, "One run, start to finish, as the events it emits")
    ax.plot([0.6, 12.0], [1.0, 1.0], color=INK2, lw=1.2)
    events = [(0.8, "run.created", MUTED), (1.6, "phase_started\nScan", C1), (4.6, "phase_ended", C1), (5.1, "paused\n(cap reached)", C2),
              (6.2, "resumed\n(cap raised)", C3), (6.7, "phase_started\nVerify", C1), (9.3, "phase_ended", C1),
              (9.8, "phase_started\nReport", C1), (10.9, "phase_ended", C1), (11.6, "run.ended\ncompleted", C3)]
    for i, (x, label, col) in enumerate(events):
        ax.plot([x, x], [0.9, 1.1], color=col, lw=2)
        ax.text(x, 0.8 if i % 2 == 0 else 0.42, label, ha="center", va="top", fontsize=7.2, color=INK)
    lanes = [(1.6, [2.9, 3.4, 3.9, 4.2, 4.6, 3.1]), (6.7, [8.1, 9.3, 7.6, 8.8]), (9.8, [10.9])]
    for start, ends in lanes:
        for k, end in enumerate(ends):
            y = 1.45 + 0.3 * k
            ax.plot([start, end], [y, y], color=C1, lw=5, solid_capstyle="butt", alpha=0.8)
            ax.plot([max(ends)], [y], alpha=0)
    ax.axvspan(5.1, 6.2, ymin=0.25, ymax=0.78, color=LIGHT[C2])
    ax.text(5.65, 2.9, "work waits;\nnothing is lost", ha="center", fontsize=7.6, color=C2)
    ax.text(0.6, 3.8, "each bar is one worker (agent_started to agent_ended); its whole conversation is kept as a thread",
            fontsize=7.8, color=INK2)
    save(fig, "one_run")


@diagram("ways")
def _ways():
    """Four ways through the notebook."""
    fig, ax = canvas(12.4, 3.9)
    title(ax, 0.3, 3.75, "Four ways through")
    rows = [("students", "Parts I, IV, V and the In plain terms paragraphs; skip the statistics on a first read", C1),
            ("developers", "Part IV (the runtime), Part V (plans and their checks), Part X (use it on your own task)", C3),
            ("PhD and masters", "Part I (benchmark design), Part VII (pre-registered experiments), Part IX (threats)", C7),
            ("teams", "the For teams paragraphs, S55 (what each feature bought), S61 (when not to use it), S73", C2)]
    for i, (who, path, col) in enumerate(rows):
        y = 2.95 - 0.72 * i
        box(ax, 1.4, y, 2.1, 0.55, who, color=col, size=9, weight="bold")
        ax.text(2.7, y, path, va="center", fontsize=8.6, color=INK)
    save(fig, "ways")


# ---- main (keep last) ----
if __name__ == "__main__":
    names = sys.argv[1:] or list(REGISTRY)
    for n in names:
        REGISTRY[n]()
        print(f"[diagram] {n}.png")
