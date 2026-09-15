/* generated from schemas/wiki_query_input.v1.json — do not edit */

export type OperationId = string
export type Company = string
export type Question = string
export type AsOf = string | null
export type Hybrid = boolean
/**
 * @maxItems 20
 */
export type ContextRefs =
  | []
  | [Reference]
  | [Reference, Reference]
  | [Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference, Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference, Reference, Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference, Reference, Reference, Reference, Reference, Reference]
  | [Reference, Reference, Reference, Reference, Reference, Reference, Reference, Reference, Reference, Reference]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
  | [
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference,
      Reference
    ]
export type Id = string
export type Version = number

export interface QueryInput {
  operation_id: OperationId
  company: Company
  question: Question
  as_of: AsOf
  hybrid: Hybrid
  context_refs: ContextRefs
}
export interface Reference {
  id: Id
  version: Version
}
