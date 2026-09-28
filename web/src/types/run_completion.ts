/* generated from schemas/run_completion.v1.json — do not edit */

export type Id = string
export type Revision = number
export type Questions = string[]
export type Findings = string

export interface RunCompletion {
  report: Ref | null
  questions: Questions
  findings: Findings
}
export interface Ref {
  id: Id
  revision: Revision
}
