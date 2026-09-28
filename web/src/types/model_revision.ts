/* generated from schemas/model_revision.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Title = string
export type Subjects = string[]
export type Id1 = string
export type Revision1 = number
export type Assumptions = Ref[]
export type Outputs = Ref[]
export type Rationale = string

export interface ModelRevision {
  id: Id
  revision: Revision
  created_at: CreatedAt
  title: Title
  subjects: Subjects
  assumptions: Assumptions
  outputs: Outputs
  rationale: Rationale
}
export interface Ref {
  id: Id1
  revision: Revision1
}
