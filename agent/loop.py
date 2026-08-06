"""Agent 核心循环。

给定一个已被 break.patch 改红的任务工作目录和一段任务描述，run_agent 驱动模型
反复「观察 → 决策 → 调工具 → 读结果」，直到模型收尾或触护栏，返回 AgentResult。
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import List, Optional

from agent.config import Config, cost_of
from agent.llm import LLMClient
from agent.tools import TOOLS, guarded_execute

_RETRIEVAL_ENCODER = None  


# ---------------------------------------------------------------------------
# 结果对象
# ---------------------------------------------------------------------------
@dataclass
class ToolCall:
    """一次工具调用的轨迹记录（供记分卡 / 调试用）。"""

    name: str
    input: dict
    result_preview: str          # guarded_execute 返回值的截断预览


@dataclass
class StepRecord:
    """单轮（一次模型调用 + 其触发的工具执行）的记录。"""

    index: int
    assistant_text: str          # 本轮所有 text 块拼接（模型的说明 / 思考）
    tool_calls: List[ToolCall]   # 本轮触发的工具调用（可多个——并行工具）
    stop_reason: str             # 本轮 response.stop_reason
    input_tokens: int
    output_tokens: int
    cost_usd: float


@dataclass
class AgentResult:
    """一次 run_agent 的完整结果。
    """

    stop_reason: str
    steps: List[StepRecord] = field(default_factory=list)
    num_steps: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    final_text: str = ""         # 模型最后一轮文字（收尾总结），仅供人看
    error: Optional[str] = None  # stop_reason == "error" 时的简述


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------
def build_system_prompt(config: Config) -> str:
    """构造逐字稳定的 system prompt。

    不含任务 / 时间 / 随机内容，方便 prompt caching 命中；具体任务和检索片段都放
    首条 user 消息，不进 system。

    config.self_correction 为真时在正文末尾追加一段反思要求（读到失败先诊断根因再改）。
    """
    base = (
        "你是一个在受限工作目录内修复代码的自主 agent。你只能通过提供的工具"
        "（list_dir / read_file / search / edit_file / write_file / apply_patch / run_tests）操作，"
        "所有路径都限定在任务工作目录内。\n\n"
        "工作循环：定位相关代码 → 做最小改动 → 立刻用 run_tests 跑测试 → 读红/绿 → "
        "按结果迭代。每次改完都必须重新跑测试，以真实 run_tests 输出为准。\n\n"
        "纪律：\n"
        "- 只做让测试通过所需的最小改动，不顺手重构无关代码。\n"
        "- edit_file 的 old_string 必须与文件内容精确、唯一匹配；多处修改优先用 apply_patch。\n"
        "- apply_patch 必须是标准 unified diff，不能修改测试文件，也不能重命名/复制文件。\n"
        "- 反作弊：绝不修改测试文件、绝不删断言、绝不用 raise/skip 绕过测试。\n"
        "- 所有测试通过时，用一句话总结修改然后停止，不要再调用任何工具。\n"
        "- 保持简洁。"
    )
    if config.self_correction:
        base += (
            "\n\n反思：run_tests 报失败时，先读报错、诊断根因，再动手改；"
            "别在没弄清原因前反复试探性修改。"
        )
    return base

# ---------------------------------------------------------------------------
# 主循环
# ---------------------------------------------------------------------------
def run_agent(workdir: str, task: str, config: Optional[Config] = None, on_text=None) -> AgentResult:
    """驱动 agent 循环，返回 AgentResult。
    """
    config = config or Config()
    result = AgentResult(stop_reason="")
    client = LLMClient(config)                  # ← 测试里被 monkeypatch 成假 LLM
    system = build_system_prompt(config)

    user_text = task
    if config.enable_retrieval:                 # MVP 默认 False，不走检索
        user_text = retrieve_context(task, workdir, config) + "\n\n" + task
    messages = [{"role": "user", "content": user_text}]

    for i in range(config.max_steps):
        # 调用模型前先查预算
        if result.total_cost_usd >= config.cost_budget_usd:
            result.stop_reason = "budget_exceeded"
            result.num_steps = i
            return result

        # 调用模型
        try:
            resp = client.create(messages=messages, system=system, tools=TOOLS, on_text=on_text)
        except Exception as e:
            result.stop_reason = "error"
            result.error = str(e)
            result.num_steps = i
            return result

        # 记账
        _accumulate_usage(result, resp, config)

        # 保留完整 content 作为 assistant 消息
        messages.append({"role": "assistant", "content": resp.content})

        # 拆解 text / tool_use，计算算本步 token/成本
        assistant_text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        usage = getattr(resp, "usage", None)
        s_in = getattr(usage, "input_tokens", 0) if usage else 0
        s_out = getattr(usage, "output_tokens", 0) if usage else 0
        s_cost = step_cost(usage, config) if usage else 0.0

        # 如果无 tool_use ，收尾
        if not tool_uses:
            result.steps.append(StepRecord(
                index=i, assistant_text=assistant_text, tool_calls=[],
                stop_reason=resp.stop_reason,
                input_tokens=s_in, output_tokens=s_out, cost_usd=s_cost,
            ))
            result.final_text = assistant_text
            result.stop_reason = "model_stop"
            result.num_steps = i + 1
            return result

        # 否则，逐个执行工具，结果合并进【一条】user 消息
        tool_calls, tool_results = [], []
        for tu in tool_uses:
            out = guarded_execute(
                tu.name, tu.input, workdir,
                test_timeout=config.run_tests_timeout_s,
                max_result_chars=config.max_tool_result_chars,
                test_cmd=config.test_cmd, test_python=config.test_python,
            )
            tool_calls.append(ToolCall(name=tu.name, input=tu.input, result_preview=out[:200]))
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,       # 必须与对应 tool_use 的 id 匹配
                "content": out,
            })
        result.steps.append(StepRecord(
            index=i, assistant_text=assistant_text, tool_calls=tool_calls,
            stop_reason=resp.stop_reason,
            input_tokens=s_in, output_tokens=s_out, cost_usd=s_cost,
        ))
        messages.append({"role": "user", "content": tool_results})

    # 循环结束，说明已经达到 max_steps
    result.stop_reason = "max_steps"
    result.num_steps = config.max_steps
    return result 


# ---------------------------------------------------------------------------
# 辅助函数：usage 记账 / 成本折算 / 检索挂载点
# ---------------------------------------------------------------------------
def _accumulate_usage(result: AgentResult, resp: "object", config: Config) -> None:
    """把一轮响应的 usage 累加进 result 。
    """
    usage = getattr(resp, "usage", None)
    if usage is None:
        return                                  # 缺 usage → 跳过、不崩
    in_tok = getattr(usage, "input_tokens", None)
    out_tok = getattr(usage, "output_tokens", None)
    if in_tok is None or out_tok is None:
        return
    result.total_input_tokens += in_tok
    result.total_output_tokens += out_tok
    result.total_cost_usd += step_cost(usage, config)


def step_cost(usage: "object", config: Config) -> float:
    """单步成本。
    """
    cost = cost_of(usage.input_tokens, usage.output_tokens, config)
    return cost if cost is not None else 0.0


def retrieve_context(task: str, workdir: str, config: Config) -> str:
    """检索挂载点：开局给首条 user 消息预注入相关代码片段。

    config.enable_retrieval=True 时：用 sentence-transformers + bge-small-en-v1.5 选出相关片段返回。
    消融只更改 enable_retrieval 一个字段。
    """
    # 先跑一次 pytest 拿失败信号。
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=line", "-p", "no:cacheprovider"],
            cwd=workdir, capture_output=True, text=True, env=env, timeout=60,
        )
        signal = "\n".join(
            ln for ln in (proc.stdout or "").splitlines()
            if "FAILED" in ln or "Error" in ln or "assert" in ln.lower()
        )[:1200]
    except Exception:
        signal = ""

    # 索引库代码
    chunks = []  # (name, start_line, text)
    for name in sorted(os.listdir(workdir)):
        if not name.endswith(".py"):
            continue
        try:
            with open(os.path.join(workdir, name), encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for i in range(0, len(lines), 30):
            block = "\n".join(lines[i:i + 30])
            if block.strip():
                chunks.append((name, i + 1, block))
    if not chunks:
        return ""

    # 导入 torch/st 并嵌入检索（
    try:
        from sentence_transformers import SentenceTransformer, util
        global _RETRIEVAL_ENCODER
        if _RETRIEVAL_ENCODER is None:
            _RETRIEVAL_ENCODER = SentenceTransformer("BAAI/bge-small-en-v1.5")
        enc = _RETRIEVAL_ENCODER
        query = f"Represent this sentence for searching relevant passages: {task}\n{signal}"
        q_emb = enc.encode(query, convert_to_tensor=True, normalize_embeddings=True)
        p_emb = enc.encode([c[2] for c in chunks], convert_to_tensor=True, normalize_embeddings=True)
        hits = util.semantic_search(q_emb, p_emb, top_k=min(4, len(chunks)))[0]
    except Exception as e:
        print(f"[retrieve_context] 检索失败，降级为不注入：{e}", file=sys.stderr)
        return ""

    # 拼成可前置进首条 user 消息的文本
    out = ["【检索】以下库代码片段可能与失败相关（供参考，未必完整）："]
    for h in hits:
        name, start, text = chunks[h["corpus_id"]]
        out.append(f"\n# {name}:{start}\n{text}")
    return "\n".join(out)
