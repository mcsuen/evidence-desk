/* generated from schemas/trace_view.v1.json — do not edit */

export type Version = string
export type RunId = string
export type CaseId = string
export type Seq = number
export type LatestSeq = number
export type TaskStatus = string
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
export type Spans = TraceSpan[]
export type Id2 = string
export type Source = string
export type Target = string
export type Kind1 = 'sequence' | 'dependency' | 'repair' | 'recovery' | 'artifact'
export type Links = TraceLink[]
export type ActiveSeconds = number | null
export type QueueSeconds = number | null
export type WaitingSeconds = number | null
export type ToolSeconds = number | null
export type MeasuredTools = number
export type ToolCount1 = number
export type BudgetToolCount = number | null
export type Gaps = string[]

export interface TraceView {
  version: Version
  run_id: RunId
  case_id: CaseId
  seq: Seq
  latest_seq: LatestSeq
  task_status: TaskStatus
  spans: Spans
  links: Links
  summary: TraceSummary
}
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
export interface TraceLink {
  id: Id2
  source: Source
  target: Target
  kind: Kind1
}
export interface TraceSummary {
  active_seconds: ActiveSeconds
  queue_seconds: QueueSeconds
  waiting_seconds: WaitingSeconds
  tool_seconds: ToolSeconds
  measured_tools: MeasuredTools
  tool_count: ToolCount1
  budget_tool_count: BudgetToolCount
  tokens: Tokens
  gaps: Gaps
}
export interface Tokens {
  [k: string]: number
}
