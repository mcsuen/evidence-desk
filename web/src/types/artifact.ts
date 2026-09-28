/* generated from schemas/artifact.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Id1 = string
export type Revision1 = number
export type Format = 'docx'
export type Digest = string
export type TemplateVersion = string
export type CompilerVersion = string
export type Paper = 'Letter' | 'A4'

export interface Artifact {
  id: Id
  revision: Revision
  created_at: CreatedAt
  report: Ref
  format: Format
  digest: Digest
  template_version: TemplateVersion
  compiler_version: CompilerVersion
  paper: Paper
  manifest: Manifest
}
export interface Ref {
  id: Id1
  revision: Revision1
}
export interface Manifest {
  [k: string]: unknown
}
