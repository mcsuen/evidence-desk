from pathlib import Path
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading

from importlib.resources import files

MANIFEST = files('pitr.integrations.slack').joinpath('manifest.yaml').read_text()
REQUIRED_SCOPES = {'chat:write', 'commands', 'im:history', 'im:read', 'im:write', 'app_mentions:read', 'files:read', 'files:write'}
SECRET_FIELDS = ('slack_app_token', 'slack_bot_token')


def validate(data):
    for key, pattern in [('slack_team_id', r'T[A-Z0-9]{5,}'), ('slack_user_id', r'[UW][A-Z0-9]{5,}')]:
        if data.get(key) and not re.fullmatch(pattern, data[key]):
            raise ValueError('Slack 工作区或本人 ID 格式不正确')
    channels = data.get('slack_channel_ids', [])
    if not isinstance(channels, list) or any(not isinstance(c, str) or not re.fullmatch(r'[CG][A-Z0-9]{5,}', c) for c in channels):
        raise ValueError('频道白名单必须是 C 或 G 开头的频道 ID 列表')
    for key, prefix in [('slack_app_token', 'xapp-'), ('slack_bot_token', 'xoxb-')]:
        if data.get(key) and not data[key].startswith(prefix):
            raise ValueError('App Token 应以 xapp- 开头，Bot Token 应以 xoxb- 开头')


class SettingsFile:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        self.lock = threading.RLock()

    def read(self):
        with self.lock:
            return json.loads(self.path.read_text()) if self.path.exists() else {}

    def save(self, values):
        with self.lock:
            data = self.read()
            # Blank secret fields retain existing credentials. Empty channel
            # lists are intentional and disable every channel surface.
            data.update({k: v for k, v in values.items() if v is not None and not (k in SECRET_FIELDS and not v)})
            validate(data)
            fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.settings-')
            try:
                with os.fdopen(fd, 'w') as output:
                    json.dump(data, output, ensure_ascii=False)
                os.replace(temporary, self.path)
                self.path.chmod(0o600)
            finally:
                Path(temporary).unlink(missing_ok=True)
            return self.public()

    def public(self):
        return {k: bool(v) if 'token' in k else v for k, v in self.read().items()}


class InstallationBusy(ValueError):
    """The previous local consumer may still be finishing its shutdown."""


class InstallationLock:
    """One network consumer per Slack installation on this OS account."""
    def __init__(self, team, bot_user):
        key = hashlib.sha256((team + ':' + bot_user).encode()).hexdigest()
        folder = Path(tempfile.gettempdir()) / ('pitr-slack-locks-' + str(os.getuid()))
        folder.mkdir(mode=0o700, exist_ok=True)
        self.path = folder / (key + '.lock')
        self.fd = None

    def acquire(self):
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise InstallationBusy('此 Slack 应用已有本机连接；等待旧连接释放后自动重试') from None
        self.fd = fd

    def release(self):
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
