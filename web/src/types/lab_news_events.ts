/* generated from schemas/lab_news_events.v1.json — do not edit */

export type Id = string
export type Title = string
export type FirstSeen = string
export type UpdatedAt = string
export type ArticleCount = number
export type Id1 = string
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
export type Companies = string[]
export type Items = NewsEvent[]
export type Total = number
export type Offset = number

export interface NewsEvents {
  items: Items
  total: Total
  counts: Counts
  offset: Offset
}
export interface NewsEvent {
  id: Id
  title: Title
  first_seen: FirstSeen
  updated_at: UpdatedAt
  article_count: ArticleCount
  score: NewsScore | null
  companies: Companies
}
export interface NewsScore {
  id: Id1
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
export interface Counts {
  [k: string]: number
}
