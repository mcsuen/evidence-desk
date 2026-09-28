/* generated from schemas/settings_command.v1.json — do not edit */

export type OperationId = string
export type AgentProvider = ('codex' | 'claude') | null
export type AgentModels = {
  [k: string]: string | null
} | null
export type SecUserAgent = string | null
export type Enabled = boolean
export type TeamId = string
export type UserId = string
export type ChannelIds = string[]
export type AppToken = string
export type BotToken = string

export interface SettingsCommand {
  operation_id: OperationId
  agent_provider?: AgentProvider
  agent_models?: AgentModels
  sec_user_agent?: SecUserAgent
  slack?: SlackConfiguration | null
}
export interface SlackConfiguration {
  enabled: Enabled
  team_id: TeamId
  user_id: UserId
  channel_ids: ChannelIds
  app_token?: AppToken
  bot_token?: BotToken
}
