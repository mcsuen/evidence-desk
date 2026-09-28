/* generated from schemas/fetch_source.v1.json — do not edit */

export type OperationId = string
export type Url = string
export type Title = string
export type Subjects = string[]

export interface FetchSource {
  operation_id: OperationId
  url: Url
  title?: Title
  subjects?: Subjects
}
