from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Citation(Contract):
    source_id: str
    block_id: str
    quote: str = Field(min_length=1)


class SourceBlock(Contract):
    id: str
    text: str
    page: int | None = None
    bbox: list[float] | None = None
    kind: Literal['paragraph', 'table'] = 'paragraph'
    cells: list[list[str]] = Field(default_factory=list)


class Document(Contract):
    id: str
    company: str
    title: str
    url: str
    digest: str
    media_type: str
    published_at: str
    available_at: str
    observed_at: str
    publication_precision: Literal['timestamp', 'day', 'observed'] = 'observed'
    origin_group: str
    blocks: list[SourceBlock]
    supersedes: str | None = None
    withdrawn_at: str | None = None
    file_name: str
    issues: list[str] = Field(default_factory=list)
    identity_version: str = 'desk-original.1'


class Metric(Contract):
    id: str
    name: str
    label: str
    period: str
    value: float
    unit: str
    basis: Literal['GAAP', 'non-GAAP', 'disclosed'] = 'GAAP'
    frequency: Literal['quarter', 'annual', 'ytd', 'instant'] = 'quarter'
    citation: Citation
    status: Literal['extracted', 'checked', 'corrected'] = 'extracted'
    correction_reason: str = ''


class Point(Contract):
    reviewed: bool = False
    period: str
    value: float | None
    observation_ids: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    calculation: str = ''
    issues: list[str] = Field(default_factory=list)


class MetricRow(Contract):
    key: str
    label: str
    group: str
    unit: str
    basis: str
    nature: Literal['flow', 'stock', 'ratio', 'per_share']
    actual: Point
    prior: Point | None = None
    baseline: float | None = None
    baseline_type: str = 'user_forecast'
    difference: float | None = None
    difference_pct: float | None = None
    yoy: float | None = None
    yoy_bps: float | None = None
    series: list[Point]
    checked: bool = False
    issues: list[str] = Field(default_factory=list)


class DeskView(Contract):
    company: str
    period: str
    periods: list[str]
    as_of: str
    snapshot: str
    rows: list[MetricRow]
    documents: list[Document]
    bridge: list[dict[str, Any]]
    model: dict[str, Any] | None = None
    issues: list[str]


class Command(Contract):
    operation_id: str = Field(min_length=8, max_length=160)


class AgentCommand(Command):
    agent_provider: Literal['codex', 'claude'] | None = None
    model: str | None = Field(default=None, max_length=200)


class TaskInput(AgentCommand):
    workflow: Literal['disclosures', 'wiki_compile', 'wiki_inspect', 'wiki_answer', 'wiki_job', 'research']
    company: str = 'PDD'
    snapshot: str = ''
    parameters: dict[str, Any] = Field(default_factory=dict)
    budget_seconds: int = Field(default=300, ge=10, le=1800)


class SourceInput(Contract):
    company: str = 'PDD'
    url: str
    title: str = ''


class SecretInput(Contract):
    agent_provider: Literal['codex', 'claude'] | None = None
    agent_models: dict[str, str | None] | None = None
    sec_user_agent: str | None = None
    slack_app_token: str | None = None
    slack_bot_token: str | None = None
    slack_team_id: str | None = None
    slack_user_id: str | None = None
    slack_channel_ids: list[str] | None = None
    slack_enabled: bool | None = None
