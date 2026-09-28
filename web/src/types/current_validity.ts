/* generated from schemas/current_validity.v1.json — do not edit */

export type Status = 'available' | 'needs_review' | 'withdrawn' | 'superseded'
export type Reason = string
export type UpdatedAt = string | null

export interface CurrentValidity {
  status: Status
  reason: Reason
  updated_at: UpdatedAt
}
