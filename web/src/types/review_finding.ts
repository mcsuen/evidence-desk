/* generated from schemas/review_finding.v1.json — do not edit */

export type Id = string
export type Revision = number
export type Severity = 'error' | 'limitation' | 'note'
export type Message = string
export type Evidence = Ref[]
export type Correction = string

export interface ReviewFinding {
  target: Ref | null
  severity: Severity
  message: Message
  evidence: Evidence
  correction: Correction
}
export interface Ref {
  id: Id
  revision: Revision
}
