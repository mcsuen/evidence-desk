"""Desk and Slack share Wiki commands; natural-language intents precede capture."""
import re
from pitr.desk.contracts import TaskInput
from pitr.desk.storage import digest
from pitr.integrations.slack import WorkflowUpdate, WorkflowModal, OutputFile
from pitr.integrations.slack.contracts import WorkflowRejected
from .contracts import WikiJobRequest, WikiUpdateSchedule, QueryInput, DecisionRecord, AnswerInput
from .jobs import WikiJobs
from .store import state, get, change


def intent(text):
    if not re.search(r'wiki|知识库|公司库', text, re.I):
        return None
    if re.search(r'收录|保存.*材料|转发', text) and not re.search(r'构建|建库', text):
        return None
    if re.search(r'审核|采纳|review', text, re.I):
        return 'review'
    if re.search(r'取消.*(?:定时|定期|计划)|(?:定时|定期|计划).*取消', text):
        return 'cancel_schedule'
    if re.search(r'暂停.*更新|更新.*暂停', text):
        return 'pause_schedule'
    if re.search(r'恢复.*更新|更新.*恢复|定期|定时|每[天周日]|schedule', text, re.I):
        return 'schedule'
    if re.search(r'构建|建库|建立|build|创建', text, re.I):
        return 'build'
    if re.search(r'更新|补查|update|refresh', text, re.I):
        return 'update'
    return 'ask' if re.search(r'问|解释|为什么|如何|什么|多少|是否|[?？]|ask|query', text, re.I) or text.lower().startswith('wiki ') else 'read'


def thread_key(event):
    return 'slack-wiki-thread:' + digest([event.target.team_id, event.target.channel_id, event.target.thread_ts or event.target.user_id])


def review_bundle(proposal):
    from pitr.desk.storage import canonical
    return canonical({'reason': proposal['request']['reason'], 'policy': proposal['request']['policy'],
        'before': proposal['before'], 'changes': proposal['request']['changes'], 'verification': proposal['verification'], 'digest': proposal['digest']})


def review_blocks(context, proposal):
    token = context.action('wiki_review', {'proposal_id': proposal['id'], 'digest': proposal['digest']})
    text = proposal['request']['reason'] + '\n' + '\n'.join(c['title'] for c in proposal['request']['changes'])
    return [{'type': 'section', 'text': {'type': 'plain_text', 'text': text[:2600]}},
            {'type': 'actions', 'elements': [{'type': 'button', 'text': {'type': 'plain_text', 'text': '审核完整 Wiki 变更'}, 'action_id': 'pitr_action', 'value': token}]}]


