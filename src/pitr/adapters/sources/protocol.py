"""SourceAdapter protocol: list items with a provable availability time, then fetch bytes."""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Literal, Protocol

PublicationSource = Literal['directory', 'archive', 'content']


@dataclass
class Candidate:
    name: str
    market: str = ''
    code: str = ''
    identifiers: dict = field(default_factory=dict)
    source: str = ''


@dataclass
class Item:
    url: str
    title: str
    channel: str
    adapter: str
    external_id: str
    published_at: str = ''                   # ISO date or timestamp the adapter can prove
    publication_source: PublicationSource = 'content'
    document_type: str = 'other'
    market: str = ''
    period: str = ''
    directory: str = ''                      # the listing/query URL the item came from
    original_url: str = ''                   # for archives: the live URL that was snapshotted

    def dump(self):
        return asdict(self)


class SourceAdapter(Protocol):
    name: str
    channel: str
    markets: tuple[str, ...]
    proof: str                                # availability proof grade this adapter can deliver

    def find_candidates(self, subject: dict, acquire) -> list[Candidate]: ...
    def list_items(self, candidate: Candidate | None, acquire, *, since: str = '', until: str = '', types=(), urls=(), terms=()) -> list[Item]: ...
    def fetch(self, item: Item, fetch) -> tuple[bytes, str, str]: ...


_REGISTRY: dict[str, SourceAdapter] = {}


def register(adapter):
    _REGISTRY[adapter.name] = adapter
    return adapter


def adapters():
    from . import exchanges, watch, archive  # noqa: F401  (registration side effects)
    return dict(_REGISTRY)


def adapter(name):
    found = adapters().get(name)
    if not found: raise KeyError('未知来源适配器：' + name)
    return found
