"""Explicit child-process credentials. Data-provider and Slack secrets never reach investigators."""
import os

_BASE = {'PATH', 'HOME', 'USER', 'TMPDIR', 'LANG', 'LC_ALL', 'SSL_CERT_FILE', 'SSL_CERT_DIR', 'SYSTEMROOT'}
_MODEL = {'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'OPENAI_BASE_URL'}

def child_env(*, model: bool = False) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in (_BASE | (_MODEL if model else set()))}
