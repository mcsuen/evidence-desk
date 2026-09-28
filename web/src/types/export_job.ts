/* generated from schemas/export_job.v1.json — do not edit */

export type Id = string
export type Id1 = string
export type Revision = number
export type Signature = string
export type Status = 'queued' | 'running' | 'completed' | 'failed'
export type Paper = 'Letter' | 'A4'
export type TemplateVersion = string
export type CheckRefs = Ref[]
export type DeliveryAtRequest = 'ready' | 'partial' | 'draft'
export type Error = string
export type Attempts = number
export type CreatedAt = string
export type UpdatedAt = string

export interface ExportJob {
  id: Id
  report: Ref
  signature: Signature
  status: Status
  paper: Paper
  template_version: TemplateVersion
  check_refs: CheckRefs
  delivery_at_request: DeliveryAtRequest
  artifact: Ref | null
  error: Error
  attempts: Attempts
  created_at: CreatedAt
  updated_at: UpdatedAt
}
export interface Ref {
  id: Id1
  revision: Revision
}
