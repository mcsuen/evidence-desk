"""Owner-directed Slack materials and revisions share the Wiki command service."""
from .capture import company_for, FINANCE, sanitize
from .contracts import CaptureEnvelope


def capture_event(wiki, event, context, *, company_override=None, enqueue=True, notify=True):
    metadata = event.metadata
    external = ':'.join([event.target.team_id, event.target.channel_id, metadata.get('message_ts') or event.id])
    text = event.text
    attachments = []
    for attachment in event.attachments:
        if attachment.status != 'ready':
            continue
        raw = context.attachment_bytes(attachment.id)
        # Preserve originals separately from their extracted, sanitized reading text.
        if attachment.media_type in ('application/pdf', 'text/plain', 'text/html') or attachment.name.lower().endswith(('.pdf', '.txt', '.html', '.md')):
            from pitr.desk.sources import parse_document
            media = attachment.media_type or ('application/pdf' if attachment.name.endswith('.pdf') else 'text/plain')
            doc = parse_document(raw, media, 'slack:' + attachment.file_id, '', attachment.name)
            extracted = '\n\n'.join(b.text for b in doc.blocks)
            clean = sanitize(extracted)
            if clean != extracted:
                # Do not persist a credential-bearing attachment into the Wiki CAS.
                text += '\n\n' + attachment.name + '\n' + clean + '\n原附件含凭据信息，仅收录脱敏文本。'
            else:
                attachments.append(wiki.objects.put(raw))
                text += '\n\n' + attachment.name + '\n' + extracted
    if event.kind=='changed' and not metadata.get('files_present'):
        from .store import state
        with wiki.store.connect() as db:
            prior=next((s for s in state(db,'sources').values() if s.get('capture_key')=='slack:'+external and s['state']=='available'),None)
        for sha in (prior or {}).get('attachments',[]):
            from pitr.desk.sources import parse_document
            raw=wiki.objects.get(sha)
            doc=parse_document(raw,'application/pdf' if raw.startswith(b'%PDF') else 'text/plain','slack:retained-attachment','','保留附件')
            text+='\n\n'+'\n\n'.join(sanitize(b.text) for b in doc.blocks)
            attachments.append(sha)
    company = company_override or company_for(text)
    action = 'withdraw' if event.kind == 'deleted' else ('revise' if event.kind == 'changed' else 'capture')
    if action == 'capture' and not FINANCE.search(text):
        return None
    with wiki.store.connect(write=True) as db:
        identity = 'slack:' + external
        from .store import state
        prior = next((s for s in state(db, 'sources').values() if s.get('capture_key') == identity and s['state'] == 'available'), None)
        if prior:
            company = prior['company']
        result = wiki.capture(CaptureEnvelope(operation_id='slack-capture:' + event.id, provider='slack',
            external_id=external, company=company, title='Slack 公司研究材料', text=text,
            thread_id=event.target.thread_ts or '', action=action, attachments=attachments,
            url='slack://' + event.target.team_id + '/' + event.target.channel_id), db=db, enqueue=enqueue)
        notify_key = 'slack-receipt:' + event.id
        if notify and not wiki._cached(db, notify_key, result):
            if result.get('status') not in ('not_captured', 'duplicate', 'ignored_echo'):
                wiki._emit(db, company, 'notification.requested', [], jobs=[('slack', {
                    'event_id': event.id,
                    'text': '[PITR Wiki] ' + {'captured': '资料已收录，后台整理后在工作台审核。', 'withdrawn': '已撤回来源，相关知识进入复核。'}.get(result['status'], result['status'])
                      + ('\n公司待归类，请在 Wiki 的原始资料中指定。' if not company else '\n' + company),
                    'source_id': result.get('id')})])
            wiki._remember(db, notify_key, result, {'queued': True})
    return result
