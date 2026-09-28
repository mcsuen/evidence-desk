/* generated from schemas/value_span.v1.json — do not edit */

export type Type = 'value'
export type Id = string
export type Revision = number

export interface ValueSpan {
  type: Type
  ref: Ref
}
export interface Ref {
  id: Id
  revision: Revision
}
