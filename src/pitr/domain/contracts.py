"""The sole source of application and report contracts."""
from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal
from pydantic import Field, field_validator, model_validator

from .common import Command, Contract, instant


class Ref(Contract):
    id: str = Field(min_length=1)
    revision: int = Field(ge=1)

    @property
    def key(self) -> str:
        return f'{self.id}@{self.revision}'


class Revision(Contract):
    id: str
    revision: int = Field(default=1, ge=1)
    created_at: str

    @property
    def ref(self) -> Ref:
        return Ref(id=self.id, revision=self.revision)


class Subject(Revision):
    name: str
    aliases: list[str] = Field(default_factory=list)
    identifiers: dict[str, str] = Field(default_factory=dict)
    official_domains: list[str] = Field(default_factory=list)
    status: Literal['unverified', 'manual', 'verified'] = 'unverified'
    evidence: list[Ref] = Field(default_factory=list)


class Scope(Contract):
    subjects: list[str] = Field(default_factory=list)
    period: str = ''
    mode: Literal['live', 'historical'] = 'live'
    as_of: str | None = None
    allow_public_search: bool = True
    proof_level: Literal['proven', 'declared'] = 'proven'

    @field_validator('as_of')
    @classmethod
    def aware(cls, value):
        if value:
            instant(value)
        return value

    @model_validator(mode='after')
    def historical(self):
        if self.mode == 'historical' and not self.as_of:
            raise ValueError('历史研究必须指定截止时间')
        if self.mode == 'historical' and self.allow_public_search:
            raise ValueError('历史研究仅使用已固定的材料，不能开放搜索')
        return self


class SourceBlock(Contract):
    id: str
    text: str
    page: int | None = None
    bbox: list[float] = Field(default_factory=list)


class SourceVersion(Revision):
    title: str
    url: str
    media_type: str
    digest: str
    byte_count: int
    subjects: list[str] = Field(default_factory=list)
    blocks: list[SourceBlock] = Field(default_factory=list)
    page_count: int = 0
    published_at: str | None = None
    available_at: str
    observed_at: str
    availability_basis: Literal['acquired', 'authoritative', 'archive', 'declared'] = 'acquired'
    availability_evidence: str = ''
    origin_group: str = ''
    source_role: Literal['official', 'third_party', 'upload'] = 'upload'
    issues: list[str] = Field(default_factory=list)


class Snapshot(Revision):
    scope: Scope
    sources: list[Ref] = Field(default_factory=list)
    knowledge: list[Ref] = Field(default_factory=list)
    reused: list[Ref] = Field(default_factory=list)
    subject_versions: list[Ref] = Field(default_factory=list)


class EvidenceAnchor(Revision):
    source: Ref
    block_id: str
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    quote: str
    page: int | None = None
    bbox: list[float] = Field(default_factory=list)


class Observation(Revision):
    evidence: Ref
    literal: str
    start: int = Field(ge=0)
    metric: str
    subject: str
    period: str
    original_unit: str
    role: Literal['actual', 'guidance', 'broker_forecast', 'consensus', 'assumption']
    basis: str
    frequency: Literal['quarter', 'annual', 'ytd', 'point']
    table: dict = Field(default_factory=dict)
    unit_evidence: Ref
    period_evidence: Ref
    basis_evidence: Ref


class Value(Revision):
    kind: Literal['observed', 'assumption', 'derived']
    metric: str
    amount: Decimal
    unit: str
    subject: str
    period: str
    basis: str
    frequency: Literal['quarter', 'annual', 'ytd', 'point']
    currency: str = ''
    share_basis: str = ''
    role: Literal['actual', 'guidance', 'broker_forecast', 'consensus', 'assumption', 'derived']
    precision: int = Field(default=3, ge=0, le=8)
    observation: Ref | None = None
    calculation: Ref | None = None
    dependencies: list[Ref] = Field(default_factory=list)
    reason: str = ''
    limitations: list[str] = Field(default_factory=list)

    @field_validator('amount')
    @classmethod
    def finite(cls, value):
        if not value.is_finite():
            raise ValueError('数值必须有限')
        return value


class Calculation(Revision):
    operation: Literal['add', 'subtract', 'multiply', 'divide', 'ratio', 'growth', 'change', 'quarterize']
    inputs: list[Ref]
    amount: Decimal
    unit: str
    rule_version: str = 'finance.1'


