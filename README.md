# Luna

[English](#luna) | [Chinese](#chinese-version)

> A test-driven autonomous coding agent, built from scratch — with a cat-eared face.
> Hand it a repo and a red test suite; it locates the code, edits it, runs the tests,
> reads the red/green, and iterates until the suite is green. Every result is scored by
> an independent harness, so **pass@1 is an observed number, never the model's own word**.
> Drive it from the CLI, or chat with **Luna**, the catgirl assistant on the front.

<!-- badges: keep to 3-4, all must be real & green -->
![Python](https://img.shields.io/badge/python-3.9-blue)
![tests](https://img.shields.io/badge/tests-121%20passing-brightgreen)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

<!-- TODO(demo.gif): record 8–15s of one task going red → agent loop → green,
     save to docs/demo.gif, then uncomment the line below.
![Luna solving a task](docs/demo.gif)
-->

## What it is

Luna is a coding agent built from scratch: hand it a repo with failing tests and it
locates the broken code, edits it, runs the tests, and iterates until green — the core
loop that tools like Claude Code run, small enough to read end-to-end. What makes it
more than a demo is **measurement**: every task is scored by a harness that independently
re-runs pytest and checks for regressions, so the solve-rate is observed, not claimed.

Two ways in, one engine:

- **CLI** (`cli.py`) — `solve` a benchmark task, `bench` the whole controlled set, or
  `run` the agent on any real git repo with failing tests.
- **Chat** (`serve.py` + `web/`) — a local web app where **Luna**, a cat-eared code
  assistant, takes a repo path in plain language, fixes the red tests, and replies with a
  result card. She'll also just chat back if you say hi.

Both funnel into the same agent loop and the same test-oracle scoring.

## Feature tour

- **Test-oracle scoring** — the model never grades itself; a separate harness re-runs
  pytest against pristine tests and flags regressions.
- **Real-repo mode** — point it at your own git repo; safe by default (clean-tree check,
  fresh branch, never commits or resets your work, prints the diff).
- **Path-confined tools** — every file op is sandboxed to the work directory; the test
  command is the only thing that runs your code.
- **Benchmark + ablations** — a 12-task controlled set with a reproducible scorecard
  (model / retrieval ablations included).
- **Streaming, retrieval, budgets** — live token streaming, optional embedding retrieval
  to seed context, and a per-task USD cost ceiling.
- **Chat frontend** — natural-language path extraction, persona small-talk, a time-aware
  greeting, a polished result card, and a drop-in portrait slot — all on stdlib
  `http.server`, no extra deps.

## Architecture

```mermaid
flowchart TD
    cli["cli.py<br/>solve / bench / run"]
    web["serve.py + web/<br/>Luna chat UI"] --> backend["web_backend.py<br/>parse · route"]
    backend -->|has a repo path| repo
    backend -->|just chatting| chat["chat_reply<br/>(persona, cheap model)"]
    cli --> repo["run_repo / run_bench"]
    repo --> loop
    subgraph agent["agent/"]
      loop["loop.py — ReAct cycle"] <-->|messages + tool_use| llm["llm.py → Claude<br/>(via gateway)"]
      loop -->|tool calls| tools["tools.py: list_dir / read_file / search /<br/>edit_file / write_file / run_tests"]
      tools --> sandbox["sandbox.py<br/>(path-confined workdir)"]
    end
    tools --> pytest["run_tests → pytest"]
    repo --> judge["judge: re-run pytest,<br/>regression check"]
    judge --> out["result card / scorecard.md"]
```

## Quickstart

```bash
# Python 3.9 on macOS/Linux
python3.9 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# secrets: copy the template and fill in your gateway creds
cp .env.example .env
# edit .env → set ANTHROPIC_API_KEY and ANTHROPIC_BASE_URL

# solve a single benchmark task (streams the loop to your terminal)
python cli.py solve 001_mul_precedence

# run the whole benchmark → writes eval/scorecard.md
python cli.py bench

# fix YOUR git repo that has failing tests (new branch, prints the diff)
python cli.py run /path/to/repo
python cli.py run /path/to/repo --python /path/to/repo/.venv/bin/python

# …or chat with Luna in the browser
python serve.py            # → http://127.0.0.1:8000  (Ctrl-C to stop)
```

## Results

<!-- from `python cli.py bench` (label=baseline): 12 controlled tasks, no retrieval / no self-correction -->

| model            | pass@1        | avg steps | avg tokens | avg cost |
|------------------|:-------------:|:---------:|:----------:|:--------:|
| claude-opus-4.8  | 100% (12/12)  |    5.9    |   21,529   |  $0.117  |

Full run: **$1.41** total · **18.6 s/task** avg wall-clock. Every verdict is the harness
independently re-running pytest against the pristine tests — the model never grades itself.
All three conditions below were rerun on **2026-07-27** from the same commit (`4834227`),
with one attempt per task. See the [full per-task scorecard](eval/scorecard.md).

### Ablations

| variant                            | pass@1        | avg steps | avg cost |
|------------------------------------|:-------------:|:---------:|:--------:|
| opus-4.8 (baseline)                | 100% (12/12)  |    5.9    |  $0.117  |
| haiku-4.5 (weaker / cheaper brain) | 100% (12/12)  |    7.2    |  $0.035  |
| opus-4.8 + embedding retrieval     | 100% (12/12)  |    5.5    |  $0.171  |

> On this deliberately simple task set all three variants solve every task (a ceiling
> effect), so the signal is **efficiency, not solve-rate**:
> - **haiku** matches opus at **~3.3× lower cost** (about 1.3 more steps) — the benchmark
>   doesn't punish the weaker model here.
> - **embedding retrieval** cuts steps (5.9 → 5.5; e.g. the division-stub task dropped
>   9 → 4 steps, since retrieval hands the agent the exact broken function) but *raises*
>   cost (~+46%): the injected code is re-sent in every turn's history (MVP doesn't trim),
>   so the step savings don't pay for the token overhead — yet. Trimming history or gating
>   injection would flip that.
>
> Separating variants on solve-rate would need a harder task set (future work). n_attempts=1.

## How it works

- **The loop** (`agent/loop.py`) — a ReAct cycle: the model sees the task, calls tools,
  observes results, iterates. Bounded by `max_steps` and a per-task USD cost budget; it
  stops when the model quits calling tools (or a guardrail trips). Optional live streaming
  and embedding retrieval to seed context.
- **The tools** (`agent/tools.py`) — `list_dir`, `read_file` (numbered lines), `search`
  (literal grep), `edit_file` (unique-match string replace), `write_file`, `run_tests`
  (pytest → compact PASS/FAIL). Every path is confined to the work directory by
  `agent/sandbox.py`; errors come back as strings, never exceptions.
- **The LLM seam** (`agent/llm.py`) — one thin wrapper over the Anthropic SDK (through an
  aggregation gateway), owning retries, streaming, and token/cost accounting. `agent/config.py`
  is the single knob panel (model, budgets, timeouts, price table).
- **The task set** (`tasks/fixture/`) — a compact arithmetic-expression evaluator in three
  stages: `tokenizer` (source → tokens), `parser` (tokens → AST via recursive descent, with
  real operator precedence, left-associativity, and unary minus), and `evaluator` (AST →
  number; true division, divide-by-zero raises), over a shared `errors` hierarchy. Pristine,
  it's fully green: 51 pytest cases. Each `tasks/NNN_*/` applies a `break.patch` that breaks
  exactly one function, turning a known subset of those tests red.
- **Scoring** (`eval/run_bench.py`) — after the agent stops, the harness restores the
  pristine test files (so a run can't cheat by editing tests), then independently re-runs the
  full `pytest`. A task is *solved* iff its target tests pass **and** no previously-green test
  newly fails (regression check).

## Run on a real repo

`python cli.py run <repo>` points the same agent at **any git repo that has failing tests**
and fixes them to green — the fixture task set, generalized to real code (via `eval/run_repo.py`):

- **Oracle = the failing tests.** It runs your suite, takes the currently-failing tests as
  the goal, edits the source, and re-runs. *Solved* = those tests pass **and** no
  previously-green test regresses. It never hunts for bugs without a failing test to prove them.
- **Safe by default.** Requires a clean tree, works on a fresh `luna/fix-<ts>` branch,
  **never commits or resets your work**, and prints the diff for you to keep or discard.
  Refuses non-git dirs, subdirectories,
  and mid-merge/rebase states. Restores any test file the agent touched before judging.
- **Uses your repo's interpreter** (`--python`, or an auto-detected `<repo>/.venv`) so the
  target's own dependencies are visible to pytest.
- **pytest by default** (per-test verdicts + regression detection); other runners work via
  `--test-cmd "…"`, judged by exit code only.

```bash
python cli.py run ~/proj --target tests/test_x.py::test_y     # narrow the goal
python cli.py run ~/proj --test-cmd "make test" --budget 2.0 --max-steps 60
```

## Chat with Luna

```bash
python serve.py            # → http://127.0.0.1:8000
```

Just tell her, in plain language: *"Fix the bug in the repo at /path/to/repo."* She pulls
the path out of the sentence, runs the exact same `run_repo` pipeline as the CLI, and replies
with a result card (baseline → fixed / regressions → branch → cost → diff). No path in your
message? She chats back in character instead of erroring.

The frontend is stdlib `http.server` with no extra deps, split by concern:

- **transport** — `serve.py`: HTTP server, routing, static file serving.
- **logic** — `web_backend.py`: `parse_message` (path extraction), `chat_reply` (persona
  small-talk on a cheap/fast model, with a canned fallback), `run_fix` (→ `run_repo`), and
  `handle_run` that routes between them. Pure dict-in/dict-out, so it's testable offline.
- **presentation** — `web/`: `index.html` / `style.css` / `app.js`, plus a hand-drawn SVG
  catgirl. A time-aware greeting (client-side), a pastel/night theme via `prefers-color-scheme`,
  and a polished result card. Drop any image at `assets/luna.png` (`.jpg`/`.webp` too) to use
  your own portrait — otherwise the built-in SVG is used.

**Local only** — it binds `127.0.0.1` and runs the target repo's tests (arbitrary code), so
point it only at repos you trust.

## Project layout

```text
agent/            the agent itself
  loop.py           ReAct loop (run_agent) + optional retrieval
  tools.py          list_dir / read_file / search / edit_file / write_file / run_tests
  sandbox.py        path confinement + per-task workspaces
  llm.py            Anthropic-via-gateway wrapper + token/cost accounting
  config.py         single knob panel (model, budgets, price table) + cost_of
  profile.py        remembers your name for the CLI greeting
tasks/            fixture/ (pristine evaluator lib + tests) + 001..012/ (task.json + break.patch)
eval/
  run_bench.py      the benchmark: run each task, judge, write scorecard.md
  run_repo.py       real-repo runner (git preflight → agent → restore tests → judge)
tests/            121 unit tests for tools / sandbox / llm / loop / config / profile / run_repo
cli.py            solve / bench / run entrypoints
serve.py          Luna chat UI — HTTP server + routing + static dispatch (thin)
web_backend.py    its logic: parse message → chat_reply / run_fix (no HTTP)
web/              its frontend: index.html + style.css + app.js
assets/           luna.* portrait (optional; falls back to the built-in SVG)
```

## Configuration

Credentials and knobs come from the environment (via `.env`):

| variable             | purpose                                                        |
|----------------------|----------------------------------------------------------------|
| `ANTHROPIC_API_KEY`  | gateway key (**required**)                                     |
| `ANTHROPIC_BASE_URL` | gateway base URL (**required**)                                |
| `LUNA_MODEL`     | override the model id (optional; defaults to opus-4.8)         |
| `LUNA_TEST_CMD`  | default test command for real-repo runs (optional)            |
| `PORT`               | chat server port (optional; default `8000`)                   |

Secrets are read straight from the environment and never enter `Config`, logs, or artifacts.

## Testing

```bash
python -m pytest -q        # 121 tests, all offline (agent runs are monkeypatched)
```

The suite covers the tools, sandbox path-confinement, the LLM wrapper, the loop, config, the
name profile, and the real-repo orchestrator — none of it hits the gateway.

## Limitations & non-goals

- **Needs a failing test as the oracle.** It fixes red tests to green; it does *not*
  proactively hunt for bugs when nothing is failing (no oracle → unverifiable).
- **Structured verdicts are pytest-only.** Other runners work via `--test-cmd` but are judged
  by exit code alone (no per-test detail / regression breakdown).
- Edits are exact string replacements (`edit_file`), not fuzzy / semantic patches.
- Real-repo and chat safety is git-based (clean tree + branch + diff) and localhost-only,
  **not** a container — run only on repos you trust (the test command executes arbitrary code).
- Cost / latency depend on the aggregation gateway; it can't report output tokens under
  streaming, so `run` / `bench` use non-streaming for accurate cost.
- Not bit-reproducible: the LLM samples, so steps / cost vary run to run.
- Embedding retrieval is English-only (`bge-small-en`); its benefit here is modest (see Ablations).

## License

MIT

---

<a id="chinese-version"></a>

# 中文版本

> 一个从零构建、由测试驱动的自主编程 Agent——还带着一张猫耳面孔。
> 给它一个仓库和一组失败的测试，它会定位代码、修改文件、运行测试、读取红绿结果，
> 并持续迭代，直到测试全部通过。每次运行都由独立评测器打分，因此 **pass@1 是实际观测值，
> 而不是模型的自我评价**。你既可以通过 CLI 使用它，也可以在前端与猫娘代码助手 Luna 对话。

![Python](https://img.shields.io/badge/python-3.9-blue)
![测试](https://img.shields.io/badge/tests-121%20passing-brightgreen)
![许可证](https://img.shields.io/badge/license-MIT-lightgrey)

<!-- TODO(demo.gif)：录制一个 8–15 秒的演示，展示单个任务从测试失败到 Agent 迭代、
     再到测试通过的过程，保存为 docs/demo.gif，然后取消下面一行的注释。
![Luna 修复任务](docs/demo.gif)
-->

## 项目简介

Luna 是一个从零构建的编程 Agent：给它一个存在失败测试的仓库，它会定位问题代码、
修改文件、运行测试，并不断迭代直到测试通过。这是 Claude Code 等工具所采用的核心循环，
但本项目规模足够小，可以完整阅读。它与普通演示项目的区别在于**可度量性**：每项任务都由
独立评测器重新运行 pytest 并检查回归，因此解决率来自实际观测，而不是模型声称的结果。

两个入口，共用一个引擎：

- **CLI**（`cli.py`）——可用 `solve` 解决单个基准任务，用 `bench` 运行完整受控任务集，
  或用 `run` 在真实 Git 仓库中运行 Agent。
- **对话界面**（`serve.py` + `web/`）——本地 Web 应用。猫耳代码助手 Luna 可以从自然语言中
  获取仓库路径、修复失败测试，并返回结果卡片；如果只是向她问好，她也可以正常聊天。

两个入口最终都会进入同一套 Agent 循环和测试预言机评分流程。

## 功能概览

- **测试预言机评分**——模型不为自己打分；独立评测器会使用原始测试重新运行 pytest 并检测回归。
- **真实仓库模式**——可以指向自己的 Git 仓库；默认检查工作区是否干净、新建分支、绝不自动提交
  或重置用户改动，并在结束时打印 diff。
- **路径受限工具**——所有文件操作都被限制在工作目录内；只有测试命令会执行目标仓库的代码。
- **基准测试与消融实验**——包含 12 个受控任务和可复现的记分卡，并提供模型与检索消融对照。
- **流式输出、检索与预算**——支持实时 token 流、可选的 embedding 检索，以及单任务美元成本上限。
- **对话前端**——支持自然语言路径提取、角色闲聊、随时间变化的问候、结果卡片和可替换立绘；
  全部基于标准库 `http.server`，无需额外 Web 框架。

## 架构

```mermaid
flowchart TD
    cli["cli.py<br/>solve / bench / run"]
    web["serve.py + web/<br/>Luna 对话界面"] --> backend["web_backend.py<br/>解析 · 分流"]
    backend -->|包含仓库路径| repo
    backend -->|普通聊天| chat["chat_reply<br/>角色设定、低成本模型"]
    cli --> repo["run_repo / run_bench"]
    repo --> loop
    subgraph agent["agent/"]
      loop["loop.py — ReAct 循环"] <-->|消息 + 工具调用| llm["llm.py → Claude<br/>通过聚合网关"]
      loop -->|调用工具| tools["tools.py: list_dir / read_file / search /<br/>edit_file / write_file / run_tests"]
      tools --> sandbox["sandbox.py<br/>工作目录路径限制"]
    end
    tools --> pytest["run_tests → pytest"]
    repo --> judge["独立裁判：重新运行 pytest<br/>并检查回归"]
    judge --> out["结果卡片 / scorecard.md"]
```

## 快速开始

```bash
# macOS/Linux，Python 3.9
python3.9 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 复制密钥模板，并填写聚合网关凭据
cp .env.example .env
# 编辑 .env，设置 ANTHROPIC_API_KEY 和 ANTHROPIC_BASE_URL

# 解决单个基准任务，并在终端中流式显示 Agent 过程
python cli.py solve 001_mul_precedence

# 运行完整基准测试，并写入 eval/scorecard.md
python cli.py bench

# 修复你自己的、存在失败测试的 Git 仓库（新建分支并打印 diff）
python cli.py run /path/to/repo
python cli.py run /path/to/repo --python /path/to/repo/.venv/bin/python

# 或者在浏览器中与 Luna 对话
python serve.py            # → http://127.0.0.1:8000（按 Ctrl-C 停止）
```

## 实验结果

<!-- 来自 `python cli.py bench`（label=baseline）：12 个受控任务，不启用检索和自我纠正 -->

| 模型 | pass@1 | 平均步数 | 平均 token | 平均成本 |
|---|:---:|:---:|:---:|:---:|
| claude-opus-4.8 | 100%（12/12） | 5.9 | 21,529 | $0.117 |

完整运行总成本为 **$1.41**，平均每项任务耗时 **18.6 秒**。每个结果都来自评测器使用
原始测试独立重新运行 pytest；模型从不为自己打分。下面三组条件均于 **2026-07-27**、
同一提交（`4834227`）上重新运行，每项任务运行一次。完整明细见
[逐任务记分卡](eval/scorecard.md)。

### 消融实验

| 实验条件 | pass@1 | 平均步数 | 平均成本 |
|---|:---:|:---:|:---:|
| opus-4.8（baseline） | 100%（12/12） | 5.9 | $0.117 |
| haiku-4.5（能力较弱、成本更低） | 100%（12/12） | 7.2 | $0.035 |
| opus-4.8 + embedding 检索 | 100%（12/12） | 5.5 | $0.171 |

> 在这组刻意保持简单的任务中，三个条件都解决了全部任务，出现了天花板效应；因此有意义的
> 信号是**效率，而不是解决率**：
>
> - **Haiku** 以约低 **3.3 倍的成本**达到与 Opus 相同的解决率，代价是平均多约 1.3 步；
>   这个任务集还不足以拉开弱模型和强模型的解决率差距。
> - **Embedding 检索**将平均步数从 5.9 降到 5.5。例如 division-stub 任务从 9 步降到 4 步，
>   因为检索直接向 Agent 提供了相关函数；但成本上升约 46%。注入的代码会在后续每轮历史中
>   重复发送，节省的步骤不足以抵消 token 开销。未来可以通过裁剪历史或按需启用检索来改善。
>
> 如果要在解决率上区分不同条件，需要更困难的任务集。当前 `n_attempts=1`。

## 工作原理

- **核心循环**（`agent/loop.py`）——ReAct 循环：模型读取任务、调用工具、观察结果并持续迭代。
  `max_steps` 和单任务美元预算会限制运行；模型不再调用工具或触发护栏时停止。支持可选的流式输出
  和 embedding 上下文检索。
- **工具层**（`agent/tools.py`）——提供 `list_dir`、带行号的 `read_file`、字面量 `search`、
  唯一匹配的 `edit_file`、`write_file` 和将 pytest 输出压缩为 PASS/FAIL 的 `run_tests`。
  所有路径都通过 `agent/sandbox.py` 限定在工作目录内；错误始终返回字符串而不是向循环抛异常。
- **LLM 接口层**（`agent/llm.py`）——对 Anthropic SDK 的薄封装，通过聚合网关调用模型，统一负责
  重试、流式输出和 token/成本统计。`agent/config.py` 集中管理模型、预算、超时和价格表。
- **任务集**（`tasks/fixture/`）——一个小型算术表达式求值器，包含 tokenizer（源码到 token）、
  parser（递归下降构建 AST，支持优先级、左结合和一元负号）与 evaluator（AST 到数值，支持真除法
  和除零异常）。纯净版本拥有 51 个全绿 pytest 用例。每个 `tasks/NNN_*/` 都通过 `break.patch`
  精确破坏一个函数，使已知测试子集变红。
- **评分系统**（`eval/run_bench.py`）——Agent 停止后，评测器恢复原始测试，防止通过修改测试作弊，
  然后独立运行完整 pytest。只有目标测试全部通过并且没有原本为绿的测试发生回归时，任务才算解决。

## 在真实仓库上运行

`python cli.py run <repo>` 会让同一个 Agent 面向一个**存在失败测试的 Git 仓库**工作，
将 fixture 任务集中的流程推广到真实代码（实现位于 `eval/run_repo.py`）：

- **失败测试就是预言机。** 工具首先运行测试套件，将当前失败的测试作为目标，修改源码后重新运行。
  “已解决”表示原本失败的测试变绿，并且原本通过的测试没有变红。没有失败测试时，它不会主动寻找
  无法通过测试证明的潜在缺陷。
- **默认安全。** 要求工作区干净，在新的 `luna/fix-<ts>` 分支上工作，绝不自动提交或重置用户改动，
  并打印最终 diff。它会拒绝非 Git 目录、仓库子目录以及正在 merge/rebase 的仓库，并在判定前恢复
  Agent 修改过的测试文件。
- **使用目标仓库的解释器。** 可以通过 `--python` 指定，或自动检测 `<repo>/.venv`，以便 pytest
  能加载目标项目自己的依赖。
- **默认使用 pytest。** pytest 模式提供逐测试判定和回归检测；也可以通过 `--test-cmd "…"`
  使用其他测试命令，但此时只能根据退出码做粗粒度判断。

```bash
python cli.py run ~/proj --target tests/test_x.py::test_y     # 缩小目标范围
python cli.py run ~/proj --test-cmd "make test" --budget 2.0 --max-steps 60
```

## 与 Luna 对话

```bash
python serve.py            # → http://127.0.0.1:8000
```

只需要用自然语言告诉她：*“帮我修一下 bug，仓库路径是 /path/to/repo。”* 她会从句子中提取路径，
调用完全相同的 `run_repo` 流程，并返回结果卡片，包括基线、修复数量、回归、分支、成本和 diff。
如果消息中没有路径，她会以角色设定正常聊天，而不是返回错误。

前端只使用标准库 `http.server`，并按职责拆分：

- **传输层**——`serve.py`：HTTP 服务、路由和静态文件分发。
- **逻辑层**——`web_backend.py`：`parse_message` 提取路径，`chat_reply` 使用低成本模型完成角色闲聊
  并提供静态兜底，`run_fix` 调用 `run_repo`，`handle_run` 负责分流。函数输入输出都是普通字典，
  因此可以脱离 HTTP 离线测试。
- **展示层**——`web/`：`index.html`、`style.css` 和 `app.js`，以及内置的手绘 SVG 猫娘。
  支持客户端时间问候、通过 `prefers-color-scheme` 切换的柔和/夜间主题，以及结果卡片。
  可以将自己的图片放到 `assets/luna.png`（也支持 `.jpg`/`.webp`）；没有图片时使用内置 SVG。

**仅限本地使用**——服务只监听 `127.0.0.1`，但会运行目标仓库的测试，而测试本质上是任意代码；
因此只应将它用于你信任的仓库。

## 项目结构

```text
agent/            Agent 核心实现
  loop.py           ReAct 循环（run_agent）与可选检索
  tools.py          list_dir / read_file / search / edit_file / write_file / run_tests
  sandbox.py        路径限制与逐任务临时工作区
  llm.py            Anthropic 聚合网关封装与 token/成本统计
  config.py         模型、预算、价格表和 cost_of 的集中配置
  profile.py        记录用户名，用于 CLI 问候
tasks/            fixture/（纯净求值器与测试）+ 001..012/（task.json + break.patch）
eval/
  run_bench.py      运行任务、独立判定并生成 scorecard.md
  run_repo.py       真实仓库流程：Git 预检 → Agent → 恢复测试 → 独立判定
tests/            工具、沙箱、LLM、循环、配置、profile 和 run_repo 的 121 个单元测试
cli.py            solve / bench / run 命令入口
serve.py          Luna 对话界面：HTTP 服务、路由与静态分发
web_backend.py    解析消息并分流到 chat_reply / run_fix 的业务逻辑
web/              index.html + style.css + app.js
assets/           可选的 luna.* 立绘；不存在时使用内置 SVG
```

## 配置

凭据和运行参数通过环境变量（`.env`）提供：

| 环境变量 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 聚合网关密钥（**必填**） |
| `ANTHROPIC_BASE_URL` | 聚合网关地址（**必填**） |
| `LUNA_MODEL` | 覆盖模型 ID（可选，默认 opus-4.8） |
| `LUNA_TEST_CMD` | 真实仓库模式的默认测试命令（可选） |
| `PORT` | 对话服务端口（可选，默认 `8000`） |

密钥直接从环境变量读取，绝不会进入 `Config`、日志或实验产物。

## 测试

```bash
python -m pytest -q        # 121 个测试，全部离线运行（Agent 调用使用 monkeypatch 替换）
```

测试覆盖工具、路径限制、LLM 封装、Agent 循环、配置、用户名 profile 和真实仓库编排流程，
不会访问模型网关。

## 限制与非目标

- **需要失败测试作为预言机。** 它负责将红测试修绿；当所有测试都通过时，不会主动搜索缺乏验证标准的 bug。
- **只有 pytest 支持结构化判定。** 其他测试命令可以通过 `--test-cmd` 使用，但只能根据退出码判断，
  无法提供逐测试明细或回归列表。
- 编辑操作使用精确字符串替换，不支持模糊匹配或语义补丁。
- 真实仓库与对话模式的安全边界是 Git 干净树、新分支、diff 和本地监听，**不是容器**；
  测试命令可以执行任意代码，因此只能用于可信仓库。
- 成本和延迟取决于聚合网关。该网关在流式模式下不返回 output token，因此 `run` 和 `bench`
  默认使用非流式请求，以获得准确成本。
- LLM 存在采样随机性，因此运行结果无法做到逐 bit 复现，步数和成本可能发生变化。
- Embedding 检索只针对英文语料（`bge-small-en`），并且在当前任务集上的收益有限，详见消融实验。

## 许可证

MIT
