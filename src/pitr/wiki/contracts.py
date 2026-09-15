from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from pitr.desk.contracts import Contract, Command, Citation, Metric

Availability = Literal['available', 'disputed', 'needs_review', 'quarantined', 'superseded', 'withdrawn']
PageType = Literal['source', 'company', 'concept', 'topic', 'analysis']


def timestamp(value: str) -> str:
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('时间必须包含时区')
    return dt.astimezone(timezone.utc).isoformat()


class Reference(Contract):
    id: str = Field(min_length=1, max_length=240)
    version: int = Field(ge=1)

    @property
    def key(self):
        return f'{self.id}@v{self.version}'


class Relation(Contract):
    target: Reference
    relation: Literal['supports', 'derived_from', 'used_in', 'related']
    paragraph: str = ''


class CaptureEnvelope(Command):
    provider: Literal['official', 'claude', 'codex', 'slack', 'research', 'manual']
    external_id: str = Field(min_length=1, max_length=500)
    company: str = ''
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(max_length=2_000_000)
    session_id: str = ''
    thread_id: str = ''
    url: str = ''
    available_at: str | None = None
    observed_at: str | None = None
    revision_of: str | None = None
    action: Literal['capture', 'revise', 'withdraw'] = 'capture'
    origin: str = 'user'
    payload_object: str | None = None
    attachments: list[str] = Field(default_factory=list)

    @field_validator('available_at', 'observed_at')
    @classmethod
    def times(cls, value):
        return timestamp(value) if value else value


class RevisionDraft(Contract):
    id: str = Field(min_length=1, max_length=240, pattern=r'^[\w:.\-]+$')
    kind: Literal['knowledge', 'page', 'policy']
    expected_version: int = Field(default=0, ge=0)
    title: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=100_000)
    summary: str = ''
    page_type: PageType | None = None
    nature: Literal['fact', 'interpretation', 'method'] | None = None
    scope: str = ''
    business_period: str = ''
    applicability: str = ''
    formula: str = ''
    failure_cases: str = ''
    example: str = ''
    citations: list[Citation] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    numeric_assertions: list[dict[str, Any]] = Field(default_factory=list)
    corrects: Reference | None = None
    reason: str = Field(min_length=1)
    change_type: Literal['new', 'supplement', 'conflict', 'scope', 'correction'] = 'new'


class PublishedRevision(RevisionDraft):
    version: int = Field(ge=1)
    company: str
    published_at: str
    publication_sequence: int = Field(ge=0)
    policy: Reference | None = None
    proposal_id: str | None = None
    review_status: str
    body_object: str = Field(pattern=r'^[0-9a-f]{64}$')
    decision: dict[str, Any] | None = None
    evidence_observations: list[Metric] = Field(default_factory=list)
    origin: str = ''


class KnowledgeRevision(PublishedRevision):
    kind: Literal['knowledge'] = 'knowledge'
    nature: Literal['fact', 'interpretation', 'method']
    scope: str = Field(min_length=1)


class WikiPageRevision(PublishedRevision):
    kind: Literal['page'] = 'page'
    page_type: PageType


class PolicyRevision(PublishedRevision):
    kind: Literal['policy'] = 'policy'


class ProposalInput(Command):
    company: str = Field(min_length=1)
    policy: Reference
    changes: list[RevisionDraft] = Field(min_length=1, max_length=50)
    inputs: list[Reference] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    origin: Literal['human', 'agent', 'ingest', 'query', 'inspection', 'research'] = 'human'
    replaces: str | None = None
    issue_ids: list[str] = Field(default_factory=list)
    as_of: str | None = None
    model_output: str | None = None

    @field_validator('as_of')
    @classmethod
    def times(cls, value):
        return timestamp(value) if value else value


class DecisionRecord(Command):
    digest: str
    action: Literal['adopt', 'reject']
    reason: str = Field(min_length=1)
    alternatives: str = ''
    consequences: str = ''
    reviewer_identity: str = Field(default='local_owner', max_length=200)


class KnowledgeEvent(Contract):
    sequence: int
    id: str
    company: str
    kind: str
    occurred_at: str
    payload_object: str


class IssueInput(Command):
    target: Reference
    paragraph: str = ''
    issue_type: Literal['citation', 'object', 'numeric', 'calculation', 'semantic', 'conflict', 'scope', 'gap', 'structure']
    description: str = Field(min_length=1)
    evidence: list[Citation] = Field(default_factory=list)
    discovered_by: Literal['human', 'agent', 'slack', 'rule', 'semantic'] = 'human'


class KnowledgeIssue(IssueInput):
    id: str
    state: Literal['open', 'closed']
    impacts: dict[str, Any]
    content_resolution: str = ''
    company: str
    created_at: str
    policy: Reference
    confirmed_hard_error: bool
    reproduced_failures: list[dict[str, str]] = Field(default_factory=list)
    previous_status: dict[str, Any]
    updated_at: str | None = None
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    reports: list[dict[str, Any]] = Field(default_factory=list)


