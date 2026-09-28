/* generated from schemas/source_block.v1.json — do not edit */

export type Id = string
export type Text = string
export type Page = number | null
export type Bbox = number[]

export interface SourceBlock {
  id: Id
  text: Text
  page: Page
  bbox: Bbox
}
