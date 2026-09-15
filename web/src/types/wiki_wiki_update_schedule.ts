/* generated from schemas/wiki_wiki_update_schedule.v1.json — do not edit */

export type OperationId = string
export type Company = string
export type Enabled = boolean
export type Frequency = 'daily' | 'weekly' | 'custom'
/**
 * @minItems 1
 * @maxItems 7
 */
export type Weekdays =
  | [number]
  | [number, number]
  | [number, number, number]
  | [number, number, number, number]
  | [number, number, number, number, number]
  | [number, number, number, number, number, number]
  | [number, number, number, number, number, number, number]
export type LocalTime = string
export type Timezone = string
export type ResearchFocus = string
export type BudgetSeconds = number
export type NotificationEventId = string

export interface WikiUpdateSchedule {
  operation_id: OperationId
  company: Company
  enabled: Enabled
  frequency: Frequency
  weekdays: Weekdays
  local_time: LocalTime
  timezone: Timezone
  research_focus: ResearchFocus
  budget_seconds: BudgetSeconds
  notification_event_id: NotificationEventId
}
