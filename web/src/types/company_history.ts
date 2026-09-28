/* generated from schemas/company_history.v1.json — do not edit */

export type Kind = 'source' | 'report' | 'decision'
export type Id = string
export type Revision = number
export type Title = string
export type At = string
export type CaseId = string | null
export type RunId = string | null
export type Action = string | null
export type Status = 'available' | 'needs_review' | 'withdrawn' | 'superseded'
export type Reason = string
export type UpdatedAt = string | null

export interface CompanyHistory {
  kind: Kind
  ref: Ref
  title: Title
  at: At
  case_id: CaseId
  run_id: RunId
  action: Action
  current_validity: CurrentValidity | null
}
export interface Ref {
  id: Id
  revision: Revision
}
export interface CurrentValidity {
  status: Status
  reason: Reason
  updated_at: UpdatedAt
}
