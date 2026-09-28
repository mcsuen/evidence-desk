/* generated from schemas/budget.v1.json — do not edit */

export type PolicyVersion = string
export type ActiveSeconds = number
export type ToolCalls = number
export type ReserveFraction = number
export type Calibration = string

export interface Budget {
  policy_version: PolicyVersion
  active_seconds: ActiveSeconds
  tool_calls: ToolCalls
  reserve_fraction: ReserveFraction
  calibration: Calibration
}
