/* generated from schemas/operating_model.v1.json — do not edit */

export type Engine = 'pdd-operating.1'
export type Snapshot = string
export type AnchorPeriod = string
export type Parameter = string
export type Period = string
export type Value = number | null
export type Reason = string
export type Provenance = 'user' | 'mechanical_reference'
export type SourceId = string
export type BlockId = string
export type Quote = string
export type Citations = Citation[]
export type Assumptions = Assumption[]
export type Scenario = string
export type InvestigationId = string | null
export type Company = string
export type AsOf = string
export type HistoryPeriods = string[]
export type ForecastPeriods = string[]
export type Parameters = {
  [k: string]: unknown
}[]
export type Outputs = {
  [k: string]: unknown
}[]
export type Key = string
export type Period1 = string
export type Value1 = number | null
export type Kind = 'actual' | 'forecast' | 'mixed'
export type Formula = string
export type Dependencies = string[]
export type Missing = string[]
export type Citations1 = Citation[]
export type Cells = ModelCell[]
export type Annual = ModelCell[]
export type Checks = {
  [k: string]: unknown
}[]
export type References = Assumption[]
export type Published = {
  [k: string]: unknown
} | null
export type Issues = string[]

export interface ModelView {
  spec: ModelSpec
  company: Company
  as_of: AsOf
  history_periods: HistoryPeriods
  forecast_periods: ForecastPeriods
  parameters: Parameters
  outputs: Outputs
  cells: Cells
  annual: Annual
  checks: Checks
  references: References
  published: Published
  issues: Issues
}
export interface ModelSpec {
  engine: Engine
  snapshot: Snapshot
  anchor_period: AnchorPeriod
  assumptions: Assumptions
  scenario: Scenario
  investigation_id: InvestigationId
}
export interface Assumption {
  parameter: Parameter
  period: Period
  value: Value
  reason: Reason
  provenance: Provenance
  citations: Citations
}
export interface Citation {
  source_id: SourceId
  block_id: BlockId
  quote: Quote
}
export interface ModelCell {
  key: Key
  period: Period1
  value: Value1
  kind: Kind
  formula: Formula
  dependencies: Dependencies
  missing: Missing
  citations: Citations1
}
