/* generated from schemas/report_summary.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Title = string
export type CaseId = string
export type RunId = string
export type InputRevision = number
export type ChangeReason = string

export interface ReportSummary {
  id: Id
  revision: Revision
  created_at: CreatedAt
  title: Title
  case_id: CaseId
  run_id: RunId
  input_revision: InputRevision
  change_reason: ChangeReason
}
