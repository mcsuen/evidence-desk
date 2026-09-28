"""Archived snapshots (Wayback Machine CDX). The snapshot capture time is archived availability proof."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
from .protocol import Item, register

CDX = 'https://web.archive.org/cdx/search/cdx'


def snapshot_time(stamp):
    return datetime.strptime(stamp, '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc).isoformat()


class ArchiveSnapshot:
    name = 'ARCHIVE'
    channel = 'media'
    markets = ()
    proof = 'archived_snapshot'

    def find_candidates(self, subject, acquire):
        return []

    def list_items(self, candidate, acquire, *, since='', until='', types=(), urls=(), terms=()):
        """Latest 200-status capture of each URL at or before `until` (and after `since`)."""
        items = []
        for url in urls:
            params = {'url': url, 'output': 'json', 'filter': 'statuscode:200', 'limit': '-20', 'fl': 'timestamp,original,digest'}
            if until: params['to'] = until[:10].replace('-', '')
            if since: params['from'] = since[:10].replace('-', '')
            raw = acquire(CDX + '?' + urlencode(params))[0]
            rows = json.loads(raw.decode('utf-8') or '[]')
            rows = [dict(zip(rows[0], r)) for r in rows[1:]] if rows else []
            if not rows: continue
            latest = max(rows, key=lambda r: r['timestamp'])
            items.append(Item(url=f"https://web.archive.org/web/{latest['timestamp']}id_/{latest['original']}", title='', channel=self.channel,
                              adapter=self.name, external_id=latest['original'] + '@' + latest['timestamp'],
                              published_at=snapshot_time(latest['timestamp']), publication_source='archive',
                              directory=CDX + '?' + urlencode({'url': url}), original_url=latest['original']))
        return items

    def fetch(self, item, fetch):
        raw, media, final, _ = fetch(item.url)
        return raw, media, final


register(ArchiveSnapshot())
