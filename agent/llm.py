"""LLM 封装：与 Claude 对话的接口。

把「经网关调用 Claude」收拢成一层薄封装，给上层的 loop.py 一个稳定的单轮接口。

三个功能：接线（用环境变量里的凭据初始化 anthropic.Anthropic()）、发一轮请求（返回
SDK 原生 Message，不解释 stop_reason、不执行工具、不跑多轮）、记账（累加各轮 usage 的tokens，按价格表折算成本）。
"""

from __future__ import annotations

import logging
from typing import Callable, NamedTuple, Optional

import anthropic
import os

# cost_of 是唯一的计价函数，owner 在 config.py；llm 和 loop 都复用它，
# 免得价格表逻辑在几个地方各写一份。
from agent.config import Config, cost_of

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据表示：Usage 记账快照
# ---------------------------------------------------------------------------
class Usage(NamedTuple):
    """一次记账快照（累计量），由 LLMClient.snapshot() 返回。

    cost_usd 是按价格表折出来的估算值，只用来横向比较和做预算护栏，网关真实计费可能不
    一样； token 计数真实（以 response.usage 为准）。模型不在价格表里时 cost_usd
    是 None 而不是 0。
    """

    input_tokens: int            # 累计 prompt tokens（以各轮 response.usage 为准）
    output_tokens: int           # 累计 completion tokens
    calls: int                   # 累计成功返回的请求次数
    cost_usd: Optional[float]    # 估算成本；模型不在价格表时为 None


# ---------------------------------------------------------------------------
# LLMClient
# ---------------------------------------------------------------------------
class LLMClient:
    """经网关调用 Claude 的薄封装 + Usage 记账器。

    典型用法（loop.py 侧）::

        client = LLMClient(config)                 # 默认 config.model（opus）
        msg = client.create(messages=msgs, system=sys, tools=TOOLS)
        # ... 读 msg.content / msg.stop_reason / msg.usage ...
        snap = client.snapshot()                   # 拿累计 token 与成本

    消融对照切模型：``LLMClient(config, config.model_haiku)``——记账按 haiku 价格。
    """

    def __init__(self, config: Config, model: Optional[str] = None) -> None:
        """构造并接线。

        建 anthropic.Anthropic 不传入 api_key / base_url——让 SDK 自己从环境变量读。

        传 model 可覆盖 config.model（比如传 config.model_haiku 切消融模型）。缺 API key
        时快速失败、给清楚的报错；model 不在价格表是允许的，只是之后 cost_usd
        记 None 并 warn 一次。
        """
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "缺少 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL，"
                "请先 cp .env.example .env 并填值"
            )
        self._config = config
        self._model = model or config.model
        self._client = anthropic.Anthropic(
            timeout=config.timeout_s,
            max_retries=config.max_retries,
        )
        self._input_tokens = 0
        self._output_tokens = 0
        self._calls = 0
        self._warned_missing_price = False

    def create(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        tool_choice: dict | None = None,
        stream: bool | None = None,
        on_text: "Callable[[str], None] | None" = None,
    ) -> "anthropic.types.Message":
        """发一轮请求，返回 SDK 原生 Message。
        """
        params = {
            "model": self._model,
            "max_tokens": self._config.max_tokens,
            "messages": messages,
        }
        if system is not None:
            params["system"] = system
        if tools is not None:
            params["tools"] = tools
        if tool_choice is not None:
            params["tool_choice"] = tool_choice

        use_stream = self._config.stream if stream is None else stream
        if use_stream:
            with self._client.messages.stream(**params) as s:
                if on_text is not None:
                    for delta in s.text_stream:  # 流式输出
                        on_text(delta)
                msg = s.get_final_message()
        else:
            msg = self._client.messages.create(**params)

        self._calls += 1
        usage = getattr(msg, "usage", None)
        if usage is None:
            logger.warning("响应缺少 usage，跳过 token 累加")
        else:
            self._input_tokens += usage.input_tokens
            self._output_tokens += usage.output_tokens
        return msg

    def snapshot(self) -> Usage:
        """返回当前累计的记账快照。
        """
        cost = cost_of(self._input_tokens, self._output_tokens, self._config, self._model)
        if cost is None and not self._warned_missing_price:
            logger.warning("模型 %s 不在价格表，cost_usd 记为 None", self._model)
            self._warned_missing_price = True
        return Usage(self._input_tokens, self._output_tokens, self._calls, cost)

    def reset(self) -> None:
        """把记账累加器清零（tokens 与 calls 归零）。
        bench 每个任务开跑前调用。
        """
        self._input_tokens = 0
        self._output_tokens = 0
        self._calls = 0

    @property
    def model(self) -> str:
        """当前生效的模型 id 。
        """
        return self._model
