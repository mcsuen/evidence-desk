/* generated from schemas/update_input.v1.json — do not edit */

export type OperationId = string
export type Question = string
export type Subjects = string[]
export type Period = string
export type Mode = 'live' | 'historical'
export type AsOf = string | null
export type AllowPublicSearch = boolean
export type ProofLevel = 'proven' | 'declared'
export type Id = string
export type Revision = number
/**
 * @maxItems 40
 */
export type Sources = Ref[]
export type Knowledge = Ref[]
export type Depth = 'interactive' | 'standard' | 'deep'
export type ReportType = 'memo' | 'earnings' | 'company' | 'industry'
export type AgentProvider = ('codex' | 'claude') | null
export type Model = string | null
export type Reasoning = string
export type ParentCaseId = string | null
export type NewsDraftId = string | null
export type ExpectedRevision = number

export interface UpdateInput {
  operation_id: OperationId
  question: Question
  scope?: Scope
  sources?: Sources
  knowledge?: Knowledge
  depth?: Depth
  report_type?: ReportType
  agent_provider?: AgentProvider
  model?: Model
  reasoning?: Reasoning
  parent_case_id?: ParentCaseId
  news_draft_id?: NewsDraftId
  expected_revision: ExpectedRevision
}
export interface Scope {
  subjects?: Subjects
  period?: Period
  mode?: Mode
  as_of?: AsOf
  allow_public_search?: AllowPublicSearch
  proof_level?: ProofLevel
}
export interface Ref {
  id: Id
  revision: Revision
}
