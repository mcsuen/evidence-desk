/* generated from schemas/continue_run.v1.json — do not edit */

export type OperationId = string
export type ExpectedGeneration = number
export type AdditionalSeconds = number
export type AdditionalCalls = number
export type Instruction = string

export interface ContinueRun {
  operation_id: OperationId
  expected_generation: ExpectedGeneration
  additional_seconds?: AdditionalSeconds
  additional_calls?: AdditionalCalls
  instruction?: Instruction
}
