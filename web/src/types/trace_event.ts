/* generated from schemas/trace_event.v1.json — do not edit */

export type Seq = number
export type At = string
export type Kind = string

export interface TraceEvent {
  seq: Seq
  at: At
  kind: Kind
  data: Data
}
export interface Data {
  [k: string]: unknown
}
