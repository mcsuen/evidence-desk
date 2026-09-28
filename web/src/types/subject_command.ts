/* generated from schemas/subject_command.v1.json — do not edit */

export type OperationId = string
export type Identity = string
export type Name = string
export type Aliases = string[]
export type OfficialDomains = string[]
export type ExpectedRevision = number
export type Id = string
export type Revision = number
export type Evidence = Ref[]

export interface SubjectCommand {
  operation_id: OperationId
  identity: Identity
  name: Name
  aliases?: Aliases
  official_domains?: OfficialDomains
  identifiers?: Identifiers
  expected_revision?: ExpectedRevision
  evidence?: Evidence
}
export interface Identifiers {
  [k: string]: string
}
export interface Ref {
  id: Id
  revision: Revision
}
