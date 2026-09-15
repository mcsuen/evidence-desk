/* generated from schemas/trace_view.v1.json — do not edit */

export type Version = string
export type RequestId = string
export type TaskId = string
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
export type CallId = string | null
export type Ordinal = number | null
export type InputVersion = number | null
export type InputRef = string | null
export type OutputRef = string | null
export type ErrorRef = string | null
export type ArtifactRefs = {
  [k: string]: unknown
}[]
export type ToolCount = number
export type IssueCount = number
export type FirstSeq = number
export type LastSeq = number
export type Spans = TraceSpan[]
export type Id1 = string
export type Source = string
export type Target = string
export type Kind1 = 'sequence' | 'dependency' | 'repair' | 'recovery' | 'artifact'
export type Label = string
export type Links = TraceLink[]
export type Plans = {
  [k: string]: unknown
}[]
export type ActiveSeconds = number | null
export type QueueSeconds = number | null
export type WaitingSeconds = number | null
export type ToolSeconds = number | null
export type MeasuredTools = number
export type ToolCount1 = number
export type BudgetToolCount = number | null
export type Cost = number | null
export type Capture = string
export type Gaps = string[]
export type Reconstructed = boolean

export interface TraceView {
  version: Version
  request_id: RequestId
  task_id: TaskId
  seq: Seq
  latest_seq: LatestSeq
  task_status: TaskStatus
  spans: Spans
  links: Links
  plans: Plans
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
  call_id: CallId
  ordinal: Ordinal
  input_version: InputVersion
  input_ref: InputRef
  output_ref: OutputRef
  error_ref: ErrorRef
  artifact_refs: ArtifactRefs
  tool_count: ToolCount
  issue_count: IssueCount
  first_seq: FirstSeq
  last_seq: LastSeq
  metadata: Metadata
}
export interface Metadata {
  [k: string]: unknown
}
export interface TraceLink {
  id: Id1
  source: Source
  target: Target
  kind: Kind1
  label: Label
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
  cost: Cost
  capture: Capture
  gaps: Gaps
  reconstructed: Reconstructed
  sync: Sync
}
export interface Tokens {
  [k: string]: number
}
export interface Sync {
  [k: string]: unknown
}
