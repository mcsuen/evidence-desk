/* generated from schemas/lab_news_research_draft.v1.json — do not edit */

export type Id = string
export type Company = string
export type Question = string
export type EventId = string
export type ScoreId = string
export type ProfileId = string
export type CreatedAt = string
export type Id1 = string
export type Revision = number
export type Title = string
export type Url = string
export type Materials = NewsMaterial[]
export type Knowledge = Ref[]

export interface NewsResearchDraft {
  id: Id
  company: Company
  question: Question
  event_id: EventId
  score_id: ScoreId
  profile_id: ProfileId
  created_at: CreatedAt
  materials: Materials
  knowledge: Knowledge
  context: Context
}
export interface NewsMaterial {
  source: Ref
  title: Title
  url: Url
}
export interface Ref {
  id: Id1
  revision: Revision
}
export interface Context {
  [k: string]: unknown
}
