"""Research contracts: prose is separate from server-rendered evidence and numbers."""
from typing import Literal, Annotated
from datetime import datetime
from pydantic import Field, field_validator
from ..contracts import Contract, Command, TaskInput

class ResearchTaskInput(TaskInput):
    workflow: Literal['research'] = 'research'
    budget_seconds: int | None = Field(default=None, ge=10)

class ResearchRequest(Command):
    question: str = Field(default='', max_length=12000)
    company: str = ''
    period: str = ''
    intent: Literal['auto','earnings','report_review','investigation'] = 'auto'
    as_of: str | None = None
    snapshot: str = ''
    model_draft_id: str = ''
    context: dict = Field(default_factory=dict)
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    official_urls: list[str] = Field(default_factory=list, max_length=10)
    channel: Literal['web','slack','cli','context'] = 'web'
    parent_request_id: str = ''
    workflow_version: Literal[3] = 3
    scope: dict = Field(default_factory=dict)
    context_source: Literal['none', 'explicit', 'workspace', 'passive'] = 'none'
    # Explicit per-request limits remain available.
    # New research has no task-level budget by default.
    budget_seconds: int | None = Field(default=None, ge=10)
    tool_budget: int | None = Field(default=None, ge=1)
    agent_provider: Literal['codex', 'claude'] | None = None
    model: str | None = Field(default=None, max_length=200)
    reasoning: Literal['low', 'medium', 'high', 'xhigh'] = 'medium'

    @field_validator('as_of')
    @classmethod
    def aware(cls,v):
        if v and datetime.fromisoformat(v.replace('Z','+00:00')).tzinfo is None: raise ValueError('截止时间必须包含时区')
        return v


class ResearchSubject(Contract):
    company_id: str = ''
    name: str
    mention: str = ''
    role: Literal['target', 'reference', 'excluded'] = 'target'
    securities: list[dict] = Field(default_factory=list)
    rationale: str = ''
    identity_sources: list[str] = Field(default_factory=list)
    verified: bool = False

class ResearchInterpretation(Contract):
    title: str
    intent: Literal['earnings', 'report_review', 'investigation', 'collect'] = 'investigation'
    scope_type: Literal['company', 'comparison', 'industry'] = 'company'
    topic: str = ''
    subjects: list[ResearchSubject] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    period: str = ''
    time_description: str = ''
    as_of: str | None = None
    clarification: str = ''
    options: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    context_action: Literal['keep', 'replace'] = 'keep'
    allow_public_search: bool = True

class ResearchMessage(Command):
    text: str = Field(default='', max_length=12000)
    source_ids: list[str] = Field(default_factory=list, max_length=10)
    expected_input_version: int = Field(ge=0)
    company: str = ''
    intent: Literal['earnings','report_review','investigation','collect'] | None = None
    as_of: str | None = None
    release_context: bool = False

class EvidenceRef(Contract):
    id: str
    source_id: str
    source_version: str
    block_id: str
    start: int
    end: int
    quote: str
    available_at: str
    origin: str
    page: int | None = None
    title: str = ''
    url: str = ''
    source_role: str = ''
    origin_group: str = ''
    published_at: str = ''
    observed_at: str = ''
    publication_precision: str = ''
    modified_at: str = ''
    publication_note: str = ''
    original_url: str = ''
    reported_date: str = ''
    bbox: list[float] = Field(default_factory=list)
    company_id: str = ''

class CalculationRef(Contract):
    id: str
    metric: str
    value: float | None
    unit: str
    currency: str = ''
    basis: str = ''
    share_basis: str = ''
    period: str = ''
    frequency: str = ''
    direction: Literal['increase','decrease','unchanged'] | None = None
    precision: int = 3
    formula: str
    dependencies: list[str] = Field(default_factory=list)
    assumption: bool = False
    limitations: list[str] = Field(default_factory=list)
    source_roles: list[str] = Field(default_factory=list)
    verification_status: str = 'source_bound'
    source_locator: dict = Field(default_factory=dict)
    company_id: str = ''
    subject_ids: list[str] = Field(default_factory=list)

