/* generated from schemas/evidence_anchor.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Id1 = string
export type Revision1 = number
export type BlockId = string
export type Start = number
export type End = number
export type Quote = string
export type Page = number | null
export type Bbox = number[]

export interface EvidenceAnchor {
  id: Id
  revision: Revision
  created_at: CreatedAt
  source: Ref
  block_id: BlockId
  start: Start
  end: End
  quote: Quote
  page: Page
  bbox: Bbox
}
export interface Ref {
  id: Id1
  revision: Revision1
}
