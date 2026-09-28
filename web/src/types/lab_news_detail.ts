/* generated from schemas/lab_news_detail.v1.json — do not edit */

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
export type Id2 = string
export type EventId1 = string
export type SourceId = string
export type SourceName = string
export type Title1 = string
export type Url = string
export type PublishedAt = string | null
export type ObservedAt = string
export type Text = string
export type Excerpt = string
export type Digest = string
export type ContentDigest = string
export type Media = string
export type OriginalFile = string
export type PublicationSource = string
export type Issues = string[]
export type Articles = NewsArticle[]
export type Scores = NewsScore[]
export type LatestScoreId = string | null
export type Id3 = string
export type Company1 = string
export type Name = string
export type Aliases = string[]
export type Items = {
  [k: string]: unknown
}[]
export type IdentityVersion = string
export type Feedback = {
  [k: string]: unknown
}[]

export interface NewsDetail {
  event: NewsEvent
  articles: Articles
  scores: Scores
  selected: NewsScore | null
  latest_score_id: LatestScoreId
  profile: NewsProfile | null
  feedback: Feedback
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
export interface NewsArticle {
  id: Id2
  event_id: EventId1
  source_id: SourceId
  source_name: SourceName
  title: Title1
  url: Url
  published_at: PublishedAt
  observed_at: ObservedAt
  text: Text
  excerpt: Excerpt
  digest: Digest
  content_digest: ContentDigest
  media: Media
  original_file: OriginalFile
  publication_source: PublicationSource
  issues: Issues
}
export interface NewsProfile {
  id: Id3
  company: Company1
  name: Name
  aliases: Aliases
  items: Items
  identity_version: IdentityVersion
}
