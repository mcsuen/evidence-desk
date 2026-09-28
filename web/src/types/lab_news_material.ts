/* generated from schemas/lab_news_material.v1.json — do not edit */

export type Id = string
export type Revision = number
export type Title = string
export type Url = string

export interface NewsMaterial {
  source: Ref
  title: Title
  url: Url
}
export interface Ref {
  id: Id
  revision: Revision
}
