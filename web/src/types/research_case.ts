/* generated from schemas/research_case.v1.json — do not edit */

export type Id = string
export type Title = string
export type Id1 = string
export type Revision = number
export type CreatedAt = string
export type Question = string
export type Subjects = string[]
export type Period = string
export type Mode = 'live' | 'historical'
export type AsOf = string | null
export type AllowPublicSearch = boolean
export type ProofLevel = 'proven' | 'declared'
export type Id2 = string
export type Revision1 = number
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
export type CreatedAt1 = string
export type UpdatedAt = string

export interface ResearchCase {
  id: Id
  title: Title
  input: ResearchInput
  parent_case_id: ParentCaseId
  created_at: CreatedAt1
  updated_at: UpdatedAt
}
export interface ResearchInput {
  id: Id1
  revision: Revision
  created_at: CreatedAt
  question: Question
  scope: Scope
  sources: Sources
  knowledge: Knowledge
  depth: Depth
  report_type: ReportType
  agent_provider: AgentProvider
  model: Model
  reasoning: Reasoning
  context: Context
}
export interface Scope {
  subjects: Subjects
  period: Period
  mode: Mode
  as_of: AsOf
  allow_public_search: AllowPublicSearch
  proof_level: ProofLevel
}
export interface Ref {
  id: Id2
  revision: Revision1
}
export interface Context {
  [k: string]: unknown
}
