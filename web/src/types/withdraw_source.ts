/* generated from schemas/withdraw_source.v1.json — do not edit */

export type OperationId = string
export type ExpectedRevision = number
export type Reason = string

export interface WithdrawSource {
  operation_id: OperationId
  expected_revision: ExpectedRevision
  reason: Reason
}
