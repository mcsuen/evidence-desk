"""Authenticated, bounded Slack-hosted downloads; workflows receive references."""
from urllib.parse import urlparse
import hashlib
import json
import os
import re
import time
import httpx

from .contracts import AttachmentRef
from .store import encode

MAX_FILE_BYTES = 40_000_000
MAX_EVENT_FILES = 10


class FileRejected(ValueError):
    pass


def safe_url(url):
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.hostname != 'files.slack.com'
            or parsed.port not in (None, 443) or parsed.username or parsed.password):
        raise FileRejected('文件地址不属于允许的 Slack 下载服务')
    return url


class Attachments:
    def __init__(self, journal, settings, web_client, http_factory=None):
        self.journal = journal
        self.settings = settings
        self.web_client = web_client
        self.http_factory = http_factory or (lambda: httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False))

    def download(self, event_id, ref):
        with self.journal.connect() as db:
            existing = db.execute('SELECT body FROM attachments WHERE id=? AND event_id=?', (ref.id, event_id)).fetchone()
        if existing:
            stored = AttachmentRef.model_validate_json(existing['body'])
            if stored.status == 'ready' and (self.journal.files / stored.id).exists():
                return stored
        if not re.fullmatch(r'F[A-Z0-9]+', ref.file_id):
            raise FileRejected('文件标识不正确')
        response = self.web_client().files_info(file=ref.file_id)
        info = response['file']
        if info.get('is_external') or info.get('mode') in ('external', 'file_access'):
            raise FileRejected('仅支持 Slack 托管且当前应用可访问的文件')
        if info.get('size', 0) > MAX_FILE_BYTES:
            raise FileRejected('文件超过 40 MB 上限')
        url = safe_url(info.get('url_private_download') or info.get('url_private', ''))
        name = str(info.get('name') or ref.file_id).replace('\\', '/').split('/')[-1][:200]
        temporary = self.journal.files / (ref.id + '.part')
        size = 0
        sha = hashlib.sha256()
        started = time.monotonic()
        try:
            with self.http_factory() as client:
                # Revalidate every redirect before attaching Authorization. The
                # client has no default credentials and cannot forward them off-host.
                for hop in range(4):
                    with client.stream('GET', safe_url(url), headers={'Authorization': 'Bearer ' + self.settings()['slack_bot_token']}) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            from urllib.parse import urljoin
                            url = safe_url(urljoin(url, response.headers.get('location', '')))
                            continue
                        response.raise_for_status()
                        if int(response.headers.get('content-length', '0')) > MAX_FILE_BYTES:
                            raise FileRejected('文件超过 40 MB 上限')
                        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                        with os.fdopen(fd, 'wb') as output:
                            for chunk in response.iter_bytes():
                                if time.monotonic() - started > 30:
                                    raise FileRejected('文件下载超过 30 秒，请稍后重新发送')
                                size += len(chunk)
                                if size > MAX_FILE_BYTES:
                                    raise FileRejected('文件超过 40 MB 上限')
                                sha.update(chunk)
                                output.write(chunk)
                        break
                else:
                    raise FileRejected('文件重定向次数过多')
            result = AttachmentRef(id=ref.id, file_id=ref.file_id, name=name,
                                   media_type=info.get('mimetype', 'application/octet-stream'), size=size,
                                   sha256=sha.hexdigest(), status='ready')
            temporary.replace(self.journal.files / ref.id)
            self.save(event_id, result)
            return result
        finally:
            temporary.unlink(missing_ok=True)

    def save(self, event_id, ref):
        with self.journal.connect(write=True) as db:
            db.execute('INSERT OR REPLACE INTO attachments VALUES(?,?,?)', (ref.id, event_id, encode(ref)))

    def read(self, event_id, attachment_id):
        with self.journal.connect() as db:
            row = db.execute('SELECT body FROM attachments WHERE id=? AND event_id=?', (attachment_id, event_id)).fetchone()
        if not row or json.loads(row['body'])['status'] != 'ready':
            raise ValueError('附件不属于当前请求或尚未接收完成')
        return (self.journal.files / attachment_id).read_bytes()
