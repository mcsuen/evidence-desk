/* generated from schemas/wiki_knowledge_issue.v1.json — do not edit */

export type OperationId = string
export type Id = string
export type Version = number
export type Paragraph = string
export type IssueType =
  'citation' | 'object' | 'numeric' | 'calculation' | 'semantic' | 'conflict' | 'scope' | 'gap' | 'structure'
export type Description = string
export type SourceId = string
export type BlockId = string
export type Quote = string
export type Evidence = Citation[]
export type DiscoveredBy = 'human' | 'agent' | 'slack' | 'rule' | 'semantic'
export type Id1 = string
export type State = 'open' | 'closed'
export type ContentResolution = string
export type Company = string
export type CreatedAt = string
export type ConfirmedHardError = boolean
export type ReproducedFailures = {
  [k: string]: string
}[]
export type UpdatedAt = string | null
export type Decisions = {
  [k: string]: unknown
}[]
export type Reports = {
  [k: string]: unknown
}[]

export interface KnowledgeIssue {
  operation_id: OperationId
  target: Reference
  paragraph: Paragraph
  issue_type: IssueType
  description: Description
  evidence: Evidence
  discovered_by: DiscoveredBy
  id: Id1
  state: State
  impacts: Impacts
  content_resolution: ContentResolution
  company: Company
  created_at: CreatedAt
  policy: Reference
  confirmed_hard_error: ConfirmedHardError
  reproduced_failures: ReproducedFailures
  previous_status: PreviousStatus
  updated_at: UpdatedAt
  decisions: Decisions
  reports: Reports
}
export interface Reference {
  id: Id
  version: Version
}
export interface Citation {
  source_id: SourceId
  block_id: BlockId
  quote: Quote
}
export interface Impacts {
  [k: string]: unknown
}
export interface PreviousStatus {
  [k: string]: unknown
}
