"""Read models rebuilt from E's versioned objects and observed execution events."""
from typing import Literal
from pydantic import Field
from .common import Contract
from .contracts import Ref, Revision, Subject, Assertion, ModelRevision, Value, ResearchCase, Scope


class TraceEvent(Contract):
    seq: int
    at: str
    kind: str
    data: dict = Field(default_factory=dict)


class TraceSpan(Contract):
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
    generation: int = 0
    ordinal: int | None = None
    input_version: int | None = None
    artifact_refs: list[Ref] = Field(default_factory=list)
    tool_count: int = 0
    issue_count: int = 0
    first_seq: int = 0
    last_seq: int = 0
    metadata: dict = Field(default_factory=dict)


class TraceLink(Contract):
    id: str
    source: str
    target: str
    kind: Literal['sequence', 'dependency', 'repair', 'recovery', 'artifact']


class TraceSummary(Contract):
    active_seconds: float | None = None
    queue_seconds: float | None = None
    waiting_seconds: float | None = None
    tool_seconds: float | None = None
    measured_tools: int = 0
    tool_count: int = 0
    budget_tool_count: int | None = None
    tokens: dict[str, int] = Field(default_factory=dict)
    gaps: list[str] = Field(default_factory=list)


class TraceView(Contract):
    version: str = 'trace.1'
    run_id: str
    case_id: str
    seq: int
    latest_seq: int
    task_status: str
    spans: list[TraceSpan]
    links: list[TraceLink]
    summary: TraceSummary


class CurrentValidity(Contract):
    status: Literal['available', 'needs_review', 'withdrawn', 'superseded']
    reason: str = ''
    updated_at: str | None = None


class SourceSummary(Revision):
    title: str
    url: str
    media_type: str
    subjects: list[str]
    source_role: Literal['official', 'third_party', 'upload']
    available_at: str
    published_at: str | None


class ReportSummary(Revision):
    title: str
    case_id: str
    run_id: str
    input_revision: int
    change_reason: str


class CompanyHistory(Contract):
    kind: Literal['source', 'report', 'decision']
    ref: Ref
    title: str
    at: str
    case_id: str | None = None
    run_id: str | None = None
    action: str | None = None
    current_validity: CurrentValidity | None = None


class KnowledgeItem(Contract):
    object: Assertion | ModelRevision
    current_validity: CurrentValidity


class CompanySource(Contract):
    object: SourceSummary
    current_validity: CurrentValidity


class CompanyValue(Contract):
    object: Value
    current_validity: CurrentValidity


class CompanyView(Contract):
    subject: Subject
    subject_at_time: bool = True
    scope: Scope
    knowledge: list[KnowledgeItem]
    sources: list[CompanySource]
    values: list[CompanyValue]
    cases: list[ResearchCase]
    reports: list[ReportSummary]
    history: list[CompanyHistory]
