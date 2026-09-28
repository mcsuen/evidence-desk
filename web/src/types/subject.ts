/* generated from schemas/subject.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Name = string
export type Aliases = string[]
export type OfficialDomains = string[]
export type Status = 'unverified' | 'manual' | 'verified'
export type Id1 = string
export type Revision1 = number
export type Evidence = Ref[]

export interface Subject {
  id: Id
  revision: Revision
  created_at: CreatedAt
  name: Name
  aliases: Aliases
  identifiers: Identifiers
  official_domains: OfficialDomains
  status: Status
  evidence: Evidence
}
export interface Identifiers {
  [k: string]: string
}
export interface Ref {
  id: Id1
  revision: Revision1
}
