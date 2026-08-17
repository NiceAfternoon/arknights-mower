# AI 协作入口

修改日志、截图通知、WebUI 日志消费、视觉/识别/匹配或设备链路前，必须先完整阅读 `doc/logging-constraints.md`。

修改全自动专精相关代码或日志时，还必须完整阅读 `doc/mastery-constraints.md`；业务状态与动作以该文档为准，日志优化不得改变业务行为。

`.scratch/log-baseline/` 保存 #48 的 owner-approved 原始报告和冻结 ledger。不得修改、删除或提交其中任何文件。上游新增日志作为 ledger 之后的增量审计，不得回写冻结 ledger。
