/* generated from schemas/chart_block.v1.json — do not edit */

export type Type = 'chart'
export type Id = string
export type Title = string
export type Kind = 'column' | 'line'
export type Categories = string[]
export type Name = string
export type Id1 = string
export type Revision = number
export type Values = (Ref | null)[]
export type Role = 'actual' | 'forecast'
export type Series = ChartSeries[]
export type Unit = string
export type Note = string

export interface ChartBlock {
  type: Type
  id: Id
  title: Title
  kind: Kind
  categories: Categories
  series: Series
  unit: Unit
  note: Note
}
export interface ChartSeries {
  name: Name
  values: Values
  role: Role
}
export interface Ref {
  id: Id1
  revision: Revision
}
