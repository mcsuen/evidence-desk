from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from .contracts import *


def router(news):
    routes = APIRouter(prefix='/api/v1/lab/news', tags=['lab-news'])

    def human(request):
        if request.headers.get('x-pitr-actor') == 'agent': raise HTTPException(403, '请由研究员操作新闻实验')

    @routes.get('/status', response_model=NewsStatus)
    def status(): return news.status()

    @routes.get('/settings', response_model=NewsSettings)
    def settings(): return news.settings()

    @routes.put('/settings', response_model=NewsSettings)
    def configure(body: NewsSettingsInput, request: Request):
        human(request)
        return news.configure(body)

    @routes.post('/runs')
    def run(body: NewsRunInput, request: Request):
        human(request)
        return news.enqueue(body)

    @routes.get('/events', response_model=NewsEvents)
    def events(company: str='', queue: str='selected', date: str='', offset: int=Query(0, ge=0), limit: int=Query(50, ge=1, le=100), order: str='high'):
        return news.events(company, queue, date, offset, limit, order)

    @routes.get('/events/{event_id}', response_model=NewsDetail)
    def detail(event_id: str, score_id: str='', company: str=''): return news.detail(event_id, score_id, company)

    @routes.post('/events/{event_id}/feedback')
    def feedback(event_id: str, body: NewsFeedbackInput, request: Request):
        human(request)
        return news.feedback(event_id, body)

    @routes.post('/events/{event_id}/research-draft', response_model=NewsResearchDraft)
    def draft(event_id: str, body: NewsDraftInput, request: Request):
        human(request)
        return news.draft(event_id, body)

    @routes.get('/drafts/{draft_id}', response_model=NewsResearchDraft)
    def get_draft(draft_id: str): return news.get_draft(draft_id)

    @routes.get('/articles/{article_id}/original')
    def original(article_id: str):
        import hashlib
        with news.store.connect() as db: row = db.execute('SELECT body FROM articles WHERE id=?', (article_id,)).fetchone()
        if not row: raise KeyError('新闻原件不存在')
        article = NewsArticle.model_validate_json(row[0])
        if not article.original_file: raise KeyError('尚未取得新闻正文原件')
        raw = (news.store.originals / article.original_file).read_bytes()
        if hashlib.sha256(raw).hexdigest() != article.digest: raise ValueError('原件摘要不一致')
        return Response(raw, media_type=article.media, headers={'Content-Security-Policy': "sandbox; default-src 'none'; style-src 'unsafe-inline'"})

    return routes
