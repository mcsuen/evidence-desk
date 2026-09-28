/* generated from schemas/subscription_command.v1.json — do not edit */

export type OperationId = string
export type Id = string | null
export type ExpectedRevision = number
export type Subject = string
export type Url = string
export type Enabled = boolean
export type IntervalHours = number

export interface SubscriptionCommand {
  operation_id: OperationId
  id?: Id
  expected_revision?: ExpectedRevision
  subject: Subject
  url: Url
  enabled?: Enabled
  interval_hours?: IntervalHours
}
