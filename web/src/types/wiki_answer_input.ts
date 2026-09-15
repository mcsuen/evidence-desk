/* generated from schemas/wiki_answer_input.v1.json — do not edit */

export type OperationId = string
export type QueryId = string
export type Title = string
export type Content = string
/**
 * @minItems 1
 */
export type Used = [Reference, ...Reference[]]
export type Id = string
export type Version = number
/**
 * @minItems 1
 */
export type Citations = [Citation, ...Citation[]]
export type SourceId = string
export type BlockId = string
export type Quote = string
export type NumericAssertions = {
  [k: string]: unknown
}[]
export type SaveProposal = boolean
export type Writeback = 'topic' | 'analysis'

export interface AnswerInput {
  operation_id: OperationId
  query_id: QueryId
  title: Title
  content: Content
  used: Used
  citations: Citations
  numeric_assertions: NumericAssertions
  save_proposal: SaveProposal
  target: Reference | null
  writeback: Writeback
}
export interface Reference {
  id: Id
  version: Version
}
export interface Citation {
  source_id: SourceId
  block_id: BlockId
  quote: Quote
}
