# 安装、启动与恢复

一键启动 `./start` 支持 macOS ARM64/Intel，使用项目私有 `.pitr/` 运行环境。首次从固定版本下载 uv、Python、Node、依赖、LibreOffice 与 Noto 中文字体，校验发行包/字体摘要；无需管理员权限。数据默认保存在 `data/research`，可用 `--data-dir` 指定独立目录。

必须先在本机安装并登录所选官方 Codex 或 Claude Code CLI。在设置页刷新检测，确认版本、认证和模型可用。PITR 不代替登录、不接受浏览器来客连接；服务仅监听回环地址。本机页面通过一次性票据建立会话，变更请求校验来源与 CSRF。

```sh
./start --data-dir /absolute/pitr-data --port 8877 --no-open
# 使用开发环境检查 Word 依赖
uv run research doctor
uv run python scripts/setup_documents.py
```

若渲染器路径由环境管理，可设 `PITR_SOFFICE`。中文字体必须实际注册，只有磁盘上存在字体文件不算可用。本轮验证平台为 macOS ARM64；Linux 可自行安装 LibreOffice 处理离线产物，但正式 Agent 桥接要求 macOS Seatbelt。

## 浏览器连接

默认端口为 `8765`。同一数据目录已有服务时，启动器会复用该服务，实际地址以终端输出为准。首次启动服务的终端需保持运行，按 `Ctrl+C` 停止。在「设置 → 研究 Agent」可查看 CLI、认证和模型检测结果。

若 Chrome 显示「连接本机 PITR」，需要通过启动链接中的一次性票据建立浏览器会话。Chrome、其他浏览器和 Codex 内置浏览器不共享登录状态；只复制普通页面地址，不能完成另一个浏览器的首次连接。

默认浏览器可重新运行 `./start` 连接。若要手动选择 Chrome 或其他浏览器，运行 `./start --no-open`，再在目标浏览器中打开终端新打印的完整链接；使用自定义目录时带上相同的 `--data-dir`。票据两分钟内有效且只能使用一次，已经在一个浏览器打开的链接不能再用于另一个浏览器。连接成功后可正常刷新、收藏页面或使用站内链接；会话失效时重新获取启动链接。

## 备份

在维护页“下载完整备份”，或对正在运行的工作站执行：

```sh
uv run research --data-dir /absolute/pitr-data backup /absolute/pitr-backup.zip
```

备份包括一致数据库快照、不可变原件/对象/报告文件、渲染 PDF/页图、方法包、获取回执、资讯实验历史、Slack 日志与附件。不会导出 Agent 登录凭据、Slack 密钥或浏览器会话。业务恢复不依赖私有宿主会话目录；未完成执行的原生会话不可用时可以从已保存输入重新执行。

## 恢复

恢复到空目录；不覆盖已有数据、不迁移旧数据库：

```sh
uv run research --data-dir /absolute/restored-pitr restore /absolute/pitr-backup.zip
./start --data-dir /absolute/restored-pitr --port 8878
```

恢复会核对 ZIP 清单、SHA-256、SQLite 完整性及引用。已有报告和文件按原字节恢复，不调用模型重造。未完成研究和导出从检查点排队，旧能力凭据失效；Slack 待投递和旧任务绑定保持暂停，不会自动重发。显式发起新的渠道命令才建立新的投递关系。

“重建检索视图”只重建派生索引，不改事实对象、报告或文件。备份归档本身含私有业务资料，应由资料所有者妥善保存。

## 故障定位

研究问题看执行详情及独立检查发现；渲染问题看导出队列错误和 `doctor`。取消不会清除输入、检查点或成果。CLI 版本、认证或连接配置改变会停止沿用不匹配会话；刷新设置后从固定输入发起新的执行。模型请求只经过当前提供方 HTTPS 网关，HTTP 明文模型端点不在支持范围。
