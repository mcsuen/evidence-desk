/* generated from schemas/check_result.v1.json — do not edit */

export type Id = string
export type Revision = number
export type CreatedAt = string
export type Id1 = string
export type Revision1 = number
export type Name = string
export type Status = 'not_run' | 'passed' | 'failed' | 'unavailable' | 'skipped' | 'error' | 'not_applicable'
export type Coverage = string[]
export type Findings = {
  [k: string]: unknown
}[]
export type Limitations = string[]
export type PolicyVersion = string

export interface CheckResult {
  id: Id
  revision: Revision
  created_at: CreatedAt
  target: Ref
  name: Name
  status: Status
  coverage: Coverage
  findings: Findings
  limitations: Limitations
  policy_version: PolicyVersion
}
export interface Ref {
  id: Id1
  revision: Revision1
}
