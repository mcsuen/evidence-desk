/* generated from schemas/trace_span.v1.json — do not edit */

export type Id = string
export type ParentId = string | null
export type Name = string
export type Kind = string
export type Executor = string
export type Status = string
export type StartedAt = string | null
export type EndedAt = string | null
export type DurationMs = number | null
export type Timing = 'measured' | 'observed' | 'missing'
export type Attempt = number | null
export type Generation = number
export type Ordinal = number | null
export type InputVersion = number | null
export type Id1 = string
export type Revision = number
export type ArtifactRefs = Ref[]
export type ToolCount = number
export type IssueCount = number
export type FirstSeq = number
export type LastSeq = number

export interface TraceSpan {
  id: Id
  parent_id: ParentId
  name: Name
  kind: Kind
  executor: Executor
  status: Status
  started_at: StartedAt
  ended_at: EndedAt
  duration_ms: DurationMs
  timing: Timing
  attempt: Attempt
  generation: Generation
  ordinal: Ordinal
  input_version: InputVersion
  artifact_refs: ArtifactRefs
  tool_count: ToolCount
  issue_count: IssueCount
  first_seq: FirstSeq
  last_seq: LastSeq
  metadata: Metadata
}
export interface Ref {
  id: Id1
  revision: Revision
}
export interface Metadata {
  [k: string]: unknown
}
