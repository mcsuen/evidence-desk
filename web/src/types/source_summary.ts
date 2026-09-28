/* generated from schemas/source_summary.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Title = string
export type Url = string
export type MediaType = string
export type Subjects = string[]
export type SourceRole = 'official' | 'third_party' | 'upload'
export type AvailableAt = string
export type PublishedAt = string | null

export interface SourceSummary {
  id: Id
  revision: Revision
  created_at: CreatedAt
  title: Title
  url: Url
  media_type: MediaType
  subjects: Subjects
  source_role: SourceRole
  available_at: AvailableAt
  published_at: PublishedAt
}
