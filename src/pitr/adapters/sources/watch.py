"""Generic URL watch: version a page by content digest. Dates found in the page are self-reported."""
from __future__ import annotations
from .protocol import Item, register


class GenericURLWatch:
    name = 'URL_WATCH'
    channel = 'media'
    markets = ()
    proof = 'self_reported'

    def find_candidates(self, subject, acquire):
        return []

    def list_items(self, candidate, acquire, *, since='', until='', types=(), urls=(), terms=()):
        return [Item(url=url, title='', channel=self.channel, adapter=self.name, external_id=url, publication_source='content') for url in urls]

    def fetch(self, item, fetch):
        raw, media, final, _ = fetch(item.url)
        return raw, media, final


register(GenericURLWatch())
