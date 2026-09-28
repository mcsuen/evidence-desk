/* generated from schemas/chart_series.v1.json — do not edit */

export type Name = string
export type Id = string
export type Revision = number
export type Values = (Ref | null)[]
export type Role = 'actual' | 'forecast'

export interface ChartSeries {
  name: Name
  values: Values
  role: Role
}
export interface Ref {
  id: Id
  revision: Revision
}
