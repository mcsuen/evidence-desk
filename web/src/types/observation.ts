/* generated from schemas/observation.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Id1 = string
export type Revision1 = number
export type Literal = string
export type Start = number
export type Metric = string
export type Subject = string
export type Period = string
export type OriginalUnit = string
export type Role = 'actual' | 'guidance' | 'broker_forecast' | 'consensus' | 'assumption'
export type Basis = string
export type Frequency = 'quarter' | 'annual' | 'ytd' | 'point'

export interface Observation {
  id: Id
  revision: Revision
  created_at: CreatedAt
  evidence: Ref
  literal: Literal
  start: Start
  metric: Metric
  subject: Subject
  period: Period
  original_unit: OriginalUnit
  role: Role
  basis: Basis
  frequency: Frequency
  table: Table
  unit_evidence: Ref
  period_evidence: Ref
  basis_evidence: Ref
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface Table {
  [k: string]: unknown
}
