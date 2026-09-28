/* generated from schemas/lab_news_draft_input.v1.json — do not edit */

export type OperationId = string
export type ScoreId = string
/**
 * @maxItems 10
 */
export type ArticleIds =
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

export interface NewsDraftInput {
  operation_id: OperationId
  score_id: ScoreId
  article_ids?: ArticleIds
}
