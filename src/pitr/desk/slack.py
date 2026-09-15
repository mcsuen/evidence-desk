"""Current application composition for the reusable Slack runtime."""
from pitr.integrations.slack.runtime import SlackRuntime
from .slack_adapter import DeskAdapter


class Slack(SlackRuntime):
    def __init__(self, desk, queue, settings, save_settings=None, **kwargs):
        super().__init__(desk.root / 'integrations' / 'slack', settings, save_settings, **kwargs)
        self.register(DeskAdapter(desk, queue), default=True)
