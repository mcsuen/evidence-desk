"""Reproducible checks, separate from semantic allegations and human judgment."""
import ast
import json
import math
import operator
import re
from decimal import Decimal, ROUND_HALF_UP

NUMBER = re.compile(r'(?<![A-Za-z_])[-+−]?\d[\d,]*(?:\.\d+)?')
FIELDS = ('content', 'summary', 'applicability', 'failure_cases', 'example')
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def numeric_context(text, start, end):
    """Do not borrow a directional assertion from a neighboring table cell.

    Table headers and row labels still constrain the value: an observation in a
    column or row named '同比增长' must have a calculation binding.
    """
    line_start = text.rfind('\n', 0, start) + 1
    line_end = text.find('\n', end)
    line = text[line_start:line_end if line_end >= 0 else len(text)]
    block = []
    for row in reversed(text[:line_start].splitlines()):
        if not re.search(r'(?<!\\)\|', row):break
        block.insert(0, row)
    table_header = len(block) >= 2 and re.fullmatch(r'[\s|:\-]+', block[1])
    if line.lstrip().startswith('|') or (table_header and re.search(r'(?<!\\)\|', line)):
        cuts = [m.start() for m in re.finditer(r'(?<!\\)\|', line)]
        local = start - line_start
        column = sum(c < local for c in cuts)
        cells = re.split(r'(?<!\\)\|', line)
        cell_start = cuts[column-1] + 1 if column else 0
        context = [numeric_context(cells[column], local-cell_start, end-line_start-cell_start)]
        label_column = next((i for i, c in enumerate(cells) if c.strip()), None)
        # A mixed cell may say "增长；金额 [100] 元" in a row labelled
        # "收入同比". The explicit amount clause identifies this occurrence as
        # a level, while the separate qualitative direction still needs review.
        # A directional column header remains binding even in that case.
        explicit_amount = re.match(r'^\s*(?:金额|余额)\s*[:：为]?\s*\[?[-+−]?\d', context[0])
        if label_column is not None and label_column != column and not explicit_amount:
            context.append(cells[label_column])
        if table_header:
            headers = re.split(r'(?<!\\)\|', block[0])
            if column < len(headers):context.append(headers[column])
        return ' '.join(context)
    # A following sentence/clause may describe change while this number is an
    # absolute amount. Commas within numeric literals are not clause boundaries.
    boundaries = list(re.finditer(r'[\n。；，;]|(?<!\d),|,(?!\d)', text))
    left = max([m.end() for m in boundaries if m.end() <= start], default=0)
    right = min([m.start() for m in boundaries if m.start() >= end], default=len(text))
    return text[max(left, start-12):min(right, end+4)]


def display_number(value, decimals):
    if type(decimals) is not int or not 0 <= decimals <= 6:
        raise ValueError('显示精度必须为零至六位小数')
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP)


