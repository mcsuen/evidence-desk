/* generated from schemas/research_message.v3.json — do not edit */

export type OperationId = string
export type Text = string
/**
 * @maxItems 10
 */
export type SourceIds =
  | []
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
export type ExpectedInputVersion = number
export type Company = string
export type Intent = ('earnings' | 'report_review' | 'investigation' | 'collect') | null
export type AsOf = string | null
export type ReleaseContext = boolean

export interface ResearchMessage {
  operation_id: OperationId
  text: Text
  source_ids: SourceIds
  expected_input_version: ExpectedInputVersion
  company: Company
  intent: Intent
  as_of: AsOf
  release_context: ReleaseContext
}
