# 研究与工程评测

评测记录区分工程正确性、真实模型执行和真人研究效果，不把其中任何一项替代其他项。

`tests/v1/test_acceptance.py` 包含六类 60 项工程反例：数值、会计口径、范围、执行、报告、审核。每类 09/10 为最后运行的 12 项留出工程检查；其余 48 项用于实现调试。额外回归覆盖真实验收中发现的字体注册、范围缓存、复核恢复、预算收尾、图表预测角色等问题。

`benchmarks/research-cases.json` 是六类 60 个研究问题：单材料、财报变化、同业比较、公司尽调、产业关系、历史时点，每类 10 个，48 个开发、12 个留出。PDD 案例读取固定摘要的真实官方披露，其余明确标注为合成材料。图像 PDF 为实际无文本层测试材料。历史案例中的时间线用于判断方法评测，服务端时点边界另由工程测试验证。

```sh
uv run python scripts/evaluate_research.py --root tmp/eval-development-new --provider codex --split development
uv run python scripts/evaluate_research.py --root tmp/eval-holdout-new --provider claude --split holdout
# 可只选择一个案例
uv run python scripts/evaluate_research.py --root tmp/eval-one-new --provider codex --case single_material-01
```

每次使用新目录，保留原件、报告、检查、Trace 和实际时间/工具消耗，输出 `evaluation-result.json`。此命令会使用模型额度。语料中 `not_run` 表示尚未完成该研究效果评测，不能以工程通过数覆盖它。最终真实 PDD 与运行边界的本次结果另见验收文档。

## 预算校准

初始预算明确标为暂定，保留 10% 收尾额度。每一深度档位至少积累 20 份完成研究且检查通过、可交付的报告，再按 `ceil(P90 × 1.5 / 0.9)` 计算时间和工具额度。输入深度采用该 run 固定的准确输入版本。

`POST /api/v1/budgets/calibrate` 传 `operation_id`、`depth` 和 `apply=false` 查看建议；`apply=true` 显式应用新预算。样本不足返回 `insufficient_samples`，不声称已校准。当前项目示例数量不足以完成统计校准。

## 真人盲评

维护页进入“研究效果评测”，选择报告并下载随机编号的盲评材料包。两名评阅者分别记录重大错误、实际核对/编辑时间、无需修改/轻度编辑/大幅修改/不可用，以及分歧意见。保留各次记录，以同一评阅者的最新记录统计。

“80% 报告轻度编辑可用”只在两人均无重大错误、均认为无需修改或轻度编辑时计为该报告达标。界面记录是所有者输入的人工标签，系统仍要求真人确认样本与分歧，不会将模型检查标为完成真人验证。本次交付不声称已完成两名真人盲评或达到该研究效果目标。
