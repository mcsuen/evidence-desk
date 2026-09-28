/* generated from schemas/export_request.v1.json — do not edit */

export type OperationId = string
export type Id = string
export type Revision = number
export type Paper = 'Letter' | 'A4'

export interface ExportRequest {
  operation_id: OperationId
  report: Ref
  paper?: Paper
}
export interface Ref {
  id: Id
  revision: Revision
}
