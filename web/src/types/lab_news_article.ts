/* generated from schemas/lab_news_article.v1.json — do not edit */

export type Id = string
export type EventId = string
export type SourceId = string
export type SourceName = string
export type Title = string
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

export interface NewsArticle {
  id: Id
  event_id: EventId
  source_id: SourceId
  source_name: SourceName
  title: Title
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
