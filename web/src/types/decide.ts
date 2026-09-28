/* generated from schemas/decide.v1.json — do not edit */

export type OperationId = string
export type ExpectedRevision = number
export type Action = 'adopt' | 'reject'
export type Reason = string

export interface Decide {
  operation_id: OperationId
  expected_revision: ExpectedRevision
  action: Action
  reason: Reason
}
