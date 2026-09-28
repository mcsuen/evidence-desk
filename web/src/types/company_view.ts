/* generated from schemas/company_view.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Name = string
export type Aliases = string[]
export type OfficialDomains = string[]
export type Status = 'unverified' | 'manual' | 'verified'
export type Id1 = string
export type Revision1 = number
export type Evidence = Ref[]
export type SubjectAtTime = boolean
export type Subjects = string[]
export type Period = string
export type Mode = 'live' | 'historical'
export type AsOf = string | null
export type AllowPublicSearch = boolean
export type ProofLevel = 'proven' | 'declared'
export type Object = Assertion | ModelRevision
export type Id2 = string
export type Revision2 = number
export type CreatedAt1 = string
export type Title = string
export type Statement = string
export type Kind = 'source_statement' | 'fact' | 'interpretation' | 'forecast' | 'relationship'
export type Subjects1 = string[]
export type Support = Ref[]
export type Counterevidence = Ref[]
export type Values = Ref[]
export type DependsOn = Ref[]
export type Alternative = string
export type Limitations = string[]
export type NextCheck = string
export type Id3 = string
export type Revision3 = number
export type CreatedAt2 = string
export type Title1 = string
export type Subjects2 = string[]
export type Assumptions = Ref[]
export type Outputs = Ref[]
export type Rationale = string
export type Status1 = 'available' | 'needs_review' | 'withdrawn' | 'superseded'
export type Reason = string
export type UpdatedAt = string | null
export type Knowledge = KnowledgeItem[]
export type Id4 = string
export type Revision4 = number
export type CreatedAt3 = string
export type Title2 = string
export type Url = string
export type MediaType = string
export type Subjects3 = string[]
export type SourceRole = 'official' | 'third_party' | 'upload'
export type AvailableAt = string
export type PublishedAt = string | null
export type Sources = CompanySource[]
export type Id5 = string
export type Revision5 = number
export type CreatedAt4 = string
export type Kind1 = 'observed' | 'assumption' | 'derived'
export type Metric = string
export type Amount = string
export type Unit = string
export type Subject1 = string
export type Period1 = string
export type Basis = string
export type Frequency = 'quarter' | 'annual' | 'ytd' | 'point'
export type Currency = string
export type ShareBasis = string
export type Role = 'actual' | 'guidance' | 'broker_forecast' | 'consensus' | 'assumption' | 'derived'
export type Precision = number
export type Dependencies = Ref[]
export type Reason1 = string
export type Limitations1 = string[]
export type Values1 = CompanyValue[]
export type Id6 = string
export type Title3 = string
export type Id7 = string
export type Revision6 = number
export type CreatedAt5 = string
export type Question = string
/**
 * @maxItems 40
 */
export type Sources1 = Ref[]
export type Knowledge1 = Ref[]
export type Depth = 'interactive' | 'standard' | 'deep'
export type ReportType = 'memo' | 'earnings' | 'company' | 'industry'
export type AgentProvider = ('codex' | 'claude') | null
export type Model = string | null
export type Reasoning = string
export type ParentCaseId = string | null
export type CreatedAt6 = string
export type UpdatedAt1 = string
export type Cases = ResearchCase[]
export type Id8 = string
export type Revision7 = number
export type CreatedAt7 = string
export type Title4 = string
export type CaseId = string
export type RunId = string
export type InputRevision = number
export type ChangeReason = string
export type Reports = ReportSummary[]
export type Kind2 = 'source' | 'report' | 'decision'
export type Title5 = string
export type At = string
export type CaseId1 = string | null
export type RunId1 = string | null
export type Action = string | null
export type History = CompanyHistory[]

export interface CompanyView {
  subject: Subject
  subject_at_time: SubjectAtTime
  scope: Scope
  knowledge: Knowledge
  sources: Sources
  values: Values1
  cases: Cases
  reports: Reports
  history: History
}
export interface Subject {
  id: Id
  revision: Revision
  created_at: CreatedAt
  name: Name
  aliases: Aliases
  identifiers: Identifiers
  official_domains: OfficialDomains
  status: Status
  evidence: Evidence
}
export interface Identifiers {
  [k: string]: string
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface Scope {
  subjects: Subjects
  period: Period
  mode: Mode
  as_of: AsOf
  allow_public_search: AllowPublicSearch
  proof_level: ProofLevel
}
export interface KnowledgeItem {
  object: Object
  current_validity: CurrentValidity
}
export interface Assertion {
  id: Id2
  revision: Revision2
  created_at: CreatedAt1
  title: Title
  statement: Statement
  kind: Kind
  subjects: Subjects1
  support: Support
  counterevidence: Counterevidence
  values: Values
  depends_on: DependsOn
  alternative: Alternative
  limitations: Limitations
  next_check: NextCheck
  relation: Relation
}
export interface Relation {
  [k: string]: unknown
}
export interface ModelRevision {
  id: Id3
  revision: Revision3
  created_at: CreatedAt2
  title: Title1
  subjects: Subjects2
  assumptions: Assumptions
  outputs: Outputs
  rationale: Rationale
}
export interface CurrentValidity {
  status: Status1
  reason: Reason
  updated_at: UpdatedAt
}
export interface CompanySource {
  object: SourceSummary
  current_validity: CurrentValidity
}
export interface SourceSummary {
  id: Id4
  revision: Revision4
  created_at: CreatedAt3
  title: Title2
  url: Url
  media_type: MediaType
  subjects: Subjects3
  source_role: SourceRole
  available_at: AvailableAt
  published_at: PublishedAt
}
export interface CompanyValue {
  object: Value
  current_validity: CurrentValidity
}
export interface Value {
  id: Id5
  revision: Revision5
  created_at: CreatedAt4
  kind: Kind1
  metric: Metric
  amount: Amount
  unit: Unit
  subject: Subject1
  period: Period1
  basis: Basis
  frequency: Frequency
  currency: Currency
  share_basis: ShareBasis
  role: Role
  precision: Precision
  observation: Ref | null
  calculation: Ref | null
  dependencies: Dependencies
  reason: Reason1
  limitations: Limitations1
}
export interface ResearchCase {
  id: Id6
  title: Title3
  input: ResearchInput
  parent_case_id: ParentCaseId
  created_at: CreatedAt6
  updated_at: UpdatedAt1
}
export interface ResearchInput {
  id: Id7
  revision: Revision6
  created_at: CreatedAt5
  question: Question
  scope: Scope
  sources: Sources1
  knowledge: Knowledge1
  depth: Depth
  report_type: ReportType
  agent_provider: AgentProvider
  model: Model
  reasoning: Reasoning
  context: Context
}
export interface Context {
  [k: string]: unknown
}
export interface ReportSummary {
  id: Id8
  revision: Revision7
  created_at: CreatedAt7
  title: Title4
  case_id: CaseId
  run_id: RunId
  input_revision: InputRevision
  change_reason: ChangeReason
}
export interface CompanyHistory {
  kind: Kind2
  ref: Ref
  title: Title5
  at: At
  case_id: CaseId1
  run_id: RunId1
  action: Action
  current_validity: CurrentValidity | null
}
