# Slack 通用接入

Slack 支持本人私信、指定频道 @提及、`/research`、附件研究、线程内进度和结果回传，以及 Wiki 审核。研究与 Wiki 命令使用和网页相同的服务。

## 首次配置

1. 执行 `./start`，在打开的页面中进入“本机设置”。
2. 登录自己的 Slack 工作区，或在 [Slack 注册页](https://slack.com/get-started#/createnew)创建工作区。
3. 在 [Slack 应用管理](https://api.slack.com/apps)选择 **Create New App → From a manifest**，导入设置页下载的应用配置文件，选择自己的工作区。
4. 在 **Basic Information → App-Level Tokens** 生成带 `connections:write` 权限的 App Token；确认 **Socket Mode** 已启用。
5. 在 **OAuth & Permissions** 安装应用，取得 Bot Token。修改 manifest 权限后需重新安装应用。
6. 在本机设置填写 App Token（`xapp-`）、Bot Token（`xoxb-`）、工作区 ID 和本人用户 ID。工作区 ID 可从打开工作区后的 `app.slack.com/client/T…` 地址取得；本人 ID 在个人资料“更多”菜单中复制。Token 只填本机设置页，不发到聊天。
7. 建立专用测试频道，将机器人加入频道，从频道详情复制频道 ID，加入白名单。白名单为空时仅允许本人私信。
8. 点击“保存 Slack 配置”“检查配置”“连接 Slack”“发送测试消息”，到 Slack 查看受理消息及帮助回复。

连接会保存启用状态；本机服务重启后恢复连接，主动断开后保持关闭。首次网络连接失败会退避重试；凭据、工作区或权限错误需修正配置。电脑休眠或服务停止期间无法处理请求。

## 使用方式

私信可直接输入以下命令；频道中在命令前 @机器人，或使用 `/research` 后跟相同的命令。频道普通聊天不触发任务，线程追问仍需 @机器人。

| 命令 | 作用 |
|---|---|
| `help` / `帮助` | 查看用法 |
| `研究 PDD 调查利润率变化的解释与反证` | 提出研究问题并进入输入理解 |
| `进度` / `status [任务 ID]` | 查询近期或指定任务 |
| `来源 source_id` | 获取来源地址与提取的原文文本 |
| `报告 task_id` | 获取完整结果文件 |
| `Wiki 关键词` | 查询已发布页面 |
| `审核` | 获取完整变更文件和审核按钮 |

消息请求在原消息线程回复，已有线程里的请求沿用线程。斜杠命令先创建受理消息，后续结果归入该消息线程。结果文件支持文本及二进制内容。

文件通过私信或带 @提及的频道消息发送。每条最多 10 个、每个最多 40 MB，仅下载应用有权读取的 Slack 托管文件。外链文件、过大、失效或无法访问的文件明确报错。附件保留文件名、类型、大小、SHA-256、Slack 文件标识及事件关联。

研究消息中的可解析附件保存为研究来源，与问题一起进入输入理解；下载失败或无法解析的附件会明确报错。同一研究线程的补充可带入新材料。需要只收录到 Wiki 时，使用“收录”或“保存到 Wiki”，或在澄清表单中选择处理方式。

## 添加工作流

`src/pitr/integrations/slack/` 只依赖通用协议、Slack SDK、HTTP 客户端和 SQLite。`src/pitr/desk/slack_adapter.py` 负责业务命令路由；`src/pitr/desk/slack.py` 负责装配。

适配器提供唯一 `name`、命令前缀 `commands`、后台请求处理 `handle(event, context)`、快速只读表单生成 `open_modal(event, context)`、表单校验 `validate_submission(event)`，以及任务更新 `poll(context)`。

```python
from pitr.integrations.slack import WorkflowUpdate, OutputFile

class ExampleAdapter:
    name = 'example'
    commands = ('example',)

    def handle(self, event, context):
        contents = [context.attachment_bytes(ref.id)
                    for ref in event.attachments if ref.status == 'ready']
        context.publish(event.id + ':result', WorkflowUpdate(
            text=f'收到 {len(contents)} 个文件',
            files=[OutputFile(filename='result.txt', content=event.text)],
        ))

    def validate_submission(self, event):
        return {}

    def open_modal(self, event, context):
        raise ValueError('此工作流没有交互表单')

    def poll(self, context):
        pass

app.state.slack.register(ExampleAdapter())
```

长任务使用 `context.prepare(factory)` 固定业务请求，以 `event.id` 调用业务自己的幂等入队接口，再 `context.bind(task_id)`。入队后、记录关联前中断，重放仍使用同一请求。后台通过 `context.bindings()` 取得 `event_id`，调用 `context.publish(key, update, event_id=...)`，每个状态使用稳定 key，不将 Slack 频道塞进业务参数。

按钮通过 `context.action(action_id, metadata)` 获取本机保存的上下文标识，作为 `action_id='pitr_action'` 按钮的 value。表单的 `private_metadata` 也由传输层生成和校验。审核版本、是否允许采纳仍由业务服务验证；开窗函数只读取本机状态，不发起长任务或修改业务。

二进制输出使用 `OutputFile.from_bytes(data, filename='model.xlsx')`。适配器获得统一协议和受当前事件约束的附件读取接口，不获得 SDK 客户端、Token、短期触发标识或任意本机文件路径。

## 本机 API

接口均位于 `/api/desk`，使用本机访问与写入来源检查。

| 方法与路径 | 用途 |
|---|---|
| `GET /slack` | 实际连接、队列计数、最近收发和连接检查记录 |
| `GET /slack-manifest` | 下载统一应用配置 |
| `POST /settings` | 保存凭据、频道白名单 `slack_channel_ids` 和启用状态 `slack_enabled` |
| `POST /slack/check` | 检查配置、Bot 工作区和可获知的权限 |
| `POST /slack/connect`、`POST /slack/disconnect` | 启用连接或主动断开 |
| `POST /slack/test` | 发送到本人私信；可传 `channel_id` 指定白名单频道 |
| `GET /slack/deliveries` | 最近 100 条消息及文件投递记录 |
| `POST /slack/deliveries/{id}/retry` | 人工重发失败或结果不确定的单项投递 |
| `GET /slack/attachments`、`GET /slack/attachments/{id}/file` | 附件记录及本机下载 |
| `POST /slack/live-checks` | 本人登记通过项目 `check` 和实际操作证据 `evidence` |

配置变更会断开连接并重置诊断和检查标记；连接检查记录保留在本机审计中。重新连接后按新配置校验待处理事件和发送目标。

## 恢复与去重

- 入站事务提交后才确认接收；入口数据库锁等待上限 250 ms。下载、业务执行及投递都在后台。入库失败不确认，等待 Slack 重投。
- 队列领取和续租支持恢复。业务操作须使用稳定操作标识；传输层不替第三方工作流承诺业务幂等。
- 同一更新的消息、文件在同一事务中分别入队。某项失败不会重发已发送的其他项。网络结果未知或发送中崩溃保留“待核对”，由本人查看 Slack 后选择是否重发。
- 明确限流时遵守 `Retry-After`，可安全重试的错误退避处理。原始 SDK 请求、Token、WebSocket ticket 和临时回复 URL 不写入日志或队列。
- 开窗触发标识短期有效且不持久化。过期或中断后提示重新点击；开窗重放不会执行审批。
- 同一 OS 账号下，每个工作区与 Bot 安装只允许一个网络连接进程。服务重启时如果旧连接仍在退出，新进程等待并退避重试；不会开启第二个并行消费者。手动连接也共享安装锁。
- 日志在 `data/desk_control/integrations/slack/`；凭据仍在 `data/desk_control/private/settings.json`。
- 包内 manifest 是运行时来源，仓库根文件供手动导入；回归测试要求两者逐字一致。

## 连接检查

设置页提供配置检查、测试消息、最近投递、附件下载与人工重发。连接检查应使用当前工作区的实际收发记录；配置正确不等于已成功收发消息。结果不确定时先在 Slack 中核对，再决定是否重发。

参考：[Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/) · [确认时限](https://docs.slack.dev/tools/bolt-python/concepts/acknowledge/) · [文件鉴权](https://docs.slack.dev/reference/objects/file-object/) · [限流](https://docs.slack.dev/apis/web-api/rate-limits/)