def handle(adapter, event, context):
    wiki = adapter.desk.wiki
    jobs = WikiJobs(wiki, adapter.queue)
    if event.kind == 'submission' and event.action_id == 'wiki_save_submit':
        with wiki.store.connect() as db:
            row = db.execute('SELECT body FROM tasks WHERE id=?', (event.metadata['task_id'],)).fetchone()
        import json
        task = json.loads(row['body']) if row else {}
        answer = task.get('result', {}).get('answer')
        if task.get('status') != 'completed' or not answer or task['request']['workflow'] != 'wiki_answer':
            raise WorkflowRejected('回答尚未完成或已失效，请重新提问。')
        from .research import save_answer
        saved = save_answer(wiki, AnswerInput(operation_id=event.id, query_id=task['request']['parameters']['query_id'],
            title=answer['title'], content=answer['content'], used=answer['used'], citations=answer['citations'],
            numeric_assertions=answer.get('numeric_assertions', []),
            writeback=event.values['writeback']['value']['selected_option']['value']))
        with wiki.store.connect() as db:
            proposal = get(db, 'proposals', saved.get('proposal_id', ''))
        context.publish(event.id + ':wiki-saved', WorkflowUpdate(text='新分析已形成 Wiki 修订草稿，正式版本等待人工采纳。',
            blocks=review_blocks(context, proposal) if proposal and proposal['status'] == 'pending' else [],
            files=[OutputFile(filename='wiki-review.json', title='完整变更及原始证据', content=review_bundle(proposal))] if proposal else []))
        return True
    if event.kind == 'submission' and event.action_id == 'wiki_review_submit':
        result = wiki.review(event.metadata['proposal_id'], DecisionRecord(operation_id=event.id,
            digest=event.metadata['digest'], action=event.values['action']['value']['selected_option']['value'],
            reason=event.values['reason']['value']['value'], reviewer_identity='slack:' + event.target.team_id + ':' + event.target.user_id))
        context.publish(event.id + ':wiki-review', WorkflowUpdate(text='Wiki 整批审核：' + ('已采纳并发布' if result['status'] == 'adopted' else '已驳回')))
        return True
    if event.kind not in ('message', 'mention', 'command'):
        return False
    with wiki.store.connect() as db:
        prior = get(db, 'settings', thread_key(event)) or {}
    action = intent(event.text)
    if not action and prior and re.search(r'为什么|如何|什么|多少|[?？]', event.text) and not event.attachments:
        action = 'ask'
    if not action:
        return False
    next_refs = prior.get('context_refs', [])
    companies = jobs.companies()
    # Match ticker tokens, full names or aliases; substring JD must not match a URL.
    matches = [c['company'] for c in companies.values() if any(re.search(r'(?<![A-Za-z0-9])' + re.escape(name) + r'(?![A-Za-z0-9])', event.text, re.I)
               for name in [c['company'], c['name'], *c['aliases']])]
    if len(matches) > 1:
        raise WorkflowRejected('涉及多个公司，请明确要维护哪家公司的 Wiki；同业资料仍会保留各自主体。')
    company = matches[0] if matches else prior.get('company')
    if not company:
        raise WorkflowRejected('请明确公司名称或代码；尚未登记的公司可先在工作台登记主体与官方来源。')
    if company != prior.get('company'):
        next_refs = []
    if action == 'review':
        with wiki.store.connect() as db:
            proposals = [p for p in state(db, 'proposals').values() if p['company'] == company and p['status'] == 'pending']
        for p in proposals[:5]:
            context.publish(event.id + ':' + p['id'], WorkflowUpdate(text=p['request']['reason'], blocks=review_blocks(context, p),
                files=[OutputFile(filename='wiki-review.json', title='完整变更、证据与目标版本', content=review_bundle(p))], status='waiting_action'))
        if not proposals:
            context.publish(event.id + ':empty', WorkflowUpdate(text=company + ' Wiki 没有待审核变更。'))
        return True
    if action in ('build', 'update'):
        provided = []
        if event.attachments:
            from .slack import capture_event
            material = capture_event(wiki, event, context, company_override=company, enqueue=False, notify=False)
            if material and material.get('id'):
                provided.append(material['id'])
        request = WikiJobRequest.model_validate(context.prepare(lambda: WikiJobRequest(operation_id=event.id,
            intent=action, company=company, research_focus=event.text, channel='slack', source_ids=provided,
            budget_seconds=1200 if action == 'build' else 600).model_dump()))
        job = jobs.create(request)
        context.bind(job['task_id'])
        context.publish(event.id + ':wiki-job', WorkflowUpdate(text=company + ' Wiki ' + ('建库' if action == 'build' else '更新') +
            '已入队。将主动寻找公开资料、保存原件、检查质量并整理完整变更，完成后等待人工采纳。\n任务：' + job['id'], status='queued'))
    elif action in ('schedule', 'pause_schedule', 'cancel_schedule'):
        with wiki.store.connect() as db:
            existing = get(db, 'update_schedules', company)
        if action == 'cancel_schedule':
            jobs.cancel_schedule(company, event.id)
            message = company + ' Wiki 定时更新已取消。'
        else:
            # Preserve configured fields when changing only enabled state.
            fields = {k: v for k, v in (existing or {}).items() if k in WikiUpdateSchedule.model_fields}
            fields.update(operation_id=event.id, company=company, enabled=action != 'pause_schedule', notification_event_id=event.id)
            if re.search(r'每天|每日', event.text):
                fields['frequency'] = 'daily'
            days = re.findall(r'(?:每周|星期|周)([一二三四五六日天])', event.text)
            if days:
                fields.update(frequency='weekly' if len(days) == 1 else 'custom', weekdays=sorted(set('一二三四五六日'.index('日' if d == '天' else d) for d in days)))
            clock = re.search(r'(?<!\d)([01]?\d|2[0-3])[:：]([0-5]\d)', event.text)
            if clock:
                fields['local_time'] = f'{int(clock[1]):02d}:{clock[2]}'
            named = re.search(r'(?:上午|下午|晚上)?\s*(\d{1,2}|九)点', event.text)
            if named and not clock:
                hour = 9 if named[1] == '九' else int(named[1])
                if ('下午' in named[0] or '晚上' in named[0]) and hour < 12:
                    hour += 12
                fields['local_time'] = f'{hour:02d}:00'
            zone = re.search(r'\b(?:Asia|America|Europe|Pacific|Australia)/[A-Za-z_/]+', event.text)
            if zone:
                fields['timezone'] = zone[0]
            schedule = jobs.schedule(WikiUpdateSchedule.model_validate(fields))
            message = company + (' Wiki 更新已暂停。' if not schedule['enabled'] else
                f" Wiki 定时更新已启用：{schedule['frequency']}，星期 {[d + 1 for d in schedule['weekdays']]}，{schedule['local_time']}，{schedule['timezone']}。每次十分钟，无变化保持安静；有待审变更或失败在此通知。")
        context.publish(event.id + ':wiki-schedule', WorkflowUpdate(text=message + '\n由本机工作进程执行，休眠后合并补查。'))
    elif action == 'ask':
        from .research import query
        reading = query(wiki, QueryInput.model_validate(context.prepare(lambda: QueryInput(operation_id=event.id,
            company=company, question=event.text, context_refs=next_refs).model_dump())))
        next_refs = [{'id': p['id'], 'version': p['version']} for p in reading['items'] if p.get('page_type') == 'topic'][:1]
        if not reading['items']:
            context.publish(event.id + ':wiki-gap', WorkflowUpdate(text='当前没有可用的已发布 Wiki 依据，暂不能给出可信答案。可发送“构建 ' + company + ' Wiki”或在工作台查看草稿。'))
        else:
            task = adapter.queue.enqueue(TaskInput(operation_id=event.id + ':answer', workflow='wiki_answer', company=company,
                parameters={'query_id': reading['id']}, budget_seconds=300))
            context.bind(task['id'])
            context.publish(event.id + ':wiki-answer', WorkflowUpdate(text='正在阅读 ' + company + ' 的已有 Wiki，核对原始依据并生成回答。', status='queued'))
    else:
        pages = [p for p in wiki.list(company, include_blocked=False) if p.get('page_type') in ('company', 'topic')]
        context.publish(event.id + ':wiki-read', WorkflowUpdate(text='\n'.join(p['title'] + ' · ' + p['ref'] for p in pages[:8]) or '暂无已采纳公司页或专题。可以发起建库任务。'))
    with wiki.store.connect(write=True) as db:
        record = {'company': company, 'last_event_id': event.id, 'question': event.text, 'context_refs': next_refs}
        wiki._emit(db, company, 'slack.context_saved', [change('settings', thread_key(event), record)])
    return True


