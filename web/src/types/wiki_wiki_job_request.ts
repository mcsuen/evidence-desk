/* generated from schemas/wiki_wiki_job_request.v1.json — do not edit */

export type OperationId = string
export type AgentProvider = ('codex' | 'claude') | null
export type Model = string | null
export type Intent = 'build' | 'update'
export type Company = string
export type ResearchFocus = string
export type SourcePolicy = 'official_industry_media'
export type AsOf = string | null
export type Years = number
export type Quarters = number
export type BudgetSeconds = number
export type MaxDocuments = number
export type Channel = 'web' | 'slack' | 'cli' | 'schedule'
/**
 * @maxItems 40
 */
export type SeedUrls = string[]
/**
 * @maxItems 40
 */
export type SourceIds = string[]
export type ResumeJobId = string | null

export interface WikiJobRequest {
  operation_id: OperationId
  agent_provider: AgentProvider
  model: Model
  intent: Intent
  company: Company
  research_focus: ResearchFocus
  source_policy: SourcePolicy
  as_of: AsOf
  years: Years
  quarters: Quarters
  budget_seconds: BudgetSeconds
  max_documents: MaxDocuments
  channel: Channel
  seed_urls: SeedUrls
  source_ids: SourceIds
  resume_job_id: ResumeJobId
}