class Assertion(Revision):
    title: str
    statement: str
    kind: Literal['source_statement', 'fact', 'interpretation', 'forecast', 'relationship']
    subjects: list[str] = Field(default_factory=list)
    support: list[Ref] = Field(default_factory=list)
    counterevidence: list[Ref] = Field(default_factory=list)
    values: list[Ref] = Field(default_factory=list)
    depends_on: list[Ref] = Field(default_factory=list)
    alternative: str = ''
    limitations: list[str] = Field(default_factory=list)
    next_check: str = ''
    relation: dict = Field(default_factory=dict)


class ModelRevision(Revision):
    title: str
    subjects: list[str]
    assumptions: list[Ref]
    outputs: list[Ref]
    rationale: str


class TextSpan(Contract):
    type: Literal['text'] = 'text'
    text: str


class ValueSpan(Contract):
    type: Literal['value'] = 'value'
    ref: Ref


class CitationSpan(Contract):
    type: Literal['citation'] = 'citation'
    ref: Ref


Inline = Annotated[TextSpan | ValueSpan | CitationSpan, Field(discriminator='type')]


class Paragraph(Contract):
    type: Literal['paragraph'] = 'paragraph'
    id: str
    inlines: list[Inline]
    assertions: list[Ref] = Field(default_factory=list)


class TableBlock(Contract):
    type: Literal['table'] = 'table'
    id: str
    title: str
    columns: list[str] = Field(min_length=1, max_length=10)
    rows: list[list[list[Inline]]]
    note: str = ''

    @model_validator(mode='after')
    def rectangular(self):
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError('表格每行必须与列数一致')
        return self


class ChartSeries(Contract):
    name: str
    values: list[Ref | None]
    role: Literal['actual', 'forecast'] = 'actual'


class ChartBlock(Contract):
    type: Literal['chart'] = 'chart'
    id: str
    title: str
    kind: Literal['column', 'line']
    categories: list[str]
    series: list[ChartSeries]
    unit: str
    note: str = ''

    @model_validator(mode='after')
    def aligned(self):
        if any(len(series.values) != len(self.categories) for series in self.series):
            raise ValueError('图表序列必须与分类对齐')
        return self


Block = Annotated[Paragraph | TableBlock | ChartBlock, Field(discriminator='type')]


class Section(Contract):
    id: str
    title: str
    blocks: list[Block]


class ReportDocument(Revision):
    case_id: str
    run_id: str
    input_revision: int
    snapshot: Ref
    title: str
    report_type: Literal['memo', 'earnings', 'company', 'industry']
    summary: list[Paragraph]
    sections: list[Section]
    gaps: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list)
    assertions: list[Ref] = Field(default_factory=list)
    models: list[Ref] = Field(default_factory=list)
    skills: list[dict] = Field(default_factory=list)
    change_reason: str = ''


