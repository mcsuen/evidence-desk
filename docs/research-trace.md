# 研究执行可视化与 Trace 工作台

研究详情提供「研究 / 执行流程 / Trace」。Agent 与受控业务服务负责研究，图形展示已发生的执行事件。

## 使用

- 运行中打开研究，默认查看执行流程；已经结束的研究默认报告。明确选过的页签和节点在同一浏览器窗口刷新后保留。
- 阶段定位栏跳到资料准备、某次 Agent 尝试、核验、修复或交付。展开尝试可查看独立调用；图可以平移和缩放。
- Trace 列表显示层级与耗时条；可筛选工具、错误及尝试。用「定位最慢工具」「定位问题」直接打开右侧输入、输出或核验原因。
- 选择较早的执行节点会暂停跟随；「返回最新」恢复。事件滑块只回放，不执行工具。窄屏优先使用列表，检查内容在抽屉中打开。
- 工具和阶段耗时不能相加成总耗时；整轮 token 包含缓存输入，缓存值不另加。未取得费用时保持未知。
- 当前研究记录可观察事件。没有逐工具开始时间时显示缺失，不用邻近日志伪造精确时间。

## 本机记录和接口

`src/pitr/desk/research/trace` 包含契约、追加事件账本、投影、调用记录读取、CLI 增量读取、OTLP 接收与 LangSmith 导出。业务任务及预算以 tasks 中的记录为准。

SQLite 保存 `trace_events / trace_spans / trace_content / trace_cursors / trace_meta / trace_outbox`。内容采用 SHA-256 引用，事件身份去重；逐事件投影允许历史查看。CLI 事件通过控制调用 ID 关联，不重复增加工具计数。

位于 `/api/desk/research/requests/{id}`：

| 接口 | 用途 |
|---|---|
| `GET /trace?at_seq=…` | 当前或历史投影 |
| `GET /trace/events` | SSE；支持 Last-Event-ID 与 after_seq |
| `GET /trace/spans/{span_id}?at_seq=…` | 节点输入输出及原始事件，按需加载 |
| `GET /trace/export` | 有版本、哈希清单及脱敏说明的 ZIP；不含原始 PDF |
| `POST /trace/sync` | 按本机策略预览或加入同步队列 |

`/api/desk/research/trace-settings` 读取或保存同步设置。密钥仅在 `private/trace-settings.json` 中保存，权限 0600，公开接口只返回是否配置。

## OTel 和 LangSmith

OTel 仅对 [`telemetry-profile.json`](../src/pitr/desk/research/trace/telemetry-profile.json) 中精确匹配的 CLI 版本启用，并按事件允许表解析。不匹配的版本不启用该通道；缺失遥测保持未知。配置从隔离的 CODEX_HOME 加载，不读取个人 Codex 配置。接收端是当前执行的 loopback broker，使用随机 capability，提示原文遥测关闭。

CLI 输出之外的内部模型上下文与推理不可见。不认识的事件留存原始记录并标记解析缺口。

LangSmith 默认关闭。仅元数据模式使用字段白名单，不发送公司、问题、工具参数、原文或自由文本错误。内容模式必须预览精确发送包；有事件变化须重新预览。所有模式都移除凭据和认证头，不上传 PDF 原件。

SDK 从本机记录显式建立嵌套运行；稳定 UUID、父节点先发送、持久发件箱和重试保证恢复。关闭同步不初始化 SDK 客户端，外部服务故障不影响研究。历史记录缺少开始时间时，外部接口所需的时间占位明确带 `timestamp_placeholder`，不能拿其外部零时长替代本机缺失值。

## 保存与恢复

本机桥接采集调用、工具、核验和取消事件，Trace 按事件序列提供执行回放。回放只读取记录，不重新运行研究。

停止写入后成套保存数据库、冻结对象和外部 Agent 运行目录。在新目录恢复并校验备份，缺失事件或时间戳仍显示为未知。具体数据范围见 [架构说明](architecture.md#7-备份与恢复)。
