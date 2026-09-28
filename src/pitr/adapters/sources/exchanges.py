"""Exchange and regulator directories wrapped as SourceAdapters.

The directory timestamp is the authoritative availability proof
(``publication_source='directory'``). Existing market adapters in
``pitr.adapters.identity.markets`` do the listing; nothing is duplicated here.
"""
from __future__ import annotations
from pitr.adapters.identity import markets
from .protocol import Candidate, Item, register


class ExchangeAdapter:
    channel = 'exchange_disclosure'
    proof = 'authoritative_timestamp'

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.markets = tuple(inner.markets)

    def find_candidates(self, subject, acquire):
        raw = lambda url, query=None: acquire(url, query)[0] if query is not None else acquire(url)[0]
        found = self.inner.find_candidates(subject.get('name', ''), subject.get('securities', []), raw)
        return [Candidate(c.name, c.market, c.code, dict(c.identifiers), getattr(c, 'source', '')) for c in found]

    def list_items(self, candidate, acquire, *, since='', until='', types=(), urls=(), terms=()):
        if candidate is None: return []
        raw = lambda url, query=None: acquire(url, query)[0] if query is not None else acquire(url)[0]
        inner = markets.Candidate(candidate.name, candidate.market, candidate.code, dict(candidate.identifiers), candidate.source)
        rows = self.inner.list_disclosures(inner, raw, as_of=until or None)
        items = []
        for row in rows:
            if since and row.published_at and row.published_at[:10] < since[:10]: continue
            if types and row.document_type not in types: continue
            # Trigger terms are matched against acquired full text afterwards, never against titles.
            items.append(Item(url=row.url, title=row.title, channel=self.channel, adapter=self.name, external_id=row.url,
                              published_at=row.published_at, publication_source='directory' if row.published_at else 'content',
                              document_type=row.document_type, market=row.market, period=getattr(row, 'period', ''), directory=row.source))
        return items

    def fetch(self, item, fetch):
        raw, media, final, _ = fetch(item.url)
        return raw, media, final


for inner in markets.ADAPTERS:
    register(ExchangeAdapter(inner))
