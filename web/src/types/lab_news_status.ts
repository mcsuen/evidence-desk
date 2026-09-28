/* generated from schemas/lab_news_status.v1.json — do not edit */

export type Enabled = boolean
export type CadenceMinutes = number
export type DailyLimit = number
export type Companies = string[]
export type Id = string
export type Name = string
export type Kind = 'rss' | 'disclosure' | 'gdelt'
export type Url = string
export type Enabled1 = boolean
export type Adapter = string
export type Company = string
/**
 * @maxItems 20
 */
export type Terms =
  | []
  | [string]
  | [string, string]
  | [string, string, string]
  | [string, string, string, string]
  | [string, string, string, string, string]
  | [string, string, string, string, string, string]
  | [string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [string, string, string, string, string, string, string, string, string, string, string, string, string, string]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
  | [
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string,
      string
    ]
/**
 * @maxItems 100
 */
export type Sources = NewsSource[]
export type Sources1 = {
  [k: string]: unknown
}[]
export type Runs = {
  [k: string]: unknown
}[]

export interface NewsStatus {
  settings: NewsSettings
  runtime: Runtime
  sources: Sources1
  runs: Runs
  counts: Counts
  evaluation: Evaluation
}
export interface NewsSettings {
  enabled: Enabled
  cadence_minutes: CadenceMinutes
  daily_limit: DailyLimit
  companies: Companies
  sources: Sources
}
export interface NewsSource {
  id: Id
  name: Name
  kind: Kind
  url: Url
  enabled: Enabled1
  adapter: Adapter
  company: Company
  terms: Terms
}
export interface Runtime {
  [k: string]: unknown
}
export interface Counts {
  [k: string]: number
}
export interface Evaluation {
  [k: string]: unknown
}
