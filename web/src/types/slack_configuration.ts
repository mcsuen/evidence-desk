/* generated from schemas/slack_configuration.v1.json — do not edit */

export type Enabled = boolean
export type TeamId = string
export type UserId = string
export type ChannelIds = string[]
export type AppToken = string
export type BotToken = string

export interface SlackConfiguration {
  enabled: Enabled
  team_id: TeamId
  user_id: UserId
  channel_ids: ChannelIds
  app_token: AppToken
  bot_token: BotToken
}
