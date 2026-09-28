/* generated from schemas/calculation.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Operation = 'add' | 'subtract' | 'multiply' | 'divide' | 'ratio' | 'growth' | 'change' | 'quarterize'
export type Id1 = string
export type Revision1 = number
export type Inputs = Ref[]
export type Amount = string
export type Unit = string
export type RuleVersion = string

export interface Calculation {
  id: Id
  revision: Revision
  created_at: CreatedAt
  operation: Operation
  inputs: Inputs
  amount: Amount
  unit: Unit
  rule_version: RuleVersion
}
export interface Ref {
  id: Id1
  revision: Revision1
}
