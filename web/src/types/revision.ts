/* generated from schemas/revision.v1.json — do not edit */

export type Id = string
export type Revision1 = number
export type CreatedAt = string

export interface Revision {
  id: Id
  revision: Revision1
  created_at: CreatedAt
}
