/* generated from schemas/review_decision.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type GroupId = string
export type Id1 = string
export type Revision1 = number
export type Targets = Ref[]
export type Action = 'adopt' | 'reject'
export type Reason = string
export type Actor = 'local_owner'

export interface ReviewDecision {
  id: Id
  revision: Revision
  created_at: CreatedAt
  group_id: GroupId
  targets: Targets
  action: Action
  reason: Reason
  actor: Actor
}
export interface Ref {
  id: Id1
  revision: Revision1
}
