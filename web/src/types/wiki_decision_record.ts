/* generated from schemas/wiki_decision_record.v1.json — do not edit */

export type OperationId = string
export type Digest = string
export type Action = 'adopt' | 'reject'
export type Reason = string
export type Alternatives = string
export type Consequences = string
export type ReviewerIdentity = string

export interface DecisionRecord {
  operation_id: OperationId
  digest: Digest
  action: Action
  reason: Reason
  alternatives: Alternatives
  consequences: Consequences
  reviewer_identity: ReviewerIdentity
}
