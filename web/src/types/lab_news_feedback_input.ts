/* generated from schemas/lab_news_feedback_input.v1.json — do not edit */

export type OperationId = string
export type ScoreId = string
export type Verdict = 'useful' | 'irrelevant' | 'duplicate' | 'raise' | 'important' | 'not_important'
export type Note = string

export interface NewsFeedbackInput {
  operation_id: OperationId
  score_id: ScoreId
  verdict: Verdict
  note?: Note
}
