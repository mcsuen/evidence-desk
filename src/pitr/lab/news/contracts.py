from typing import Any, Literal
from pydantic import Field, field_validator, model_validator
from pitr.domain.common import Contract, Command


class NewsSource(Contract):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=160)
    kind: Literal['rss', 'disclosure', 'gdelt'] = 'rss'
    url: str = ''
    enabled: bool = True
    adapter: str = ''
    company: str = ''
    terms: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode='after')
    def valid_source(self):
        if self.kind == 'rss' and not self.url.startswith(('https://', 'http://')):
            raise ValueError('RSS 来源需要公开 HTTP(S) 地址')
        if self.kind == 'disclosure' and (not self.adapter or not self.company):
            raise ValueError('公告来源需要公司和适配器')
        if self.kind == 'gdelt' and not self.terms:
            raise ValueError('全球发现需要公开主题关键词')
        return self


class NewsSettings(Contract):
    enabled: bool = False
    cadence_minutes: int = Field(default=30, ge=5, le=1440)
    daily_limit: int = Field(default=1000, ge=1, le=10000)
    companies: list[str] = Field(default_factory=list)
    sources: list[NewsSource] = Field(default_factory=list, max_length=100)

    @field_validator('sources')
    @classmethod
    def unique(cls, value):
        if len({s.id for s in value}) != len(value):
            raise ValueError('来源 ID 不能重复')
        return value


class NewsSettingsInput(Command):
    settings: NewsSettings


class NewsRunInput(Command):
    kind: Literal['collect', 'rescore', 'install'] = 'collect'


class NewsArticle(Contract):
    id: str
    event_id: str
    source_id: str
    source_name: str
    title: str
    url: str
    published_at: str | None = None
    observed_at: str
    text: str
    excerpt: str = ''
    digest: str
    content_digest: str = ''
    media: str = 'text/plain'
    original_file: str = ''
    publication_source: str = 'content'
    issues: list[str] = Field(default_factory=list)


class NewsProfile(Contract):
    id: str
    company: str
    name: str
    aliases: list[str]
    items: list[dict[str, Any]] = Field(default_factory=list)
    identity_version: str


class NewsScore(Contract):
    id: str
    event_id: str
    article_id: str
    company: str
    profile_id: str
    created_at: str
    signature: str
    priority: float | None = None
    dimensions: dict[str, float] = Field(default_factory=dict)
    confidence: dict[str, float] = Field(default_factory=dict)
    queue: Literal['selected', 'uncertain', 'all'] = 'uncertain'
    reasons: list[str] = Field(default_factory=list)
    references: list[dict[str, Any]] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    raw: list[dict[str, Any]] = Field(default_factory=list)
    model: dict[str, Any] = Field(default_factory=dict)
    policy_version: str = 'news-priority.1'
    calibration: str = '未校准'


class NewsEvent(Contract):
    id: str
    title: str
    first_seen: str
    updated_at: str
    article_count: int
    score: NewsScore | None = None
    companies: list[str] = Field(default_factory=list)


class NewsEvents(Contract):
    items: list[NewsEvent]
    total: int
    counts: dict[str, int]
    offset: int = 0


class NewsDetail(Contract):
    event: NewsEvent
    articles: list[NewsArticle]
    scores: list[NewsScore]
    selected: NewsScore | None = None
    latest_score_id: str | None = None
    profile: NewsProfile | None = None
    feedback: list[dict[str, Any]] = Field(default_factory=list)


class NewsFeedbackInput(Command):
    score_id: str
    verdict: Literal['useful', 'irrelevant', 'duplicate', 'raise', 'important', 'not_important']
    note: str = Field(default='', max_length=2000)


class NewsDraftInput(Command):
    score_id: str
    article_ids: list[str] = Field(default_factory=list, max_length=10)


from pitr.domain.contracts import Ref


class NewsMaterial(Contract):
    source: Ref
    title: str
    url: str


class NewsResearchDraft(Contract):
    id: str
    company: str
    question: str
    event_id: str
    score_id: str
    profile_id: str
    created_at: str
    materials: list[NewsMaterial]
    knowledge: list[Ref]
    context: dict[str, Any]


class NewsStatus(Contract):
    settings: NewsSettings
    runtime: dict[str, Any]
    sources: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    counts: dict[str, int]
    evaluation: dict[str, Any]
