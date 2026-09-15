/* generated from schemas/research_request.v3.json — do not edit */

export type OperationId = string
export type Question = string
export type Company = string
export type Period = string
export type Intent = 'auto' | 'earnings' | 'report_review' | 'investigation'
export type AsOf = string | null
export type Snapshot = string
export type ModelDraftId = string
/**
 * @maxItems 10
 */
export type SourceIds =
  | []
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
/**
 * @maxItems 10
 */
export type OfficialUrls =
  | []
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
export type Channel = 'web' | 'slack' | 'cli' | 'context'
export type ParentRequestId = string
export type WorkflowVersion = 3
export type ContextSource = 'none' | 'explicit' | 'workspace' | 'passive'
export type BudgetSeconds = number | null
export type ToolBudget = number | null
export type AgentProvider = ('codex' | 'claude') | null
export type Model = string | null
export type Reasoning = 'low' | 'medium' | 'high' | 'xhigh'

export interface ResearchRequest {
  operation_id: OperationId
  question: Question
  company: Company
  period: Period
  intent: Intent
  as_of: AsOf
  snapshot: Snapshot
  model_draft_id: ModelDraftId
  context: Context
  source_ids: SourceIds
  official_urls: OfficialUrls
  channel: Channel
  parent_request_id: ParentRequestId
  workflow_version: WorkflowVersion
  scope: Scope
  context_source: ContextSource
  budget_seconds: BudgetSeconds
  tool_budget: ToolBudget
  agent_provider: AgentProvider
  model: Model
  reasoning: Reasoning
}
export interface Context {
  [k: string]: unknown
}
export interface Scope {
  [k: string]: unknown
}
