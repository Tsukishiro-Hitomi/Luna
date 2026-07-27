"""agent：

config：参数配置和计价，
llm：封装对 Anthropic 网关的调用与用量记账，
tools：工具集和护栏分发，
sandbox：负责路径封闭和工作区，
loop：ReAct 主循环。

任务成败由评测 harness 决定，用受保护的原版测试独立复跑 pytest。
"""
