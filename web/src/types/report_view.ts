/* generated from schemas/report_view.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type CaseId = string
export type RunId = string
export type InputRevision = number
export type Id1 = string
export type Revision1 = number
export type Title = string
export type ReportType = 'memo' | 'earnings' | 'company' | 'industry'
export type Type = 'paragraph'
export type Id2 = string
export type Type1 = 'text'
export type Text = string
export type Type2 = 'value'
export type Type3 = 'citation'
export type Inlines = (TextSpan | ValueSpan | CitationSpan)[]
export type Assertions = Ref[]
export type Summary = Paragraph[]
export type Id3 = string
export type Title1 = string
export type Type4 = 'table'
export type Id4 = string
export type Title2 = string
/**
 * @minItems 1
 * @maxItems 10
 */
export type Columns =
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
export type Rows = (TextSpan | ValueSpan | CitationSpan)[][][]
export type Note = string
export type Type5 = 'chart'
export type Id5 = string
export type Title3 = string
export type Kind = 'column' | 'line'
export type Categories = string[]
export type Name = string
export type Values = (Ref | null)[]
export type Role = 'actual' | 'forecast'
export type Series = ChartSeries[]
export type Unit = string
export type Note1 = string
export type Blocks = (Paragraph | TableBlock | ChartBlock)[]
export type Sections = Section[]
export type Gaps = string[]
export type NextSteps = string[]
export type Assertions1 = Ref[]
export type Models = Ref[]
export type Skills = {
  [k: string]: unknown
}[]
export type ChangeReason = string
export type Delivery = 'draft' | 'partial' | 'ready'
export type Id6 = string
export type Revision2 = number
export type CreatedAt1 = string
export type Name1 = string
export type Status = 'not_run' | 'passed' | 'failed' | 'unavailable' | 'skipped' | 'error' | 'not_applicable'
export type Coverage = string[]
export type Findings = {
  [k: string]: unknown
}[]
export type Limitations = string[]
export type PolicyVersion = string
export type Checks = CheckResult[]
export type Id7 = string
export type Revision3 = number
export type CreatedAt2 = string
export type Kind1 = 'observed' | 'assumption' | 'derived'
export type Metric = string
export type Amount = string
export type Unit1 = string
export type Subject = string
export type Period = string
export type Basis = string
export type Frequency = 'quarter' | 'annual' | 'ytd' | 'point'
export type Currency = string
export type ShareBasis = string
export type Role1 = 'actual' | 'guidance' | 'broker_forecast' | 'consensus' | 'assumption' | 'derived'
export type Precision = number
export type Dependencies = Ref[]
export type Reason = string
export type Limitations1 = string[]
export type Values1 = Value[]
export type Id8 = string
export type Revision4 = number
export type CreatedAt3 = string
export type BlockId = string
export type Start = number
export type End = number
export type Quote = string
export type Page = number | null
export type Bbox = number[]
export type Evidence = EvidenceAnchor[]
export type Id9 = string
export type Revision5 = number
export type CreatedAt4 = string
export type Title4 = string
export type Url = string
export type MediaType = string
export type Digest = string
export type ByteCount = number
export type Subjects = string[]
export type Id10 = string
export type Text1 = string
export type Page1 = number | null
export type Bbox1 = number[]
export type Blocks1 = SourceBlock[]
export type PageCount = number
export type PublishedAt = string | null
export type AvailableAt = string
export type ObservedAt = string
export type AvailabilityBasis = 'acquired' | 'authoritative' | 'archive' | 'declared'
export type AvailabilityEvidence = string
export type OriginGroup = string
export type SourceRole = 'official' | 'third_party' | 'upload'
export type Issues = string[]
export type Sources = SourceVersion[]
export type Id11 = string
export type Revision6 = number
export type CreatedAt5 = string
export type Title5 = string
export type Statement = string
export type Kind2 = 'source_statement' | 'fact' | 'interpretation' | 'forecast' | 'relationship'
export type Subjects1 = string[]
export type Support = Ref[]
export type Counterevidence = Ref[]
export type Values2 = Ref[]
export type DependsOn = Ref[]
export type Alternative = string
export type Limitations2 = string[]
export type NextCheck = string
export type Assertions2 = Assertion[]
export type Id12 = string
export type Signature = string
export type Status1 = 'queued' | 'running' | 'completed' | 'failed'
export type Paper = 'Letter' | 'A4'
export type TemplateVersion = string
export type CheckRefs = Ref[]
export type DeliveryAtRequest = 'ready' | 'partial' | 'draft'
export type Error = string
export type Attempts = number
export type CreatedAt6 = string
export type UpdatedAt = string
export type Exports = ExportJob[]

