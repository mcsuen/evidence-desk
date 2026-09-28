/* generated from schemas/human_evaluation.v1.json — do not edit */

export type OperationId = string
export type BlindId = string
export type Annotator = string
export type EditEffort = 'none' | 'light' | 'heavy' | 'unusable'
export type MajorError = boolean
export type EditingMinutes = number
export type Comments = string

export interface HumanEvaluation {
  operation_id: OperationId
  blind_id: BlindId
  annotator: Annotator
  edit_effort: EditEffort
  major_error: MajorError
  editing_minutes: EditingMinutes
  comments?: Comments
}
