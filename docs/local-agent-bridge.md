# 一键启动与本机 Agent 桥接

## 使用

在 macOS（Apple Silicon / Intel）提前安装并登录官方 Codex 或 Claude Code。项目目录中执行 `./start`。选择页面顶部的 Agent 和模型后开始研究或使用 Wiki。

```sh
./start
./start --data-dir /path/to/desk --port 8877 --no-open
```

默认数据目录 `data/desk_control`，端口 `127.0.0.1:8765`。终端前台托管服务，Ctrl+C、SIGHUP 或 SIGTERM 停止服务。重新执行命令打开同一目录的现有实例；端口被其他应用占用时只报错。

首次运行下载校验后的 uv 0.12.13、CPython 3.12.12、Node.js 24.13.0。uv 和 Node 两种架构的 SHA-256 固定在启动器中；Python 下载与校验表由这个固定 uv 版本提供。运行环境、Python 依赖和缓存位于 `.pitr/`，前端依赖位于 `web/node_modules/`，不安装系统软件、不需要 sudo。依赖锁文件和前端输入摘要决定是否重新安装／构建。下载或构建失败可重复运行。

## 选择与调用

- 仅一个 Agent 就绪时自动选中；两个都就绪时由用户选择。各自的模型选择独立保存。
- Codex 的候选模型来自 App Server；Claude 提供本机配置、官方别名和自定义 ID。候选项不代表已验证的账号权限。
- 每个任务保存 `agent` 快照：provider、请求模型、本机默认值、实际模型、推理设置、CLI 版本、认证方式和连接配置摘要。恢复与子任务继承快照。连接／认证方式变化会停止并给出恢复提示。
- Claude 的 `[1m]` 长上下文后缀独立保留，原生事件返回不带后缀的实际模型名称时，后续调用仍沿用该上下文选项。
- 研究理解、身份核实、调查、独立复核、修复、搜索，以及 Wiki 发现、整理、问答和语义巡检均通过 `AgentRuntime`。研究者与复核者有不同会话；同一会话串行，搜索子调用使用独立会话。
- `agent_bindings` 保存实际解析模型，`agent_calls` 保存各次调用、会话、状态与可观察用量。不可观察的用量／费用保留为空。研究工具事件进入 Trace；运行目录保存完整 JSONL 与结构化结果。
- 公开搜索记录取自真实工具事件。候选网址仍需获取原件、核对引用与数值；搜索摘要不是证据。研究交付需要核验，Wiki 发布需要人工审核。

## 原生配置与隔离

Codex 使用 `app-server --stdio`。App Server 不支持 `exec` 的 `--ignore-user-config` 和 `--ignore-rules`；macOS Seatbelt 将个人配置、规则、skills、hooks 等路径视为不存在，再显式传入筛选后的模型和连接设置。App Server 的 MCP 需要 tool host，因此保留该通信组件，关闭 shell、文件编辑、个人扩展和其他非研究工具。

Claude 使用 `-p`、流式 JSON、JSON Schema、精确 session 续接、restricted 模式、空 setting sources、禁用 slash commands 和 strict MCP config。`--safe-mode` 会连显式注入的 PITR MCP 一起禁用，因此不用于桥接。仅允许 PITR MCP 和需要时的 WebSearch，不使用全局跳过权限。

CLI 使用自己的 HOME／凭据存储，自行读取或刷新登录。PITR 不读取或保存 OAuth 账号令牌，不改写 CLI 配置。启动环境仅保留认证、模型、证书和代理等连接所需字段。系统隔离拒绝读取控制数据库、其他运行目录和项目源文件；只开放当前运行目录、CLI、Python、凭据与必要网络路径。每次调用先执行实际文件权限探针。

文件访问采用允许名单，也拒绝读取放在系统临时目录或其他挂载位置的无关工作区。系统运行库、证书及认证存储按必要路径开放；`TMPDIR` 和 Claude 的 [`CLAUDE_CODE_TMPDIR`](https://code.claude.com/docs/en/env-vars) 指向当前调用的私有临时目录。权限探针包含一个位于运行目录以外的真实临时文件。

## 本机访问与生命周期

启动链接的随机票据位于 URL fragment，使用一次或两分钟后失效。交换后从地址栏移除，建立 HttpOnly、SameSite=Strict Cookie。API 读取要求浏览器会话，写请求另需 CSRF 令牌；所有请求检查 Host、Origin 和本机来源。私有 Unix socket 为重复启动签发新票据，文件权限限制为当前 OS 用户。

队列停止时先撤销执行租约，将未完成任务保留为 interrupted／queued，再关闭 Agent 进程组。取消状态不会被迟到结果覆盖。每个子进程组还有通过私有管道监测 daemon 退出的守护进程，daemon 异常退出时也回收该组。此服务只面向同一用户的本机浏览器，不是多用户远程托管服务。

## 开发与验证

普通使用不运行 Vite 开发服务器。开发时可直接调用 `create_app(..., worker=False)` 使用离线测试服务器；生产入口统一经过 daemon 访问控制。修改前端后执行 `./start` 会自动重建。

```sh
uv sync --extra dev
uv run pytest -q
cd web && npm run build
```

协议替身测试位于 `tests/test_agent_runtime.py`，覆盖结构化返回、提前到达的事件、续接、选择快照、取消、恢复、认证边界、真实搜索凭据与进程回收。

参考：[Codex App Server](https://learn.chatgpt.com/docs/app-server)、[Claude CLI](https://code.claude.com/docs/en/cli-reference)、[Claude 模型配置](https://code.claude.com/docs/en/model-config)。
