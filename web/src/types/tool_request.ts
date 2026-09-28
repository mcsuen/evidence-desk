/* generated from schemas/tool_request.v1.json — do not edit */

export type OperationId = string
export type Name = string

export interface ToolRequest {
  operation_id: OperationId
  name: Name
  arguments?: Arguments
}
export interface Arguments {
  [k: string]: unknown
}
