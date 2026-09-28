/* generated from schemas/independent_review.v1.json — do not edit */

export type Verdict = 'pass' | 'revise' | 'blocked'
export type Id = string
export type Revision = number
export type Severity = 'error' | 'limitation' | 'note'
export type Message = string
export type Evidence = Ref[]
export type Correction = string
export type Findings = ReviewFinding[]
export type CheckedAssertions = Ref[]
export type Evidence1 = Ref[]
export type Summary = string

export interface IndependentReview {
  verdict: Verdict
  findings: Findings
  checked_assertions: CheckedAssertions
  evidence: Evidence1
  summary: Summary
}
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