class CheckResult(Revision):
    target: Ref
    name: str
    status: Literal['not_run', 'passed', 'failed', 'unavailable', 'skipped', 'error', 'not_applicable']
    coverage: list[str]
    findings: list[dict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    policy_version: str


class ReviewDecision(Revision):
    group_id: str
    targets: list[Ref]
    action: Literal['adopt', 'reject']
    reason: str
    actor: Literal['local_owner'] = 'local_owner'


class ReviewGroup(Revision):
    title: str
    targets: list[Ref] = Field(min_length=1)
    expected_heads: dict[str, int] = Field(default_factory=dict)
    report: Ref | None = None
    reason: str


class ResearchInput(Revision):
    question: str = Field(min_length=1, max_length=16000)
    scope: Scope
    sources: list[Ref] = Field(default_factory=list, max_length=40)
    knowledge: list[Ref] = Field(default_factory=list)
    depth: Literal['interactive', 'standard', 'deep'] = 'standard'
    report_type: Literal['memo', 'earnings', 'company', 'industry'] = 'memo'
    agent_provider: Literal['codex', 'claude'] | None = None
    model: str | None = None
    reasoning: str = 'medium'
    context: dict = Field(default_factory=dict)


class ResearchCase(Contract):
    id: str
    title: str
    input: ResearchInput
    parent_case_id: str | None = None
    created_at: str
    updated_at: str


class Budget(Contract):
    policy_version: str = 'budget.1'
    active_seconds: float = Field(ge=1)
    tool_calls: int = Field(ge=1)
    reserve_fraction: float = Field(default=0.1, gt=0, lt=0.5)
    calibration: str = 'provisional'


class Run(Contract):
    id: str
    case_id: str
    input_revision: int
    snapshot: Ref
    status: Literal['queued', 'running', 'waiting_user', 'budget_exhausted', 'completed', 'cancelled', 'failed']
    stage: str
    generation: int = 0
    agent: dict = Field(default_factory=dict)
    lane: Literal['codex', 'claude', 'local']
    budget: Budget
    active_seconds: float = 0
    tool_calls: int = 0
    cost: float | None = None
    checkpoint: dict = Field(default_factory=dict)
    report: Ref | None = None
    error: str = ''
    questions: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str


class Artifact(Revision):
    report: Ref
    format: Literal['docx'] = 'docx'
    digest: str
    template_version: str
    compiler_version: str
    paper: Literal['Letter', 'A4']
    manifest: dict


class ExportJob(Contract):
    id: str
    report: Ref
    signature: str
    status: Literal['queued', 'running', 'completed', 'failed']
    paper: Literal['Letter', 'A4']
    template_version: str
    check_refs: list[Ref] = Field(default_factory=list)
    delivery_at_request: Literal['ready','partial','draft'] = 'draft'
    artifact: Ref | None = None
    error: str = ''
    attempts: int = 0
    created_at: str
    updated_at: str


class CreateCase(Command):
    question: str = Field(min_length=1, max_length=16000)
    scope: Scope = Field(default_factory=Scope)
    sources: list[Ref] = Field(default_factory=list, max_length=40)
    knowledge: list[Ref] = Field(default_factory=list)
    depth: Literal['interactive', 'standard', 'deep'] = 'standard'
    report_type: Literal['memo', 'earnings', 'company', 'industry'] = 'memo'
    agent_provider: Literal['codex', 'claude'] | None = None
    model: str | None = None
    reasoning: str = 'medium'
    parent_case_id: str | None = None
    news_draft_id: str | None = None


class UpdateInput(CreateCase):
    expected_revision: int = Field(ge=1)


class StartRun(Command):
    expected_revision: int = Field(ge=1)


class ContinueRun(Command):
    expected_generation: int = Field(ge=0)
    additional_seconds: int = Field(default=1800, ge=60, le=86400)
    additional_calls: int = Field(default=180, ge=1, le=10000)
    instruction: str = Field(default='',max_length=16000)


class ReviseReport(Command):
    expected_revision: int = Field(ge=1)
    title: str
    summary: list[Paragraph]
    sections: list[Section]
    gaps: list[str]
    next_steps: list[str]
    reason: str = Field(min_length=1)


class ExportRequest(Command):
    report: Ref
    paper: Literal['Letter', 'A4'] = 'Letter'


class Decide(Command):
    expected_revision: int = Field(ge=1)
    action: Literal['adopt', 'reject']
    reason: str = Field(min_length=1, max_length=4000)


class ToolRequest(Command):
    name: str
    arguments: dict = Field(default_factory=dict)


class AgentAnswer(Contract):
    report: ReportDocument | None = None
    questions: list[str] = Field(default_factory=list)
    findings: str = ''


class RunCompletion(Contract):
    report: Ref | None
    questions: list[str]
    findings: str


class ReviewFinding(Contract):
    target: Ref | None
    severity: Literal['error', 'limitation', 'note']
    message: str
    evidence: list[Ref]
    correction: str


class IndependentReview(Contract):
    verdict: Literal['pass', 'revise', 'blocked']
    findings: list[ReviewFinding]
    checked_assertions: list[Ref]
    evidence: list[Ref]
    summary: str


class ReportView(Contract):
    document: ReportDocument
    delivery: Literal['draft', 'partial', 'ready']
    checks: list[CheckResult]
    current_validity: dict
    values: list[Value]
    value_labels: dict[str, str]
    evidence: list[EvidenceAnchor]
    sources: list[SourceVersion]
    assertions: list[Assertion]
    exports: list[ExportJob]


REVISION_MODELS = {
    'subject': Subject, 'source': SourceVersion, 'snapshot': Snapshot,
    'evidence': EvidenceAnchor, 'observation': Observation, 'value': Value,
    'calculation': Calculation, 'assertion': Assertion, 'model': ModelRevision,
    'report': ReportDocument, 'check': CheckResult, 'review_group': ReviewGroup,
    'decision': ReviewDecision, 'input': ResearchInput, 'artifact': Artifact,
}
