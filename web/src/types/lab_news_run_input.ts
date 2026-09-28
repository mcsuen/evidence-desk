/* generated from schemas/lab_news_run_input.v1.json — do not edit */

export type OperationId = string
export type Kind = 'collect' | 'rescore' | 'install'

export interface NewsRunInput {
  operation_id: OperationId
  kind?: Kind
}
