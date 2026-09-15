/* generated from schemas/wiki_knowledge_revision.v1.json — do not edit */

export type Id = string
export type Kind = 'knowledge'
export type ExpectedVersion = number
export type Title = string
export type Content = string
export type Summary = string
export type PageType = ('source' | 'company' | 'concept' | 'topic' | 'analysis') | null
export type Nature = 'fact' | 'interpretation' | 'method'
export type Scope = string
export type BusinessPeriod = string
export type Applicability = string
export type Formula = string
export type FailureCases = string
export type Example = string
export type SourceId = string
export type BlockId = string
export type Quote = string
export type Citations = Citation[]
export type Id1 = string
export type Version = number
export type Relation1 = 'supports' | 'derived_from' | 'used_in' | 'related'
export type Paragraph = string
export type Relations = Relation[]
export type NumericAssertions = {
  [k: string]: unknown
}[]
export type Reason = string
export type ChangeType = 'new' | 'supplement' | 'conflict' | 'scope' | 'correction'
export type Version1 = number
export type Company = string
export type PublishedAt = string
export type PublicationSequence = number
export type ProposalId = string | null
export type ReviewStatus = string
export type BodyObject = string
export type Decision = {
  [k: string]: unknown
} | null
export type Id2 = string
export type Name = string
export type Label = string
export type Period = string
export type Value = number
export type Unit = string
export type Basis = 'GAAP' | 'non-GAAP' | 'disclosed'
export type Frequency = 'quarter' | 'annual' | 'ytd' | 'instant'
export type Status = 'extracted' | 'checked' | 'corrected'
export type CorrectionReason = string
export type EvidenceObservations = Metric[]
export type Origin = string

export interface KnowledgeRevision {
  id: Id
  kind: Kind
  expected_version: ExpectedVersion
  title: Title
  content: Content
  summary: Summary
  page_type: PageType
  nature: Nature
  scope: Scope
  business_period: BusinessPeriod
  applicability: Applicability
  formula: Formula
  failure_cases: FailureCases
  example: Example
  citations: Citations
  relations: Relations
  numeric_assertions: NumericAssertions
  corrects: Reference | null
  reason: Reason
  change_type: ChangeType
  version: Version1
  company: Company
  published_at: PublishedAt
  publication_sequence: PublicationSequence
  policy: Reference | null
  proposal_id: ProposalId
  review_status: ReviewStatus
  body_object: BodyObject
  decision: Decision
  evidence_observations: EvidenceObservations
  origin: Origin
}
export interface Citation {
  source_id: SourceId
  block_id: BlockId
  quote: Quote
}
export interface Relation {
  target: Reference
  relation: Relation1
  paragraph: Paragraph
}
export interface Reference {
  id: Id1
  version: Version
}
export interface Metric {
  id: Id2
  name: Name
  label: Label
  period: Period
  value: Value
  unit: Unit
  basis: Basis
  frequency: Frequency
  citation: Citation
  status: Status
  correction_reason: CorrectionReason
}
