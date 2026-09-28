/* generated from schemas/agent_answer.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type CaseId = string
export type RunId = string
export type InputRevision = number
export type Id1 = string
export type Revision1 = number
export type Title = string
export type ReportType = 'memo' | 'earnings' | 'company' | 'industry'
export type Type = 'paragraph'
export type Id2 = string
export type Type1 = 'text'
export type Text = string
export type Type2 = 'value'
export type Type3 = 'citation'
export type Inlines = (TextSpan | ValueSpan | CitationSpan)[]
export type Assertions = Ref[]
export type Summary = Paragraph[]
export type Id3 = string
export type Title1 = string
export type Type4 = 'table'
export type Id4 = string
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
export type Id5 = string
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
export type Assertions1 = Ref[]
export type Models = Ref[]
export type Skills = {
  [k: string]: unknown
}[]
export type ChangeReason = string
export type Questions = string[]
export type Findings = string

export interface AgentAnswer {
  report: ReportDocument | null
  questions: Questions
  findings: Findings
}
export interface ReportDocument {
  id: Id
  revision: Revision
  created_at: CreatedAt
  case_id: CaseId
  run_id: RunId
  input_revision: InputRevision
  snapshot: Ref
  title: Title
  report_type: ReportType
  summary: Summary
  sections: Sections
  gaps: Gaps
  next_steps: NextSteps
  assertions: Assertions1
  models: Models
  skills: Skills
  change_reason: ChangeReason
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface Paragraph {
  type: Type
  id: Id2
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
export interface CitationSpan {
  type: Type3
  ref: Ref
}
export interface Section {
  id: Id3
  title: Title1
  blocks: Blocks
}
export interface TableBlock {
  type: Type4
  id: Id4
  title: Title2
  columns: Columns
  rows: Rows
  note: Note
}
export interface ChartBlock {
  type: Type5
  id: Id5
  title: Title3
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
