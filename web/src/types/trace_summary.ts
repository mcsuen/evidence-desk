/* generated from schemas/trace_summary.v1.json — do not edit */

export type ActiveSeconds = number | null
export type QueueSeconds = number | null
export type WaitingSeconds = number | null
export type ToolSeconds = number | null
export type MeasuredTools = number
export type ToolCount = number
export type BudgetToolCount = number | null
export type Gaps = string[]

export interface TraceSummary {
  active_seconds: ActiveSeconds
  queue_seconds: QueueSeconds
  waiting_seconds: WaitingSeconds
  tool_seconds: ToolSeconds
  measured_tools: MeasuredTools
  tool_count: ToolCount
  budget_tool_count: BudgetToolCount
  tokens: Tokens
  gaps: Gaps
}
export interface Tokens {
  [k: string]: number
}
