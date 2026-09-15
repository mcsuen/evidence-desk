/* generated from schemas/desk_view.v1.json — do not edit */

export type Company = string
export type Period = string
export type Periods = string[]
export type AsOf = string
export type Snapshot = string
export type Key = string
export type Label = string
export type Group = string
export type Unit = string
export type Basis = string
export type Nature = 'flow' | 'stock' | 'ratio' | 'per_share'
export type Reviewed = boolean
export type Period1 = string
export type Value = number | null
export type ObservationIds = string[]
export type SourceId = string
export type BlockId = string
export type Quote = string
export type Citations = Citation[]
export type Calculation = string
export type Issues = string[]
export type Baseline = number | null
export type BaselineType = string
export type Difference = number | null
export type DifferencePct = number | null
export type Yoy = number | null
export type YoyBps = number | null
export type Series = Point[]
export type Checked = boolean
export type Issues1 = string[]
export type Rows = MetricRow[]
export type Id = string
export type Company1 = string
export type Title = string
export type Url = string
export type Digest = string
export type MediaType = string
export type PublishedAt = string
export type AvailableAt = string
export type ObservedAt = string
export type PublicationPrecision = 'timestamp' | 'day' | 'observed'
export type OriginGroup = string
export type Id1 = string
export type Text = string
export type Page = number | null
export type Bbox = number[] | null
export type Kind = 'paragraph' | 'table'
export type Cells = string[][]
export type Blocks = SourceBlock[]
export type Supersedes = string | null
export type WithdrawnAt = string | null
export type FileName = string
export type Issues2 = string[]
export type IdentityVersion = string
export type Documents = Document[]
export type Bridge = {
  [k: string]: unknown
}[]
export type Model = {
  [k: string]: unknown
} | null
export type Issues3 = string[]

export interface DeskView {
  company: Company
  period: Period
  periods: Periods
  as_of: AsOf
  snapshot: Snapshot
  rows: Rows
  documents: Documents
  bridge: Bridge
  model: Model
  issues: Issues3
}
export interface MetricRow {
  key: Key
  label: Label
  group: Group
  unit: Unit
  basis: Basis
  nature: Nature
  actual: Point
  prior: Point | null
  baseline: Baseline
  baseline_type: BaselineType
  difference: Difference
  difference_pct: DifferencePct
  yoy: Yoy
  yoy_bps: YoyBps
  series: Series
  checked: Checked
  issues: Issues1
}
export interface Point {
  reviewed: Reviewed
  period: Period1
  value: Value
  observation_ids: ObservationIds
  citations: Citations
  calculation: Calculation
  issues: Issues
}
export interface Citation {
  source_id: SourceId
  block_id: BlockId
  quote: Quote
}
export interface Document {
  id: Id
  company: Company1
  title: Title
  url: Url
  digest: Digest
  media_type: MediaType
  published_at: PublishedAt
  available_at: AvailableAt
  observed_at: ObservedAt
  publication_precision: PublicationPrecision
  origin_group: OriginGroup
  blocks: Blocks
  supersedes: Supersedes
  withdrawn_at: WithdrawnAt
  file_name: FileName
  issues: Issues2
  identity_version: IdentityVersion
}
export interface SourceBlock {
  id: Id1
  text: Text
  page: Page
  bbox: Bbox
  kind: Kind
  cells: Cells
}