def modal(adapter, event):
    if event.action_id == 'wiki_save':
        return WorkflowModal(title='保存研究分析', action_id='wiki_save_submit', metadata=event.metadata, blocks=[
            {'type': 'section', 'text': {'type': 'plain_text', 'text': '保留原始证据与实际使用版本。生成修订草稿后仍须审核采纳；重复回答复用原提案。'}},
            {'type': 'input', 'block_id': 'writeback', 'label': {'type': 'plain_text', 'text': '保存位置'}, 'element': {
                'type': 'static_select', 'action_id': 'value', 'options': [
                    {'text': {'type': 'plain_text', 'text': label}, 'value': value} for label, value in [('补充到所用研究专题', 'topic'), ('独立综合分析', 'analysis')]]}}])
    with adapter.desk.wiki.store.connect() as db:
        proposal = get(db, 'proposals', event.metadata['proposal_id'])
    if not proposal or proposal['status'] != 'pending' or proposal['digest'] != event.metadata['digest']:
        raise WorkflowRejected('审核包已变化，请重新查询 Wiki 审核。')
    return WorkflowModal(title='Wiki 整批审核', action_id='wiki_review_submit', metadata=event.metadata, blocks=[
        {'type': 'section', 'text': {'type': 'plain_text', 'text': (proposal['request']['reason'] + '\n完整逐页正文、证据、目标版本与规范见原线程文件。')[:2400]}},
        {'type': 'input', 'block_id': 'action', 'label': {'type': 'plain_text', 'text': '决定'}, 'element': {'type': 'static_select', 'action_id': 'value', 'options': [
            {'text': {'type': 'plain_text', 'text': label}, 'value': value} for label, value in [('整批采纳', 'adopt'), ('驳回', 'reject')]]}},
        {'type': 'input', 'block_id': 'reason', 'label': {'type': 'plain_text', 'text': '审核理由'}, 'element': {'type': 'plain_text_input', 'action_id': 'value', 'multiline': True}},
        {'type': 'input', 'block_id': 'reviewed', 'label': {'type': 'plain_text', 'text': '确认'}, 'element': {'type': 'checkboxes', 'action_id': 'value', 'options': [
            {'text': {'type': 'plain_text', 'text': '我已核对完整变更、证据与影响'}, 'value': 'yes'}]}}])
