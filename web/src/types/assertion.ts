/* generated from schemas/assertion.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Title = string
export type Statement = string
export type Kind = 'source_statement' | 'fact' | 'interpretation' | 'forecast' | 'relationship'
export type Subjects = string[]
export type Id1 = string
export type Revision1 = number
export type Support = Ref[]
export type Counterevidence = Ref[]
export type Values = Ref[]
export type DependsOn = Ref[]
export type Alternative = string
export type Limitations = string[]
export type NextCheck = string

export interface Assertion {
  id: Id
  revision: Revision
  created_at: CreatedAt
  title: Title
  statement: Statement
  kind: Kind
  subjects: Subjects
  support: Support
  counterevidence: Counterevidence
  values: Values
  depends_on: DependsOn
  alternative: Alternative
  limitations: Limitations
  next_check: NextCheck
  relation: Relation
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface Relation {
  [k: string]: unknown
}