class NumberRegistration(Contract):
    company_id: str = Field(default='', description='Required in multi-company research; resolved company_id from context.')
    evidence_id: str
    text: str
    metric: str = Field(description='Stable economic metric, e.g. revenue, gross_profit, operating_profit, net_income. Use the SAME metric for actual/consensus and current/previous comparisons. Put actual/consensus identity in role, revision identity in column_label, and dates in period; do not append those labels to metric.')
    unit: str = Field(description='Use canonical financial units: RMB_mn, USD_mn, RMB_bn, USD_bn, USD_per_ADS, RMB_per_ADS, percent, percentage_points, multiple, ratio. Equivalent displayed spellings are normalized without changing values; preserve the original unit and scale.')
    period: str
    role: Literal['company_actual','reported_actual','reported_consensus','broker_forecast','user_forecast','scenario']
    basis: str = Field(description='Accounting basis stated on the original: GAAP, non-GAAP or disclosed if not established. Never infer agreement just to pass arithmetic.')
    frequency: Literal['quarter','annual','ytd','point']
    row_label: str = ''
    column_label: str = ''
    start: int | None = Field(default=None, ge=0)
    scale: float = 1
    precision: int = Field(default=3, ge=0, le=8)
    table_id: str = ''
    row: int | None = Field(default=None, ge=0, description='Zero-based numeric cell row; not the row label.')
    column: int | None = Field(default=None, ge=0, description='Zero-based numeric cell column; not the column label.')

class CalculationStep(Contract):
    operation: Literal['change','growth','ratio','subtract','quarterize','fee_shock','add','multiply','divide','compare','sum_difference']
    left: str = Field(description='One calculation id or an earlier alias. Never a list or an amount.')
    right: str | None = None
    delta_pp: float | None = None
    alias: str = ''

class TemporalRelation(Contract):
    earlier: str
    later: str


class AgentTemporalRelation(TemporalRelation):
    earlier: str = Field(pattern=r'^20\d{2}(?:Q[1-4]|-\d{2}-\d{2})$', description='Earlier calendar quarter YYYYQn or date YYYY-MM-DD. Never an evidence or claim id.')
    later: str = Field(pattern=r'^20\d{2}(?:Q[1-4]|-\d{2}-\d{2})$', description='Later calendar quarter YYYYQn or date YYYY-MM-DD. Use specific dates for events within the same quarter.')

class ResearchClaim(Contract):
    id: str
    section: Literal['summary','changes','baseline','cash_margin','persistence','model_impact','claims','questions']
    text: str = Field(min_length=1)
    verdict: Literal['supported','partial','insufficient','contradicted','interpretation']
    evidence: list[str] = Field(default_factory=list)
    counterevidence: list[str] = Field(default_factory=list)
    calculations: list[str] = Field(default_factory=list)
    depends_on: list[str] = Field(default_factory=list)
    chronology: list[TemporalRelation] = Field(default_factory=list)
    alternative: str = ''
    next_check: str = ''
    original_claim: str = ''
    original_evidence: list[str] = Field(default_factory=list)
    counterevidence_notes: str = ''
    claim_type: Literal['fact', 'author_statement', 'calculation', 'interpretation'] = 'interpretation'
    requirement_ids: list[str] = Field(default_factory=list)
    temporal_scope: Literal['at_report', 'subsequent', 'general'] = 'general'
    revision_reason: str = ''
    subject_ids: list[str] = Field(default_factory=list)


EvidenceId = Annotated[str, Field(pattern=r'^evidence_[a-f0-9]{24}$', description='Exact evidence id returned by a tool: evidence_ plus all 24 hex characters; never abbreviate or use prose.')]
CalculationId = Annotated[str, Field(pattern=r'^calculation_[a-f0-9]{24}$', description='Exact calculation id: calculation_ plus all 24 hex characters, without {{ }} wrappers.')]


class AgentClaim(ResearchClaim):
    evidence: list[EvidenceId] = Field(default_factory=list, description='Supporting source references; arithmetic operands are also linked by the server.')
    counterevidence: list[EvidenceId] = Field(default_factory=list, description='Actual challenging evidence ids only. Explain limitations in counterevidence_notes; empty is valid.')
    original_evidence: list[EvidenceId] = Field(default_factory=list, description='References locating the author statement being reviewed, not independent corroboration.')
    calculations: list[CalculationId] = Field(default_factory=list)
    chronology: list[AgentTemporalRelation] = Field(default_factory=list)


class RequiredConcept(Contract):
    name: str
    terms: list[str] = Field(min_length=1, description='Equivalent explicit terms for this concept; at least one must appear in the linked report claims, not only in the coverage self-assessment.')


