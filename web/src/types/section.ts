/* generated from schemas/section.v1.json — do not edit */

export type Id = string
export type Title = string
export type Type = 'paragraph'
export type Id1 = string
export type Type1 = 'text'
export type Text = string
export type Type2 = 'value'
export type Id2 = string
export type Revision = number
export type Type3 = 'citation'
export type Inlines = (TextSpan | ValueSpan | CitationSpan)[]
export type Assertions = Ref[]
export type Type4 = 'table'
export type Id3 = string
export type Title1 = string
/**
 * @minItems 1
 * @maxItems 10
 */
export type Columns =
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
export type Rows = (TextSpan | ValueSpan | CitationSpan)[][][]
export type Note = string
export type Type5 = 'chart'
export type Id4 = string
export type Title2 = string
export type Kind = 'column' | 'line'
export type Categories = string[]
export type Name = string
export type Values = (Ref | null)[]
export type Role = 'actual' | 'forecast'
export type Series = ChartSeries[]
export type Unit = string
export type Note1 = string
export type Blocks = (Paragraph | TableBlock | ChartBlock)[]

export interface Section {
  id: Id
  title: Title
  blocks: Blocks
}
export interface Paragraph {
  type: Type
  id: Id1
  inlines: Inlines
  assertions: Assertions
}
export interface TextSpan {
  type: Type1
  text: Text
}
export interface ValueSpan {
  type: Type2
  ref: Ref
}
export interface Ref {
  id: Id2
  revision: Revision
}
export interface CitationSpan {
  type: Type3
  ref: Ref
}
export interface TableBlock {
  type: Type4
  id: Id3
  title: Title1
  columns: Columns
  rows: Rows
  note: Note
}
export interface ChartBlock {
  type: Type5
  id: Id4
  title: Title2
  kind: Kind
  categories: Categories
  series: Series
  unit: Unit
  note: Note1
}
export interface ChartSeries {
  name: Name
  values: Values
  role: Role
}
