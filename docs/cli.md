# CLI 与接口

`research` 是运行中工作站的薄客户端。它通过本机一次性登录票据访问 `/api/v1`，普通研究命令不直接读写数据库。

```sh
uv run research --data-dir data/research request /subjects
uv run research --data-dir data/research request /cases --method POST --input /absolute/create-case.json
uv run research --data-dir data/research request /reports/REPORT_ID/revisions/1
uv run research --data-dir data/research request /exports --method POST --input /absolute/export.json
uv run research --data-dir data/research request /artifacts/ARTIFACT_ID/download --output /absolute/report.docx
```

创建案例请求示例（主体须先登记，原件引用使用上传/获取接口返回的准确版本）：

```json
{
  "operation_id": "owner-case-001",
  "question": "对比两期披露，哪些盈利变化有原文支持？",
  "scope": {"subjects": ["PDD"], "period": "2025Q2 / 2024Q2", "allow_public_search": false},
  "sources": [],
  "depth": "standard",
  "report_type": "earnings",
  "agent_provider": "codex"
}
```

启动研究：`POST /cases/{id}/runs`，传 `operation_id` 与 `expected_revision`。补充输入：`POST /cases/{id}/inputs`，传新输入和预期修订。继续：`POST /runs/{id}/continue`，传 `expected_generation`、新增预算和可选 `instruction`。取消：`POST /runs/{id}/cancel`。

报告修订：`POST /reports/{id}/revisions`。人工决定：`POST /review/{group_id}/decisions`。独立导出：`POST /exports`，传报告引用和 `paper`；失败重试：`POST /exports/{id}/retry`。备份、检索重建、订阅、资料目录和评测均使用相同 `/api/v1` 命令。

读取知识、关系和检索时统一传 `subject`、`mode=historical` 与带时区 `as_of`；未指定时为当前范围。来源列表支持 `all_revisions=true`。具体请求 Schema 以 `/openapi.json` 与 `schemas/` 为准。

```sh
uv run python -m pitr.schemas --check
npm --prefix web run check-types
```

Pydantic 请求 Schema 使用校验模式，默认字段可省略；响应 Schema 使用序列化模式，返回的默认字段为必需，TypeScript 不再强行改写所有字段的可选性。

Agent 使用单独的 `python -m pitr.tool_cli catalog / call`，凭据由运行控制器签发。它没有工作站 owner 会话，不能通过 CLI 获得任意业务写权限。
