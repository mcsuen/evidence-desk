/* generated from schemas/review_group.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Title = string
/**
 * @minItems 1
 */
export type Targets = [Ref, ...Ref[]]
export type Id1 = string
export type Revision1 = number
export type Reason = string

export interface ReviewGroup {
  id: Id
  revision: Revision
  created_at: CreatedAt
  title: Title
  targets: Targets
  expected_heads: ExpectedHeads
  report: Ref | null
  reason: Reason
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface ExpectedHeads {
  [k: string]: number
}
