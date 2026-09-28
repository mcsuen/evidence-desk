/* generated from schemas/company_value.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Kind = 'observed' | 'assumption' | 'derived'
export type Metric = string
export type Amount = string
export type Unit = string
export type Subject = string
export type Period = string
export type Basis = string
export type Frequency = 'quarter' | 'annual' | 'ytd' | 'point'
export type Currency = string
export type ShareBasis = string
export type Role = 'actual' | 'guidance' | 'broker_forecast' | 'consensus' | 'assumption' | 'derived'
export type Precision = number
export type Id1 = string
export type Revision1 = number
export type Dependencies = Ref[]
export type Reason = string
export type Limitations = string[]
export type Status = 'available' | 'needs_review' | 'withdrawn' | 'superseded'
export type Reason1 = string
export type UpdatedAt = string | null

export interface CompanyValue {
  object: Value
  current_validity: CurrentValidity
}
export interface Value {
  id: Id
  revision: Revision
  created_at: CreatedAt
  kind: Kind
  metric: Metric
  amount: Amount
  unit: Unit
  subject: Subject
  period: Period
  basis: Basis
  frequency: Frequency
  currency: Currency
  share_basis: ShareBasis
  role: Role
  precision: Precision
  observation: Ref | null
  calculation: Ref | null
  dependencies: Dependencies
  reason: Reason
  limitations: Limitations
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface CurrentValidity {
  status: Status
  reason: Reason1
  updated_at: UpdatedAt
}
