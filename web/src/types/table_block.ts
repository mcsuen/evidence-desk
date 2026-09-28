/* generated from schemas/table_block.v1.json — do not edit */

export type Type = 'table'
export type Id = string
export type Title = string
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
export type Type1 = 'text'
export type Text = string
export type Type2 = 'value'
export type Id1 = string
export type Revision = number
export type Type3 = 'citation'
export type Rows = (TextSpan | ValueSpan | CitationSpan)[][][]
export type Note = string

export interface TableBlock {
  type: Type
  id: Id
  title: Title
  columns: Columns
  rows: Rows
  note: Note
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
  id: Id1
  revision: Revision
}
export interface CitationSpan {
  type: Type3
  ref: Ref
}