class IssueDecision(Command):
    action: Literal['dismiss', 'withdraw', 'resolve', 'impact']
    reason: str = Field(min_length=1)
    target: str = ''
    disposition: Literal['reviewed_unchanged', 'revised', 'withdrawn', 'not_applicable'] | None = None


class InspectionRun(Contract):
    id: str
    kind: Literal['rules', 'semantic']
    company: str
    policy: Reference
    started_at: str
    finished_at: str | None = None
    scope: list[str] = Field(default_factory=list)
    skipped: list[dict[str, str]] = Field(default_factory=list)
    failures: list[dict[str, str]] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)
    budget_seconds: int = 600
    budget_exhausted: bool = False
    model_outputs: list[str] = Field(default_factory=list)
    elapsed_seconds: float | None = None
    feedback: dict[str, Any] | None = None


class QueryInput(Command):
    company: str
    question: str = Field(min_length=1)
    as_of: str | None = None
    hybrid: bool = False
    context_refs: list[Reference] = Field(default_factory=list, max_length=20)

    @field_validator('as_of')
    @classmethod
    def times(cls, value):
        return timestamp(value) if value else value


class AnswerInput(Command):
    query_id: str
    title: str
    content: str
    used: list[Reference] = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)
    numeric_assertions: list[dict[str, Any]] = Field(default_factory=list)
    save_proposal: bool = True
    target: Reference | None = None
    writeback: Literal['topic', 'analysis'] = 'topic'


class WikiJobRequest(Command):
    agent_provider: Literal['codex', 'claude'] | None = None
    model: str | None = Field(default=None, max_length=200)
    intent: Literal['build', 'update'] = 'build'
    company: str = Field(min_length=1, max_length=40)
    research_focus: str = Field(default='业务模式、盈利驱动、竞争、风险与现金转化', max_length=12000)
    source_policy: Literal['official_industry_media'] = 'official_industry_media'
    as_of: str | None = None
    years: int = Field(default=3, ge=1, le=10)
    quarters: int = Field(default=8, ge=1, le=40)
    budget_seconds: int = Field(default=1200, ge=10, le=1800)
    max_documents: int = Field(default=24, ge=1, le=40)
    channel: Literal['web', 'slack', 'cli', 'schedule'] = 'web'
    seed_urls: list[str] = Field(default_factory=list, max_length=40)
    source_ids: list[str] = Field(default_factory=list, max_length=40)
    resume_job_id: str | None = None

    @model_validator(mode='after')
    def update_budget(self):
        if self.intent == 'update' and 'budget_seconds' not in self.model_fields_set:
            self.budget_seconds = 600
        return self

    @field_validator('as_of')
    @classmethod
    def cutoff(cls, value):
        return timestamp(value) if value else value


class CompanyRegistration(Command):
    company: str = Field(pattern=r'^[A-Z][A-Z0-9.\-]{0,15}$')
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    official_domains: list[str] = Field(default_factory=list, max_length=20)
    catalog_urls: list[str] = Field(default_factory=list, max_length=20)
    securities: list[dict] = Field(default_factory=list, max_length=12)
    brands: list[str] = Field(default_factory=list, max_length=30)
    identity_sources: list[str] = Field(default_factory=list, max_length=20)


class WikiUpdateSchedule(Command):
    company: str
    enabled: bool = True
    frequency: Literal['daily', 'weekly', 'custom'] = 'weekly'
    weekdays: list[int] = Field(default_factory=lambda: [0], min_length=1, max_length=7)
    local_time: str = Field(default='09:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    timezone: str = 'Asia/Shanghai'
    research_focus: str = '复核新披露与已有研究认识的变化'
    budget_seconds: int = Field(default=600, ge=10, le=1800)
    notification_event_id: str = ''

    @field_validator('weekdays')
    @classmethod
    def days(cls, value):
        if any(type(d) is not int or not 0 <= d <= 6 for d in value):
            raise ValueError('星期必须为周一至周日')
        return sorted(set(value))

    @field_validator('timezone')
    @classmethod
    def zone(cls, value):
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(value)
        except Exception as error:
            raise ValueError('未知时区') from error
        return value


class WikiJobResult(Contract):
    job_id: str
    execution_status: str
    publication_status: str = 'not_published'
    materials: list[dict[str, Any]] = Field(default_factory=list)
    coverage: list[dict[str, Any]] = Field(default_factory=list)
    checks: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)
    proposal_id: str | None = None
    previous_failures: list[dict[str, Any]] = Field(default_factory=list)
    supplemental_discovery: dict[str, Any] = Field(default_factory=dict)
    catalog_checks: list[dict[str, Any]] = Field(default_factory=list)
    catalog_excluded: list[dict[str, Any]] = Field(default_factory=list)
    resumed_from: str | None = None


class InspectionFeedback(Command):
    reviewed_all: Literal[True]
    false_positives: int = Field(ge=0)
    missed_issues: int = Field(ge=0)
    review_minutes: float = Field(ge=0)
    note: str = Field(min_length=1)


class ValidateUse(Contract):
    company: str
    references: list[Reference] = Field(min_length=1,max_length=100)
    as_of: str | None = None
