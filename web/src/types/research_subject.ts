/* generated from schemas/research_subject.v3.json — do not edit */

export type CompanyId = string
export type Name = string
export type Mention = string
export type Role = 'target' | 'reference' | 'excluded'
export type Securities = {
  [k: string]: unknown
}[]
export type Rationale = string
export type IdentitySources = string[]
export type Verified = boolean

export interface ResearchSubject {
  company_id: CompanyId
  name: Name
  mention: Mention
  role: Role
  securities: Securities
  rationale: Rationale
  identity_sources: IdentitySources
  verified: Verified
}
