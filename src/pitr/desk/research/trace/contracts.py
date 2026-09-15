from typing import Any, Literal
from pydantic import BaseModel, Field

class TraceEvent(BaseModel):
    seq: int
    event_id: str
    source: str
    kind: str
    occurred_at: str | None = None
    received_at: str
    span_id: str | None = None
    content_ref: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)

class TraceLink(BaseModel):
    id: str
    source: str
    target: str
    kind: Literal['sequence', 'dependency', 'repair', 'recovery', 'artifact']
    label: str = ''

class TraceSpan(BaseModel):
    id: str
    parent_id: str | None = None
    name: str
    kind: str
    executor: str = 'controller'
    status: str = 'running'
    started_at: str | None = None
    ended_at: str | None = None
    duration_ms: float | None = None
    timing: Literal['measured', 'observed', 'missing'] = 'missing'
    attempt: int | None = None
    call_id: str | None = None
    ordinal: int | None = None
    input_version: int | None = None
    input_ref: str | None = None
    output_ref: str | None = None
    error_ref: str | None = None
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    tool_count: int = 0
    issue_count: int = 0
    first_seq: int = 0
    last_seq: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

class TraceSummary(BaseModel):
    active_seconds: float | None = None
    queue_seconds: float | None = None
    waiting_seconds: float | None = None
    tool_seconds: float | None = None
    measured_tools: int = 0
    tool_count: int = 0
    budget_tool_count: int | None = None
    tokens: dict[str, int] = Field(default_factory=dict)
    cost: float | None = None
    capture: str = 'partial'
    gaps: list[str] = Field(default_factory=list)
    reconstructed: bool = False
    sync: dict[str, Any] = Field(default_factory=dict)

class TraceView(BaseModel):
    version: str = 'research-trace.1'
    request_id: str
    task_id: str
    seq: int
    latest_seq: int
    task_status: str
    spans: list[TraceSpan] = Field(default_factory=list)
    links: list[TraceLink] = Field(default_factory=list)
    plans: list[dict[str, Any]] = Field(default_factory=list)
    summary: TraceSummary

class TraceSettings(BaseModel):
    mode: Literal['off', 'metadata', 'content'] = 'off'
    endpoint: str = 'https://api.smith.langchain.com'
    project: str = 'pitr-research'
    api_key: str | None = None

class TraceSyncRequest(BaseModel):
    preview_hash: str | None = None
    preview: bool = False
