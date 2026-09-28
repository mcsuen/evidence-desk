/* generated from schemas/source_version.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Title = string
export type Url = string
export type MediaType = string
export type Digest = string
export type ByteCount = number
export type Subjects = string[]
export type Id1 = string
export type Text = string
export type Page = number | null
export type Bbox = number[]
export type Blocks = SourceBlock[]
export type PageCount = number
export type PublishedAt = string | null
export type AvailableAt = string
export type ObservedAt = string
export type AvailabilityBasis = 'acquired' | 'authoritative' | 'archive' | 'declared'
export type AvailabilityEvidence = string
export type OriginGroup = string
export type SourceRole = 'official' | 'third_party' | 'upload'
export type Issues = string[]

export interface SourceVersion {
  id: Id
  revision: Revision
  created_at: CreatedAt
  title: Title
  url: Url
  media_type: MediaType
  digest: Digest
  byte_count: ByteCount
  subjects: Subjects
  blocks: Blocks
  page_count: PageCount
  published_at: PublishedAt
  available_at: AvailableAt
  observed_at: ObservedAt
  availability_basis: AvailabilityBasis
  availability_evidence: AvailabilityEvidence
  origin_group: OriginGroup
  source_role: SourceRole
  issues: Issues
}
export interface SourceBlock {
  id: Id1
  text: Text
  page: Page
  bbox: Bbox
}
