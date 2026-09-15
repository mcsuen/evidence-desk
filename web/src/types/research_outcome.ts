/* generated from schemas/research_outcome.v3.json — do not edit */

export type ArtifactVersion = number | null
export type SchemaVersion = 3
export type Title = string
export type RequestId = string
export type InputVersion = number
export type Snapshot = string
export type AsOf = string
export type Intent = string
export type Claims = {
  [k: string]: unknown
}[]
export type Id = string
export type SourceId = string
export type SourceVersion = string
export type BlockId = string
export type Start = number
export type End = number
export type Quote = string
export type AvailableAt = string
export type Origin = string
export type Page = number | null
export type Title1 = string
export type Url = string
export type SourceRole = string
export type OriginGroup = string
export type PublishedAt = string
export type ObservedAt = string
export type PublicationPrecision = string
export type ModifiedAt = string
export type PublicationNote = string
export type OriginalUrl = string
export type ReportedDate = string
export type Bbox = number[]
export type CompanyId = string
export type Evidence = EvidenceRef[]
export type Id1 = string
export type Metric = string
export type Value = number | null
export type Unit = string
export type Currency = string
export type Basis = string
export type ShareBasis = string
export type Period = string
export type Frequency = string
export type Direction = ('increase' | 'decrease' | 'unchanged') | null
export type Precision = number
export type Formula = string
export type Dependencies = string[]
export type Assumption = boolean
export type Limitations = string[]
export type SourceRoles = string[]
export type VerificationStatus = string
export type CompanyId1 = string
export type SubjectIds = string[]
export type Calculations = CalculationRef[]
export type Metrics = {
  [k: string]: unknown
}[]
export type Key = string
export type Status = 'answered' | 'gap' | 'missing' | 'invalid'
export type ClaimIds = string[]
export type Explanation = string
export type Coverage = CoverageCheck[]
export type Gaps = string[]
export type Issues = {
  [k: string]: unknown
}[]
export type Status1 = 'review_ready' | 'partial' | 'needs_review'
export type Handoffs = {
  [k: string]: unknown
}[]
export type HumanReview = string
export type Id2 = string
export type Question = string
export type SourceId1 = string
export type Pages = number[]
export type Kind = 'question' | 'table' | 'figure' | 'model' | 'temporal'
export type Reason = string
export type Check =
  | 'answer'
  | 'consensus_comparison_ratios'
  | 'forecast_revision_ratios'
  | 'valuation_price_reconciliation'
  | 'consensus_profit_reconciliation'
  | 'segment_revenue_reconciliation'
  | 'public_investigation'
export type Name = string
/**
 * Equivalent explicit terms for this concept; at least one must appear in the linked report claims, not only in the coverage self-assessment.
 *
 * @minItems 1
 */
export type Terms = [string, ...string[]]
export type RequiredConcepts = RequiredConcept[]
export type RequiredMetrics = string[]
export type RequiredPeriods = string[]
export type Metric1 = string
export type Period1 = string
export type Basis1 = string
export type RequiredComparisons = RequiredComparison[]
export type Requirements = Requirement[]
export type RequirementId = string
export type Status2 = 'answered' | 'gap' | 'pending'
export type ClaimIds1 = string[]
export type Explanation1 = string
export type CheckReceipts = string[]
export type NeededInput = string
export type RequirementResolutions = RequirementResolution[]
export type Reviews = {
  [k: string]: unknown
}[]
export type Reading = {
  [k: string]: unknown
}[]
export type CompanyId2 = string
export type Name1 = string
export type Mention = string
export type Role = 'target' | 'reference' | 'excluded'
export type Securities = {
  [k: string]: unknown
}[]
export type Rationale = string
export type IdentitySources = string[]
export type Verified = boolean
export type Subjects = ResearchSubject[]
export type ScopeType = string
export type KeyClaimIds = string[]
export type Sections = {
  [k: string]: unknown
}[]
export type Comparisons = {
  [k: string]: unknown
}[]

export interface ResearchOutcome {
  artifact_version: ArtifactVersion
  schema_version: SchemaVersion
  title: Title
  request_id: RequestId
  input_version: InputVersion
  snapshot: Snapshot
  as_of: AsOf
  intent: Intent
  claims: Claims
  evidence: Evidence
  calculations: Calculations
  metrics: Metrics
  coverage: Coverage
  gaps: Gaps
  issues: Issues
  status: Status1
  verification: Verification
  handoffs: Handoffs
  human_review: HumanReview
  requirements: Requirements
  requirement_resolutions: RequirementResolutions
  reviews: Reviews
  reading: Reading
  delivery: Delivery
  subjects: Subjects
  scope_type: ScopeType
  key_claim_ids: KeyClaimIds
  sections: Sections
  comparisons: Comparisons
}
export interface EvidenceRef {
  id: Id
  source_id: SourceId
  source_version: SourceVersion
  block_id: BlockId
  start: Start
  end: End
  quote: Quote
  available_at: AvailableAt
  origin: Origin
  page: Page
  title: Title1
  url: Url
  source_role: SourceRole
  origin_group: OriginGroup
  published_at: PublishedAt
  observed_at: ObservedAt
  publication_precision: PublicationPrecision
  modified_at: ModifiedAt
  publication_note: PublicationNote
  original_url: OriginalUrl
  reported_date: ReportedDate
  bbox: Bbox
  company_id: CompanyId
}
export interface CalculationRef {
  id: Id1
  metric: Metric
  value: Value
  unit: Unit
  currency: Currency
  basis: Basis
  share_basis: ShareBasis
  period: Period
  frequency: Frequency
  direction: Direction
  precision: Precision
  formula: Formula
  dependencies: Dependencies
  assumption: Assumption
  limitations: Limitations
  source_roles: SourceRoles
  verification_status: VerificationStatus
  source_locator: SourceLocator
  company_id: CompanyId1
  subject_ids: SubjectIds
}
export interface SourceLocator {
  [k: string]: unknown
}
export interface CoverageCheck {
  key: Key
  status: Status
  claim_ids: ClaimIds
  explanation: Explanation
}
export interface Verification {
  [k: string]: unknown
}
export interface Requirement {
  id: Id2
  question: Question
  source_id: SourceId1
  pages: Pages
  kind: Kind
  reason: Reason
  check: Check
  required_concepts: RequiredConcepts
  required_metrics: RequiredMetrics
  required_periods: RequiredPeriods
  required_comparisons: RequiredComparisons
}
export interface RequiredConcept {
  name: Name
  terms: Terms
}
export interface RequiredComparison {
  metric: Metric1
  period: Period1
  basis: Basis1
}
export interface RequirementResolution {
  requirement_id: RequirementId
  status: Status2
  claim_ids: ClaimIds1
  explanation: Explanation1
  check_receipts: CheckReceipts
  needed_input: NeededInput
}
export interface Delivery {
  [k: string]: unknown
}
export interface ResearchSubject {
  company_id: CompanyId2
  name: Name1
  mention: Mention
  role: Role
  securities: Securities
  rationale: Rationale
  identity_sources: IdentitySources
  verified: Verified
}
