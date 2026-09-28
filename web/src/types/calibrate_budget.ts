/* generated from schemas/calibrate_budget.v1.json — do not edit */

export type OperationId = string
export type Depth = 'interactive' | 'standard' | 'deep'
export type Apply = boolean

export interface CalibrateBudget {
  operation_id: OperationId
  depth: Depth
  apply?: Apply
}
