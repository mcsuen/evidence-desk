/* generated from schemas/citation_span.v1.json — do not edit */

export type Type = 'citation'
export type Id = string
export type Revision = number

export interface CitationSpan {
  type: Type
  ref: Ref
}
export interface Ref {
  id: Id
  revision: Revision
}
