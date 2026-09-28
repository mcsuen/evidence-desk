/* generated from schemas/blind_pack.v1.json — do not edit */

export type OperationId = string
/**
 * @minItems 1
 * @maxItems 60
 */
export type Reports = [Ref, ...Ref[]]
export type Id = string
export type Revision = number

export interface BlindPack {
  operation_id: OperationId
  reports: Reports
}
export interface Ref {
  id: Id
  revision: Revision
}
