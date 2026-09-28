/* generated from schemas/discover_sources.v1.json — do not edit */

export type OperationId = string
export type Subject = string
export type Adapter = string
export type Since = string
export type Until = string
export type Urls = string[]

export interface DiscoverSources {
  operation_id: OperationId
  subject: Subject
  adapter: Adapter
  since?: Since
  until?: Until
  urls?: Urls
}
