/* generated from schemas/wiki_inspection_run.v1.json — do not edit */

export type Id = string
export type Kind = 'rules' | 'semantic'
export type Company = string
export type Id1 = string
export type Version = number
export type StartedAt = string
export type FinishedAt = string | null
export type Scope = string[]
export type Skipped = {
  [k: string]: string
}[]
export type Failures = {
  [k: string]: string
}[]
export type Issues = string[]
export type BudgetSeconds = number
export type BudgetExhausted = boolean
export type ModelOutputs = string[]
export type ElapsedSeconds = number | null
export type Feedback = {
  [k: string]: unknown
} | null

export interface InspectionRun {
  id: Id
  kind: Kind
  company: Company
  policy: Reference
  started_at: StartedAt
  finished_at: FinishedAt
  scope: Scope
  skipped: Skipped
  failures: Failures
  issues: Issues
  budget_seconds: BudgetSeconds
  budget_exhausted: BudgetExhausted
  model_outputs: ModelOutputs
  elapsed_seconds: ElapsedSeconds
  feedback: Feedback
}
export interface Reference {
  id: Id1
  version: Version
}
