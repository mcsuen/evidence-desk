/* generated from schemas/run.v1.json — do not edit */

export type Id = string
export type CaseId = string
export type InputRevision = number
export type Id1 = string
export type Revision = number
export type Status = 'queued' | 'running' | 'waiting_user' | 'budget_exhausted' | 'completed' | 'cancelled' | 'failed'
export type Stage = string
export type Generation = number
export type Lane = 'codex' | 'claude' | 'local'
export type PolicyVersion = string
export type ActiveSeconds = number
export type ToolCalls = number
export type ReserveFraction = number
export type Calibration = string
export type ActiveSeconds1 = number
export type ToolCalls1 = number
export type Cost = number | null
export type Error = string
export type Questions = string[]
export type CreatedAt = string
export type UpdatedAt = string

export interface Run {
  id: Id
  case_id: CaseId
  input_revision: InputRevision
  snapshot: Ref
  status: Status
  stage: Stage
  generation: Generation
  agent: Agent
  lane: Lane
  budget: Budget
  active_seconds: ActiveSeconds1
  tool_calls: ToolCalls1
  cost: Cost
  checkpoint: Checkpoint
  report: Ref | null
  error: Error
  questions: Questions
  created_at: CreatedAt
  updated_at: UpdatedAt
}
export interface Ref {
  id: Id1
  revision: Revision
}
export interface Agent {
  [k: string]: unknown
}
export interface Budget {
  policy_version: PolicyVersion
  active_seconds: ActiveSeconds
  tool_calls: ToolCalls
  reserve_fraction: ReserveFraction
  calibration: Calibration
}
export interface Checkpoint {
  [k: string]: unknown
}
