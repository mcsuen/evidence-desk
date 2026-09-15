/* generated from schemas/research_interpretation.v3.json — do not edit */

export type Title = string
export type Intent = 'earnings' | 'report_review' | 'investigation' | 'collect'
export type ScopeType = 'company' | 'comparison' | 'industry'
export type Topic = string
export type CompanyId = string
export type Name = string
export type Mention = string
export type Role = 'target' | 'reference' | 'excluded'
export type Securities = {
  [k: string]: unknown
}[]
export type Rationale = string
export type IdentitySources = string[]
export type Verified = boolean
export type Subjects = ResearchSubject[]
export type Questions = string[]
export type Plan = string[]
export type Period = string
export type TimeDescription = string
export type AsOf = string | null
export type Clarification = string
export type Options = string[]
export type Assumptions = string[]
export type ContextAction = 'keep' | 'replace'
export type AllowPublicSearch = boolean

export interface ResearchInterpretation {
  title: Title
  intent: Intent
  scope_type: ScopeType
  topic: Topic
  subjects: Subjects
  questions: Questions
  plan: Plan
  period: Period
  time_description: TimeDescription
  as_of: AsOf
  clarification: Clarification
  options: Options
  assumptions: Assumptions
  context_action: ContextAction
  allow_public_search: AllowPublicSearch
}
export interface ResearchSubject {
  company_id: CompanyId
  name: Name
  mention: Mention
  role: Role
  securities: Securities
  rationale: Rationale
  identity_sources: IdentitySources
  verified: Verified
}
