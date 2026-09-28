/* generated from schemas/knowledge_item.v1.json — do not edit */

export type Object = Assertion | ModelRevision
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
export type Id2 = string
export type Revision2 = number
export type CreatedAt1 = string
export type Title1 = string
export type Subjects1 = string[]
export type Assumptions = Ref[]
export type Outputs = Ref[]
export type Rationale = string
export type Status = 'available' | 'needs_review' | 'withdrawn' | 'superseded'
export type Reason = string
export type UpdatedAt = string | null

export interface KnowledgeItem {
  object: Object
  current_validity: CurrentValidity
}
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
export interface ModelRevision {
  id: Id2
  revision: Revision2
  created_at: CreatedAt1
  title: Title1
  subjects: Subjects1
  assumptions: Assumptions
  outputs: Outputs
  rationale: Rationale
}
export interface CurrentValidity {
  status: Status
  reason: Reason
  updated_at: UpdatedAt
}