def calculate(expression, values):
    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Name) and node.id in values:
            return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in OPS:
            return OPS[type(node.op)](evaluate(node.left), evaluate(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -evaluate(node.operand)
        raise ValueError('计算只允许已绑定指标和四则运算')
    if len(expression) > 1000:
        raise ValueError('计算表达式过长')
    value = evaluate(ast.parse(expression, mode='eval'))
    if not math.isfinite(value):
        raise ValueError('计算结果必须有限')
    return value


def validate_numbers(db, draft, sources):
    research_bindings=[b for b in draft.get('numeric_assertions',[]) if b.get('kind')=='research_artifact']
    if research_bindings:
        from pitr.desk.research.handoff import resolve
        if len(research_bindings)!=1 or len(draft['numeric_assertions'])!=1:raise ValueError('研究交接绑定只能引用一个完整核验产物')
        report,claim=resolve(db,research_bindings[0]['research_ref'])
        if draft.get('content')!=claim['text'] or any(draft.get(k) for k in FIELDS if k!='content'):raise ValueError('Wiki 内容与核验后的研究产物不一致')
        if not {e['source_id'] for e in report['evidence']} <= {c['source_id'] for c in draft.get('citations',[])}:raise ValueError('研究依赖来源未完整保留')
        return len(list(NUMBER.finditer(draft['content'])))
    observations = ({m['id']:m for m in draft['evidence_observations']} if 'evidence_observations' in draft else
                    {r['id']: json.loads(r['body']) for r in db.execute('SELECT id,body FROM observations')})
    bindings = draft.get('numeric_assertions', [])
    cited = {c['source_id'] for c in draft.get('citations', [])}
    count = 0
    for field in FIELDS:
        text = draft.get(field) or ''
        for occurrence in NUMBER.finditer(text):
            count += 1
            found = [b for b in bindings if b.get('field') == field and b.get('start') == occurrence.start() and b.get('end') == occurrence.end()]
            if len(found) != 1:
                raise ValueError(f'{field} 每个数字需要独立绑定指标、值、单位、期间和口径')
            binding = found[0]
            literal = float(occurrence.group().replace(',', '').replace('−', '-'))
            if binding.get('kind') == 'period':
                source = sources.get(binding.get('source_id'))
                if not source or source['id'] not in cited or str(binding.get('value')) != occurrence.group():
                    raise ValueError('期间数字必须绑定同一引用的原始来源')
                period = str(binding.get('period', ''))
                if not period or occurrence.group() not in period or not any(period in b['text'] for b in source['blocks']):
                    raise ValueError('原文没有披露所绑定期间')
                continue
            def observation(oid):
                item = observations.get(oid)
                if not item or item['citation']['source_id'] not in cited:
                    raise ValueError('数值缺少所引用来源的原始指标')
                return item
            if binding.get('kind') == 'calculation':
                operands = {alias: observation(oid) for alias, oid in binding.get('operands', {}).items()}
                if not operands or not binding.get('unit') or not binding.get('period') or not binding.get('basis'):
                    raise ValueError('计算缺少原始操作数、单位、期间或口径')
                if any(m['basis'] != binding['basis'] for m in operands.values()):
                    raise ValueError('计算口径不一致')
                unit_set = {m['unit'] for m in operands.values()}
                if len(unit_set) != 1:
                    raise ValueError('计算操作数单位不一致')
                expected = calculate(binding.get('expression', ''), {k: m['value'] for k, m in operands.items()})
                if binding.get('periods') != {k: m['period'] for k, m in operands.items()}:
                    raise ValueError('计算必须保留每个操作数的业务期间')
            else:
                item = observation(binding.get('observation_id'))
                if any(binding.get(k) != item[k] for k in ('name', 'value', 'unit', 'period', 'basis')):
                    raise ValueError('数值绑定与指标、值、单位、期间或口径不一致')
                expected = item['value']
                near = numeric_context(text, occurrence.start(), occurrence.end())
                if any(word in near for word in ('增长', '下降', '增加', '减少', '同比', '环比')):
                    raise ValueError('方向性变化需要独立计算绑定')
            if 'display_decimals' in binding:
                expected = float(display_number(expected, binding['display_decimals']))
            if not math.isclose(literal, expected, rel_tol=1e-9, abs_tol=1e-9):
                raise ValueError('正文数字与绑定值或计算结果不一致')
    if count != len(bindings):
        raise ValueError('数值绑定必须与正文数字逐一对应')
    return count


def hard_failures(wiki, db, rev):
    from .store import state
    st = state(db)
    failures = []
    try:
        frozen = json.loads(wiki.objects.get(rev['body_object']))
        if {k: v for k, v in rev.items() if k != 'body_object'} != frozen:
            raise ValueError('版本正文与冻结对象不一致')
    except (OSError, ValueError, KeyError) as error:
        failures.append({'type': 'object', 'detail': str(error)})
    for citation in rev.get('citations', []):
        source = st['sources'].get(citation['source_id'])
        if not source:
            failures.append({'type': 'citation', 'detail': '引用来源不存在'})
            continue
        try:
            wiki.objects.get(source['payload_object'])
            for attachment in source.get('attachments',[]):wiki.objects.get(attachment)
            if source.get('record_object'):
                expected=json.loads(wiki.objects.get(source['record_object']))
                if expected!={k:source.get(k) for k in expected}:
                    raise ValueError('原文定位与冻结来源不一致')
        except (OSError, ValueError) as error:
            failures.append({'type': 'object', 'detail': str(error)})
        if not any(b['id'] == citation['block_id'] and citation['quote'] and citation['quote'] in b['text'] for b in source['blocks']):
            failures.append({'type': 'citation', 'detail': '引用段落或原文不存在'})
    if rev['kind'] != 'policy':
        try:
            validate_numbers(db, rev, st['sources'])
        except (ValueError, ZeroDivisionError, SyntaxError) as error:
            failures.append({'type': 'calculation' if '计算' in str(error) else 'numeric', 'detail': str(error)})
    return failures
