/* generated from schemas/wiki_proposal_input.v1.json — do not edit */

export type OperationId = string
export type Company = string
export type Id = string
export type Version = number
/**
 * @minItems 1
 * @maxItems 50
 */
export type Changes = [RevisionDraft, ...RevisionDraft[]]
export type Id1 = string
export type Kind = 'knowledge' | 'page' | 'policy'
export type ExpectedVersion = number
export type Title = string
export type Content = string
export type Summary = string
export type PageType = ('source' | 'company' | 'concept' | 'topic' | 'analysis') | null
export type Nature = ('fact' | 'interpretation' | 'method') | null
export type Scope = string
export type BusinessPeriod = string
export type Applicability = string
export type Formula = string
export type FailureCases = string
export type Example = string
export type SourceId = string
export type BlockId = string
export type Quote = string
export type Citations = Citation[]
export type Relation1 = 'supports' | 'derived_from' | 'used_in' | 'related'
export type Paragraph = string
export type Relations = Relation[]
export type NumericAssertions = {
  [k: string]: unknown
}[]
export type Reason = string
export type ChangeType = 'new' | 'supplement' | 'conflict' | 'scope' | 'correction'
export type Inputs = Reference[]
export type Reason1 = string
export type Origin = 'human' | 'agent' | 'ingest' | 'query' | 'inspection' | 'research'
export type Replaces = string | null
export type IssueIds = string[]
export type AsOf = string | null
export type ModelOutput = string | null

export interface ProposalInput {
  operation_id: OperationId
  company: Company
  policy: Reference
  changes: Changes
  inputs: Inputs
  reason: Reason1
  origin: Origin
  replaces: Replaces
  issue_ids: IssueIds
  as_of: AsOf
  model_output: ModelOutput
}
export interface Reference {
  id: Id
  version: Version
}
export interface RevisionDraft {
  id: Id1
  kind: Kind
  expected_version: ExpectedVersion
  title: Title
  content: Content
  summary: Summary
  page_type: PageType
  nature: Nature
  scope: Scope
  business_period: BusinessPeriod
  applicability: Applicability
  formula: Formula
  failure_cases: FailureCases
  example: Example
  citations: Citations
  relations: Relations
  numeric_assertions: NumericAssertions
  corrects: Reference | null
  reason: Reason
  change_type: ChangeType
}
export interface Citation {
  source_id: SourceId
  block_id: BlockId
  quote: Quote
}
export interface Relation {
  target: Reference
  relation: Relation1
  paragraph: Paragraph
}
