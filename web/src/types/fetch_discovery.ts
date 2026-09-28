/* generated from schemas/fetch_discovery.v1.json — do not edit */

export type OperationId = string
export type DiscoveryId = string
export type Index = number

export interface FetchDiscovery {
  operation_id: OperationId
  discovery_id: DiscoveryId
  index: Index
}
