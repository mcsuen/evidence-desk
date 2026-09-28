/* generated from schemas/paragraph.v1.json — do not edit */

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

export interface Paragraph {
  type: Type
  id: Id
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
  id: Id1
  revision: Revision
}
export interface CitationSpan {
  type: Type3
  ref: Ref
}
