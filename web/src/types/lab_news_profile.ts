/* generated from schemas/lab_news_profile.v1.json — do not edit */

export type Id = string
export type Company = string
export type Name = string
export type Aliases = string[]
export type Items = {
  [k: string]: unknown
}[]
export type IdentityVersion = string

export interface NewsProfile {
  id: Id
  company: Company
  name: Name
  aliases: Aliases
  items: Items
  identity_version: IdentityVersion
}
