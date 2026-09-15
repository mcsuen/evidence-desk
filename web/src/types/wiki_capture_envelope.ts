/* generated from schemas/wiki_capture_envelope.v1.json — do not edit */

export type OperationId = string
export type Provider = 'official' | 'claude' | 'codex' | 'slack' | 'research' | 'manual'
export type ExternalId = string
export type Company = string
export type Title = string
export type Text = string
export type SessionId = string
export type ThreadId = string
export type Url = string
export type AvailableAt = string | null
export type ObservedAt = string | null
export type RevisionOf = string | null
export type Action = 'capture' | 'revise' | 'withdraw'
export type Origin = string
export type PayloadObject = string | null
export type Attachments = string[]

export interface CaptureEnvelope {
  operation_id: OperationId
  provider: Provider
  external_id: ExternalId
  company: Company
  title: Title
  text: Text
  session_id: SessionId
  thread_id: ThreadId
  url: Url
  available_at: AvailableAt
  observed_at: ObservedAt
  revision_of: RevisionOf
  action: Action
  origin: Origin
  payload_object: PayloadObject
  attachments: Attachments
}
