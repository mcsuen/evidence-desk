/* generated from schemas/scope.v1.json — do not edit */

export type Subjects = string[]
export type Period = string
export type Mode = 'live' | 'historical'
export type AsOf = string | null
export type AllowPublicSearch = boolean
export type ProofLevel = 'proven' | 'declared'

export interface Scope {
  subjects: Subjects
  period: Period
  mode: Mode
  as_of: AsOf
  allow_public_search: AllowPublicSearch
  proof_level: ProofLevel
}
