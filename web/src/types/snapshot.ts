/* generated from schemas/snapshot.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Subjects = string[]
export type Period = string
export type Mode = 'live' | 'historical'
export type AsOf = string | null
export type AllowPublicSearch = boolean
export type ProofLevel = 'proven' | 'declared'
export type Id1 = string
export type Revision1 = number
export type Sources = Ref[]
export type Knowledge = Ref[]
export type Reused = Ref[]
export type SubjectVersions = Ref[]

export interface Snapshot {
  id: Id
  revision: Revision
  created_at: CreatedAt
  scope: Scope
  sources: Sources
  knowledge: Knowledge
  reused: Reused
  subject_versions: SubjectVersions
}
export interface Scope {
  subjects: Subjects
  period: Period
  mode: Mode
  as_of: AsOf
  allow_public_search: AllowPublicSearch
  proof_level: ProofLevel
}
export interface Ref {
  id: Id1
  revision: Revision1
}
