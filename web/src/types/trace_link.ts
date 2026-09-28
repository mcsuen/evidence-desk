/* generated from schemas/trace_link.v1.json — do not edit */

export type Id = string
export type Source = string
export type Target = string
export type Kind = 'sequence' | 'dependency' | 'repair' | 'recovery' | 'artifact'

export interface TraceLink {
  id: Id
  source: Source
  target: Target
  kind: Kind
}