export interface ReportView {
  document: ReportDocument
  delivery: Delivery
  checks: Checks
  current_validity: CurrentValidity
  values: Values1
  value_labels: ValueLabels
  evidence: Evidence
  sources: Sources
  assertions: Assertions2
  exports: Exports
}
export interface ReportDocument {
  id: Id
  revision: Revision
  created_at: CreatedAt
  case_id: CaseId
  run_id: RunId
  input_revision: InputRevision
  snapshot: Ref
  title: Title
  report_type: ReportType
  summary: Summary
  sections: Sections
  gaps: Gaps
  next_steps: NextSteps
  assertions: Assertions1
  models: Models
  skills: Skills
  change_reason: ChangeReason
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface Paragraph {
  type: Type
  id: Id2
  inlines: Inlines
  assertions: Assertions
}
export interface TextSpan {
  type: Type1
  text: Text
}
export interface ValueSpan {
  type: Type2
  ref: Ref
}
export interface CitationSpan {
  type: Type3
  ref: Ref
}
export interface Section {
  id: Id3
  title: Title1
  blocks: Blocks
}
export interface TableBlock {
  type: Type4
  id: Id4
  title: Title2
  columns: Columns
  rows: Rows
  note: Note
}
export interface ChartBlock {
  type: Type5
  id: Id5
  title: Title3
  kind: Kind
  categories: Categories
  series: Series
  unit: Unit
  note: Note1
}
export interface ChartSeries {
  name: Name
  values: Values
  role: Role
}
export interface CheckResult {
  id: Id6
  revision: Revision2
  created_at: CreatedAt1
  target: Ref
  name: Name1
  status: Status
  coverage: Coverage
  findings: Findings
  limitations: Limitations
  policy_version: PolicyVersion
}
export interface CurrentValidity {
  [k: string]: unknown
}
export interface Value {
  id: Id7
  revision: Revision3
  created_at: CreatedAt2
  kind: Kind1
  metric: Metric
  amount: Amount
  unit: Unit1
  subject: Subject
  period: Period
  basis: Basis
  frequency: Frequency
  currency: Currency
  share_basis: ShareBasis
  role: Role1
  precision: Precision
  observation: Ref | null
  calculation: Ref | null
  dependencies: Dependencies
  reason: Reason
  limitations: Limitations1
}
export interface ValueLabels {
  [k: string]: string
}
export interface EvidenceAnchor {
  id: Id8
  revision: Revision4
  created_at: CreatedAt3
  source: Ref
  block_id: BlockId
  start: Start
  end: End
  quote: Quote
  page: Page
  bbox: Bbox
}
export interface SourceVersion {
  id: Id9
  revision: Revision5
  created_at: CreatedAt4
  title: Title4
  url: Url
  media_type: MediaType
  digest: Digest
  byte_count: ByteCount
  subjects: Subjects
  blocks: Blocks1
  page_count: PageCount
  published_at: PublishedAt
  available_at: AvailableAt
  observed_at: ObservedAt
  availability_basis: AvailabilityBasis
  availability_evidence: AvailabilityEvidence
  origin_group: OriginGroup
  source_role: SourceRole
  issues: Issues
}
export interface SourceBlock {
  id: Id10
  text: Text1
  page: Page1
  bbox: Bbox1
}
export interface Assertion {
  id: Id11
  revision: Revision6
  created_at: CreatedAt5
  title: Title5
  statement: Statement
  kind: Kind2
  subjects: Subjects1
  support: Support
  counterevidence: Counterevidence
  values: Values2
  depends_on: DependsOn
  alternative: Alternative
  limitations: Limitations2
  next_check: NextCheck
  relation: Relation
}
export interface Relation {
  [k: string]: unknown
}
export interface ExportJob {
  id: Id12
  report: Ref
  signature: Signature
  status: Status1
  paper: Paper
  template_version: TemplateVersion
  check_refs: CheckRefs
  delivery_at_request: DeliveryAtRequest
  artifact: Ref | null
  error: Error
  attempts: Attempts
  created_at: CreatedAt6
  updated_at: UpdatedAt
}
