"""配置面板：一个 ``Config`` 数据类，以及价格表和计价函数 ``cost_of``。

旋钮都存在一个 ``Config`` 实例里，别处统一用 ``config.model`` 等属性访问。
计价的价格表和函数只有这一份，llm 和 loop 都复用 ``cost_of``。
密钥（``ANTHROPIC_API_KEY`` / ``ANTHROPIC_BASE_URL``）不进 Config，由 anthropic SDK
自己从环境读，以免被泄漏。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
import os

@dataclass
class Config:
    """承载全部运行旋钮的单一配置对象。

    字段按照用途分为：模型、预算护栏、能力开关、工具截断预算、价格表等。
    做消融对照时不新增字段，只换 ``model`` 或更改 ``enable_retrieval`` / ``self_correction``，
    由 bench 构造不同 ``Config`` 进行测试。
    """

    # 模型
    model: str = "anthropic/claude-opus-4.8"          # 正式跑
    model_haiku: str = "anthropic/claude-haiku-4.5"   # 仅作消融对照
    max_tokens: int = 8192                            # 单次响应输出上限（write_file 重写整文件时需余量）
    stream: bool = True                               # 流式
    timeout_s: float = 120.0                          # 单次 HTTP 请求超时（秒）
    max_retries: int = 2                              # 交给 SDK 自动重试（SDK 默认即 2）

    # 护栏 / 预算 
    max_steps: int = 30                               # 单任务最多迭代轮数
    cost_budget_usd: float = 0.50                     # 单任务成本预算（美元）
    run_tests_timeout_s: int = 60                     # run_tests 子进程超时（传给工具层）
    judge_timeout_s: int = 60                         # harness 复判 pytest 超时（eval 用）

    # 能力开关
    enable_retrieval: bool = False                    # embedding 代码检索；False 时仅靠 search 工具
    self_correction: bool = False                     # 为 True 时 system prompt 追加反思段

    # 工具截断预算
    max_tool_result_chars: int = 8000
    max_read_lines: int = 400
    max_search_hits: int = 100
    max_test_output: int = 4000

    test_cmd: Optional[str] = None      
    test_python: Optional[str] = None   

    # 成本核算：模型 id -> (输入价, 输出价)，美元/百万 token
    # 默认取第一方参考价（Opus 4.8 = $5/$25、Haiku 4.5 = $1/$5 每百万 token），
    # 走聚合网关时按实际计费校准。未知模型缺表时 cost_of 返回 None。
    price_per_mtok: Dict[str, Tuple[float, float]] = field(
        default_factory=lambda: {
            "anthropic/claude-opus-4.8": (5.0, 25.0),
            "anthropic/claude-haiku-4.5": (1.0, 5.0),
        }
    )

    @classmethod
    def from_env(cls) -> "Config":
        """在默认值之上叠加 ``.env`` 里的非密钥旋钮，返回新的 ``Config``。

        由 ``cli.py`` 在 ``load_dotenv()`` 之后调用。目前只吸收 ``LUNA_MODEL`` /
        ``MAX_STEPS`` / ``RUN_TESTS_TIMEOUT`` / ``LUNA_TEST_CMD`` ，其他
        保持字段默认。密钥（``ANTHROPIC_API_KEY`` / ``ANTHROPIC_BASE_URL``）绝不会被存进来，
        由 SDK 直接读环境。
        """
        overrides = {}
        model = os.environ.get("LUNA_MODEL")
        if model is not None:
            overrides["model"] = model
        max_steps = os.environ.get("MAX_STEPS")
        if max_steps is not None:
            overrides["max_steps"] = int(max_steps)
        timeout = os.environ.get("RUN_TESTS_TIMEOUT")
        if timeout is not None:
            overrides["run_tests_timeout_s"] = int(timeout)
        test_cmd = os.environ.get("LUNA_TEST_CMD")
        if test_cmd is not None:
            overrides["test_cmd"] = test_cmd
        return cls(**overrides)


def cost_of(
    in_tokens: int,
    out_tokens: int,
    config: "Config",
    model: Optional[str] = None,
) -> Optional[float]:
    """按价格表把 token 用量折算成美元。
    """
    if model is None:
        model = config.model
    if model not in config.price_per_mtok:
        return None
    pin, pout = config.price_per_mtok.get(model)
    return (float)(in_tokens * pin + out_tokens * pout) / 1000000
