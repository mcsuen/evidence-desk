/* generated from schemas/lab_news_score.v1.json — do not edit */

export type Id = string
export type EventId = string
export type ArticleId = string
export type Company = string
export type ProfileId = string
export type CreatedAt = string
export type Signature = string
export type Priority = number | null
export type Queue = 'selected' | 'uncertain' | 'all'
export type Reasons = string[]
export type References = {
  [k: string]: unknown
}[]
export type Inputs = {
  [k: string]: unknown
}[]
export type Raw = {
  [k: string]: unknown
}[]
export type PolicyVersion = string
export type Calibration = string

export interface NewsScore {
  id: Id
  event_id: EventId
  article_id: ArticleId
  company: Company
  profile_id: ProfileId
  created_at: CreatedAt
  signature: Signature
  priority: Priority
  dimensions: Dimensions
  confidence: Confidence
  queue: Queue
  reasons: Reasons
  references: References
  inputs: Inputs
  raw: Raw
  model: Model
  policy_version: PolicyVersion
  calibration: Calibration
}
export interface Dimensions {
  [k: string]: number
}
export interface Confidence {
  [k: string]: number
}
export interface Model {
  [k: string]: unknown
}
