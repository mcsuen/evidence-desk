/* generated from schemas/wiki_wiki_job_result.v1.json — do not edit */

export type JobId = string
export type ExecutionStatus = string
export type PublicationStatus = string
export type Materials = {
  [k: string]: unknown
}[]
export type Coverage = {
  [k: string]: unknown
}[]
export type Checks = {
  [k: string]: unknown
}[]
export type Failures = {
  [k: string]: unknown
}[]
export type Skipped = {
  [k: string]: unknown
}[]
export type ProposalId = string | null
export type PreviousFailures = {
  [k: string]: unknown
}[]
export type CatalogChecks = {
  [k: string]: unknown
}[]
export type CatalogExcluded = {
  [k: string]: unknown
}[]
export type ResumedFrom = string | null

export interface WikiJobResult {
  job_id: JobId
  execution_status: ExecutionStatus
  publication_status: PublicationStatus
  materials: Materials
  coverage: Coverage
  checks: Checks
  failures: Failures
  skipped: Skipped
  proposal_id: ProposalId
  previous_failures: PreviousFailures
  supplemental_discovery: SupplementalDiscovery
  catalog_checks: CatalogChecks
  catalog_excluded: CatalogExcluded
  resumed_from: ResumedFrom
}
export interface SupplementalDiscovery {
  [k: string]: unknown
}
