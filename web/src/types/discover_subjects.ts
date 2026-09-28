/* generated from schemas/discover_subjects.v1.json — do not edit */

export type OperationId = string
export type Name = string
export type Market = 'SEC' | 'HKEX' | 'SSE' | 'SZSE' | 'BSE' | 'CNINFO'
export type Code = string

export interface DiscoverSubjects {
  operation_id: OperationId
  name: Name
  market: Market
  code?: Code
}
