"""luna 的评测 harness，负责判卷和记分。

对每道题准备一份干净的隔离副本、打上 break.patch，跑一遍 agent 主循环，
然后自己独立复跑 pytest 来判断是否 solved：目标测试全绿且没有回归才算过。
跑完后将结果汇总成 scorecard.md 和 results/<label>.json。

入口是 eval.run_bench。
"""