class RequiredComparison(Contract):
    metric: str
    period: str = ''
    basis: str = ''


class Requirement(Contract):
    id: str
    question: str
    source_id: str = ''
    pages: list[int] = Field(default_factory=list)
    kind: Literal['question', 'table', 'figure', 'model', 'temporal'] = 'question'
    reason: str = ''
    check: Literal['answer','consensus_comparison_ratios','forecast_revision_ratios','valuation_price_reconciliation','consensus_profit_reconciliation','segment_revenue_reconciliation','public_investigation'] = 'answer'
    required_concepts: list[RequiredConcept] = Field(default_factory=list)
    required_metrics: list[str] = Field(default_factory=list)
    required_periods: list[str] = Field(default_factory=list)
    required_comparisons: list[RequiredComparison] = Field(default_factory=list)


class RequirementResolution(Contract):
    requirement_id: str
    status: Literal['answered', 'gap', 'pending']
    claim_ids: list[str] = Field(default_factory=list)
    explanation: str = ''
    check_receipts: list[str] = Field(default_factory=list)
    needed_input: str = ''


class ReviewFinding(Contract):
    id: str
    severity: Literal['blocking', 'advisory']
    code: Literal['omission', 'evidence', 'inference', 'numeric', 'temporal', 'gap', 'regression']
    claim_id: str = ''
    requirement_id: str = ''
    field: str = ''
    message: str
    requested_change: str
    evidence: list[EvidenceId] = Field(default_factory=list)


class ReviewSourceCheck(Contract):
    source_id: str
    status: Literal['used','irrelevant','unavailable']
    reason: str
    claim_ids: list[str] = Field(default_factory=list)
    evidence: list[EvidenceId] = Field(default_factory=list)


class IndependentReview(Contract):
    verdict: Literal['pass', 'revise', 'blocked']
    summary: str
    findings: list[ReviewFinding] = Field(default_factory=list)
    additional_requirements: list[Requirement] = Field(default_factory=list)
    checked_requirements: list[str] = Field(default_factory=list)
    check_receipts: list[str] = Field(default_factory=list)
    source_checks: list[ReviewSourceCheck] = Field(default_factory=list, description='逐项处理复核者通过 fetch_public_source 取得的原件。used 须自行成功阅读并给出该原件 evidence_ID 和受影响 claim_ids；irrelevant/unavailable 必须说明具体原因。用于判断的原件须落实为报告引用，不能仅修改缺口措辞。')
    blocking_reason: str = ''

class CoverageCheck(Contract):
    key: str
    status: Literal['answered','gap','missing','invalid']
    claim_ids: list[str] = Field(default_factory=list)
    explanation: str = ''

class DraftOutcome(Contract):
    title: str
    claims: list[ResearchClaim] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    requirement_resolutions: list[RequirementResolution] = Field(default_factory=list)
    # Coverage is recomputed by the server; the model cannot self-certify it.


class AgentDraft(DraftOutcome):
    claims: list[AgentClaim] = Field(default_factory=list)

class ResearchOutcome(Contract):
    artifact_version: int | None = Field(default=None, ge=1)
    schema_version: Literal[3] = 3
    title: str
    request_id: str
    input_version: int
    snapshot: str
    as_of: str
    intent: str
    claims: list[dict] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    calculations: list[CalculationRef] = Field(default_factory=list)
    metrics: list[dict] = Field(default_factory=list)
    coverage: list[CoverageCheck] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    issues: list[dict] = Field(default_factory=list)
    status: Literal['review_ready','partial','needs_review']
    verification: dict
    handoffs: list[dict] = Field(default_factory=list)
    human_review: str = 'not_reviewed'
    requirements: list[Requirement] = Field(default_factory=list)
    requirement_resolutions: list[RequirementResolution] = Field(default_factory=list)
    reviews: list[dict] = Field(default_factory=list)
    reading: list[dict] = Field(default_factory=list)
    delivery: dict = Field(default_factory=dict)
    subjects: list[ResearchSubject] = Field(default_factory=list)
    scope_type: str = 'company'
    key_claim_ids: list[str] = Field(default_factory=list)
    sections: list[dict] = Field(default_factory=list)
    comparisons: list[dict] = Field(default_factory=list)
