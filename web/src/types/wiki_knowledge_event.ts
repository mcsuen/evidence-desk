/* generated from schemas/wiki_knowledge_event.v1.json — do not edit */

export type Sequence = number
export type Id = string
export type Company = string
export type Kind = string
export type OccurredAt = string
export type PayloadObject = string

export interface KnowledgeEvent {
  sequence: Sequence
  id: Id
  company: Company
  kind: Kind
  occurred_at: OccurredAt
  payload_object: PayloadObject
}
