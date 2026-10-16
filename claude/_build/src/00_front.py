#%% md
# Dynamic Workflows from Scratch
### A lead agent that writes its own plan: many workers in phases, one answer back, and a budget that can pause it

This notebook builds a small multi-agent system and then tries hard to show where it helps and where it does not. A **lead agent** reads a big job, writes a short plan with numbered phases, and hands the plan to a **runtime**. The runtime runs every phase in the background with many **workers** at once, waits for the slowest one, passes the results on, and gives the lead back a single combined answer. You can follow the run phase by phase, open the log of any worker, and cap what it may spend. When the cap is reached the work pauses, and when you raise it the work carries on from where it stopped.

**The idea in one line.** When a job is too big for one model's context, let a model write the plan, let plain code run it, and check both with tests that know the answer.

**What this notebook teaches.**

- How to build every piece yourself, in plain Python: a streaming client, a ledger that makes every run replayable, rate control, workers with readable threads, an event stream, `parallel()` and `pipeline()`, a budget that pauses and resumes, background runs, resume after a crash, and limits that say what they dropped (Parts II and IV).
- How a lead writes a plan, first as JSON data and then as a small checked program, and how a plan is checked, rehearsed and priced before it may spend anything (Part V).
- Which quality patterns earn their cost, measured one at a time on a job with a hidden answer key (Parts VI and VII).
- That the same engine runs other jobs unchanged, and when it should not be used at all (Part VIII).
- How to check your own measurements: the scorer, the judges, memory of the training data, and the bugs we made ourselves (Part IX).

**What is deliberately not claimed.**

- That these numbers carry over to other models, other libraries or other jobs. They come from one library, one model family and one provider (S68).
- That planted one-line bugs are like real bugs. They are a measurable stand-in; S66 looks at the real ones the workers found anyway.
- That more agents are always better. Part VIII ends with two jobs where the workflow is not expected to help, and measures what happens.

**About the outputs.** Every model answer this notebook shows is stored in a ledger (S8). The committed outputs come from one live run, and the same notebook replays from the ledger offline, call for call, at no cost (S74). Every number quoted in the prose is filled in from the records the code wrote, never typed by hand.

#%% md
## Results at a glance

Read from the records of Parts VII and VIII. Each row names the section that measured it, and each comparison carries its interval there.

| question | what was measured | where |
|---|---|---|
| Does the dynamic workflow find more planted bugs than one agent alone? | recall {{main.D_mean\|.2f}} against {{main.A_mean\|.2f}}; difference {{main.DA_lo\|+.2f}} to {{main.DA_hi\|+.2f}} (95%) | S52 |
| And when one agent gets about the same budget? | recall {{main.A2_mean\|.2f}} for one agent given {{main.A2_cost\|.1f}} cents | S52 |
| Against a plan written by hand? | difference {{main.DC_lo\|+.2f}} to {{main.DC_hi\|+.2f}} | S52 |
| What did a run cost? | {{main.D_cost\|.1f}} cents per dynamic run; {{main.A_cost\|.1f}} for one agent alone | S52 |
| Grading 600 homework solutions | accuracy {{hw_run.wf_acc\|.2f}} for the workflow, {{hw_run.single_acc\|.2f}} for one grader reading them all | S59 |
| Sorting ten thousand customer messages | agreement with the hidden intents (ARI) {{intents.ari\|.2f}}; one call alone labelled {{intents.one_share\|.0%}} of them | S60 |
| A job of five items | accuracy {{controls.tiny_wf\|.2f}} for {{controls.tiny_wf_cost\|.1f}} cents against {{controls.tiny_one\|.2f}} for {{controls.tiny_one_cost\|.1f}} | S61 |
| Claims fixed before the runs | {{claims.supported}} of {{claims.total}} SUPPORTED, {{claims.not_supported}} NOT SUPPORTED, {{claims.reported}} REPORTED | S69 |

#%% md
## New to agents? A working vocabulary

| word | meaning here |
|---|---|
| **model** | a large language model behind an API: text in, text out |
| **agent** | a model call with a role, instructions and sometimes tools, used as a step in a program |
| **lead** | the agent that reads the job and writes the plan; it never does the work itself |
| **worker** | an agent that does one piece of the work, such as reading one shard of code |
| **plan** | the lead's description of the work: phases, what each worker gets, how results combine |
| **phase** | one step of a plan; its workers run at the same time |
| **barrier** | the point where a phase waits for its slowest worker before the next phase starts |
| **pipeline** | the alternative to a barrier: each item moves to its next step as soon as it is ready |
| **fan-out, fan-in** | splitting work over many workers, and combining what they return |
| **run** | one execution of a plan, in the background, with a status you can ask for |
| **thread** | the whole conversation of one worker, kept so a person can read it afterwards |
| **event** | a short record the runtime emits, such as "phase started"; a run is followed through its events |
| **budget** | the meter for the session; at the cap new calls wait, and raising the cap lets them go on |
| **cent** | the notebook's unit of account; the provider bills per token, and every call's cost is converted to cents |
| **ledger** | a database of every call and answer; it is the cache, the accounts and the replay source |
| **replay** | running the notebook again with every answer read from the ledger: free, offline, identical |
| **schema** | the shape a model's JSON answer must have; answers are checked against it and repaired once |
| **lens** | a point of view given to a worker, such as "boundaries" or "logic", so different workers look for different things |
| **skeptic** | an agent asked to refute a finding; a finding stands when enough skeptics fail to refute it |
| **planted bug** | a one-line change we made on purpose, proven to break the code; the answer key lists them |
| **recall, precision** | the share of planted bugs found, and the share of reports that were real |
| **doctest** | an example in a function's docstring that runs as a test |

#%% md
## The whole system on one page

![system](attachment:system.png)

The lead (purple) scouts the job, writes a plan, checks it and prices it with a dry run before anything is spent. The runtime (blue) runs the plan's phases in the background, many workers per phase, and returns one answer. Five services are shared by everything: one budget, one ledger, one event stream, the threads, and a rate gate per model.

![one_run](attachment:one_run.png)

One run, as its events see it. Each bar is a worker. The run pauses when the budget's cap is reached, and continues when the cap is raised; work already done is never repeated.

## How to read a section

Every section follows the same rhythm. **Theory.** says what problem the section solves and why the obvious approach fails. **In plain terms.** says the same thing in two sentences without jargon. **For teams.** says what a team building this for real should take away. Then comes the code, one function per cell, each followed by a short summary line printed by `show_def`, then a demonstration that prints what happened, then a figure, and then **Reading FIG N.**, which says what to look at in it. Lines that start with `PASSED` are tests that ran in that cell; a test that does not hold prints `FAILED` instead.

Parts V and VI present features as **cards**: why the feature exists, how it is built, a test, a live run, the evidence, and the verdict from the ablation of S55.

![ways](attachment:ways.png)
