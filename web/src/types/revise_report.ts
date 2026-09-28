/* generated from schemas/revise_report.v1.json — do not edit */

export type OperationId = string
export type ExpectedRevision = number
export type Title = string
export type Type = 'paragraph'
export type Id = string
export type Type1 = 'text'
export type Text = string
export type Type2 = 'value'
export type Id1 = string
export type Revision = number
export type Type3 = 'citation'
export type Inlines = (TextSpan | ValueSpan | CitationSpan)[]
export type Assertions = Ref[]
export type Summary = Paragraph[]
export type Id2 = string
export type Title1 = string
export type Type4 = 'table'
export type Id3 = string
export type Title2 = string
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
export type Title3 = string
export type Kind = 'column' | 'line'
export type Categories = string[]
export type Name = string
export type Values = (Ref | null)[]
export type Role = 'actual' | 'forecast'
export type Series = ChartSeries[]
export type Unit = string
export type Note1 = string
export type Blocks = (Paragraph | TableBlock | ChartBlock)[]
export type Sections = Section[]
export type Gaps = string[]
export type NextSteps = string[]
export type Reason = string

export interface ReviseReport {
  operation_id: OperationId
  expected_revision: ExpectedRevision
  title: Title
  summary: Summary
  sections: Sections
  gaps: Gaps
  next_steps: NextSteps
  reason: Reason
}
export interface Paragraph {
  type?: Type
  id: Id
  inlines: Inlines
  assertions?: Assertions
}
export interface TextSpan {
  type?: Type1
  text: Text
}
export interface ValueSpan {
  type?: Type2
  ref: Ref
}
export interface Ref {
  id: Id1
  revision: Revision
}
export interface CitationSpan {
  type?: Type3
  ref: Ref
}
export interface Section {
  id: Id2
  title: Title1
  blocks: Blocks
}
export interface TableBlock {
  type?: Type4
  id: Id3
  title: Title2
  columns: Columns
  rows: Rows
  note?: Note
}
export interface ChartBlock {
  type?: Type5
  id: Id4
  title: Title3
  kind: Kind
  categories: Categories
  series: Series
  unit: Unit
  note?: Note1
}
export interface ChartSeries {
  name: Name
  values: Values
  role?: Role
}
