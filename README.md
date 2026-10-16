# Dynamic Workflow Agents

Two self-contained editions of **Dynamic Workflows from Scratch**, a hands-on Python notebook that builds a small multi-agent runtime and tests when a lead-directed workflow helps. The lead writes a phased plan; the runtime runs parallel workers, keeps per-worker threads and events, and enforces a resumable spending budget. The main experiment asks agents to find 72 planted bugs in a roughly 100,000-line algorithm corpus. Later sections apply the same runtime to grading and customer-message analysis.

| Edition | Notebook | Provider used for the recorded run | Accounting in the notebook |
| --- | --- | --- | --- |
| Claude | [`claude/dynamic_workflows.ipynb`](claude/dynamic_workflows.ipynb) | Anthropic API | Per token, tracked in cents; 2,500-cent cap |
| Qwen | [`qwen/dynamic_workflows.ipynb`](qwen/dynamic_workflows.ipynb) | ModelScope's Qwen endpoint | Per call, tracked in Magicubes; 1,500-Magicube cap |

Both notebooks include executed outputs and figures. The Claude edition was run, replayed offline, and checked against its live results. The Qwen edition completed a live run and passes the notebook checks; its final offline replay and prose audit against the live outputs have **not** yet been completed. Treat its narrative conclusions as provisional until those steps are done. A free smoke run uses scripted answers: its numbers are synthetic and are not experimental results.

## Start here

Install Python 3.11 or newer and [uv](https://docs.astral.sh/uv/). Clone this private repository, then work **inside one edition directory**. Each edition has its own `pyproject.toml`, environment, data, ledger, and generated results. The notebook finds its root from the nearest `pyproject.toml`; keeping the working directory inside the selected edition prevents results from going into the other one.

```powershell
git clone https://github.com/FareedKhan-dev/dynamic-workflow-agents.git
cd dynamic-workflow-agents/claude # or: cd dynamic-workflow-agents/qwen
uv sync --locked --group lab
uv run python _build/checks.py
uv run --group lab jupyter lab
```

Open `dynamic_workflows.ipynb` in JupyterLab and select the Python kernel from this edition's `.venv`. The saved notebook can be read without a key. If JupyterLab does not select the environment automatically, register its kernel with `uv run python -m ipykernel install --user --name dynamic-workflows-claude --display-name "Dynamic Workflows (Claude)"` (substitute `qwen` in the name for that edition), then choose it in JupyterLab.

The two editions contain comparable lessons, but their requests, price accounting, model roles, and recorded results differ. Do not point one edition at the other's ledger.

## Rebuild and run

Run these commands from the edition directory. The same commands work in PowerShell, Bash, and other shells once `uv` is on `PATH`.

```text
uv run python _build/run.py smoke             # scripted model; no API key or model charges
uv run python _build/run.py replay            # recorded answers only; no model calls
uv run python _build/run.py collect           # live calls; requires the edition's API key
uv run python _build/checks.py                # validate the executed notebook
```

`smoke` writes its notebook and experiment records under `_build/out/`. It also rebuilds the local algorithm corpus in `data/`, so expect generated data files to change. The scripted numbers are invented to exercise the code. `replay` uses `artifacts/cache/ledger.sqlite`; it rewrites the edition's notebook and results without contacting a provider. It fails if an answer needed by the current source is missing from the ledger. `collect` first reuses matching ledger answers, then pays for missing ones. It rewrites the notebook, records, and run traces. A full execution takes time because the notebook runs hundreds of cells and many model turns.

The optional `--upto NN` argument runs only source files through number `NN`, for example `uv run python _build/run.py smoke --upto 24`. A partial `collect` or `replay` writes a partial notebook, so use a separate branch or commit the complete notebook first if you want to preserve it.

For a live run, set `CLAUDE_API_KEY` in the Claude edition or `MODELSCOPE_API_KEY` in the Qwen edition through your shell or secret manager. Never put a key in a notebook, tracked file, command argument, or commit. Budget caps are defined in each edition's `_build/src/10_part1_setup.py`; review them and the provider's current prices before running `collect`. The values in this repository describe the recorded experiments and are not a promise about future pricing or model availability.

To regenerate a notebook **without executing it**, run `uv run python _build/build.py build`. This produces empty code outputs and unresolved prose placeholders. Run `replay` or `collect` to obtain a complete notebook. `_build/diagrams.py` draws the source diagrams if you change them; the PNGs already needed by the builder are included in `_build/diagrams/`.

## Repository map

```text
dynamic-workflow-agents/
├── README.md
├── claude/
│   ├── dynamic_workflows.ipynb
│   ├── pyproject.toml, uv.lock
│   ├── _build/
│   │   ├── src/                # editable, percent-format notebook sources
│   │   ├── diagrams/           # images attached during the build
│   │   └── build.py, run.py, checks.py, diagrams.py
│   ├── data/                   # source datasets and the algorithm benchmark
│   └── artifacts/              # answer ledger, experiment records, figures, run traces
└── qwen/                       # same structure, isolated from the Claude edition
```

Edit `_build/src/NN_*.py` when changing a lesson. `#%% md` and `#%% code` delimit notebook cells. `_build/build.py` assembles these sources, attaches PNG diagrams, and fills `{{record.key}}` references from `artifacts/exp_*.json` after execution. The `.ipynb` files are the readable, executed deliverables; the source files are the maintainable version. `_build/checks.py` checks style, filled placeholders, cell outputs, figure references, and several integrity rules.

`data/algorithms/original/` is the fixed upstream snapshot. Part I filters and tests it, then creates `audited/` with planted faults and `hidden/` with the answer key. The saved generated copies are included so the executed notebook's benchmark can be inspected directly and individual later cells have their expected files. **Do not give workers access to `hidden/`** when adapting the experiment. `data/homework/` and `data/intents/` contain the other two input datasets. Each upstream dataset's license notice is kept alongside it.

The versioned `artifacts/cache/ledger.sqlite` files contain the paid model responses required for offline replay; `artifacts/runs/` contains event and thread traces, including the original timing evidence; `artifacts/exp_*.json` supplies the prose figures. These are research records, not disposable cache files. Backup ledgers, temporary notebooks, screenshots, personal notes, and local environments are excluded.

## Interpreting the results

The benchmark is a planted-bug audit, not a general measure of software engineering skill. Both editions use one algorithm library and one model family each. The single-agent baseline can stop before reading the whole corpus, and three runs per arm give wide uncertainty intervals. The notebook shows both gains and failures; consult its executed tables and traces rather than treating every feature as an improvement. The Qwen prose still needs a line-by-line comparison with its completed live run.

This repository has no blanket license for the notebook or build code. The included datasets retain their own license files.
