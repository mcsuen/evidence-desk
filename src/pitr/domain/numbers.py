"""Decimal arithmetic and provenance-preserving financial dimensional rules."""
from decimal import Decimal, InvalidOperation, localcontext, ROUND_HALF_UP
import re

from .contracts import Value


UNITS = {
    '元': ('CNY', Decimal(1)), '人民币元': ('CNY', Decimal(1)),
    '万元': ('CNY', Decimal(10000)), '百万元': ('CNY', Decimal(1000000)),
    '亿元': ('CNY', Decimal(100000000)), 'RMB': ('CNY', Decimal(1)),
    'RMB_thousand': ('CNY', Decimal(1000)), 'USD_thousand': ('USD', Decimal(1000)),
    'RMB_mn': ('CNY', Decimal(1000000)), 'RMB_bn': ('CNY', Decimal(1000000000)),
    'USD_mn': ('USD', Decimal(1000000)), 'USD_bn': ('USD', Decimal(1000000000)),
    'USD': ('USD', Decimal(1)), 'HKD_mn': ('HKD', Decimal(1000000)),
    'HKD': ('HKD', Decimal(1)), '%': ('percent', Decimal(1)),
    'percent': ('percent', Decimal(1)), '百分点': ('percentage_points', Decimal(1)),
    'percentage_points': ('percentage_points', Decimal(1)), 'bp': ('percentage_points', Decimal('.01')),
    'ratio': ('ratio', Decimal(1)), 'multiple': ('multiple', Decimal(1)),
    'RMB_per_ADS': ('CNY_per_ADS', Decimal(1)), 'USD_per_ADS': ('USD_per_ADS', Decimal(1)),
    'RMB_per_share': ('CNY_per_share', Decimal(1)), 'USD_per_share': ('USD_per_share', Decimal(1)),
    'ADS_mn': ('ADS', Decimal(1000000)), 'shares_mn': ('shares', Decimal(1000000)),
    '1': ('1', Decimal(1)),
}
LITERAL = re.compile(r'^[+−\-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$')


def parse_literal(literal: str) -> Decimal:
    value = literal.strip().replace('\u00a0', '')
    negative = value.startswith('(') and value.endswith(')')
    if negative:
        value = value[1:-1].strip()
    if not LITERAL.fullmatch(value) or (negative and value.startswith(('-', '−', '+'))):
        raise ValueError('原值不是完整、明确的数值字符串')
    try:
        result = Decimal(value.replace(',', '').replace('−', '-').rstrip('%'))
    except InvalidOperation as error:
        raise ValueError('原值不能解析') from error
    return -result if negative else result


def conversion(source_unit: str, target_unit: str) -> Decimal:
    a = UNITS.get(source_unit, (source_unit, Decimal(1)))
    b = UNITS.get(target_unit, (target_unit, Decimal(1)))
    if a[0] != b[0]:
        raise ValueError(f'量纲不兼容：{source_unit} → {target_unit}')
    return a[1] / b[1]


def locate(quote: str, literal: str, start: int | None = None) -> int:
    candidates = [m.start() for m in re.finditer(re.escape(literal), quote)
                  if not (m.start() and (quote[m.start()-1].isdigit() or quote[m.start()-1] in '.,'))
                  and not (m.end() < len(quote) and (quote[m.end()].isdigit() or quote[m.end()] in '.,'))]
    if start is None:
        if len(candidates) != 1:
            raise ValueError('数值缺失或出现多次，请指定准确字符位置')
        return candidates[0]
    if start not in candidates:
        raise ValueError('数值位置与原文不一致或只匹配到较大数字的一部分')
    return start


def binding_proofs(args, unit_quote, period_quote, basis_quote):
    """Reject contradicted/missing header dimensions; column meaning still needs review."""
    if args.original_unit not in UNITS or args.unit not in UNITS:
        raise ValueError('未登记的原值单位；先明确受支持的单位，不能默认为不缩放')
    unit=unit_quote.casefold()
    scale=UNITS[args.original_unit][1]
    patterns={Decimal(1000):r'thousand|千',Decimal(10000):r'万',Decimal(1000000):r'million|百万',
              Decimal(100000000):r'亿',Decimal(1000000000):r'billion|十亿'}
    if scale in patterns and not re.search(patterns[scale],unit):
        raise ValueError('原单位的缩放与单位引文不符；引用完整表头或单位注释')
    currency=UNITS[args.original_unit][0].split('_')[0]
    indicators={'CNY':r'rmb|renminbi|人民币|人民幣|元','USD':r'us\$|usd|u\.s\.\s*dollar|美元','HKD':r'hk\$|hkd|港元'}
    if currency in indicators and not re.search(indicators[currency],unit):
        raise ValueError('单位引文未确认所用币种')
    if args.currency and currency in ('CNY','USD','HKD') and args.currency!=currency:
        raise ValueError('币种与数值单位不一致')
    if args.share_basis and 'ADS' in args.original_unit and args.share_basis!='ADS':
        raise ValueError('ADS 单位不能标为普通股')
    year=re.match(r'\d{4}',args.period)
    if year and year[0] not in period_quote:
        raise ValueError('期间引文没有包含所选年份')
    basis=basis_quote.casefold()
    if args.basis.casefold() in ('gaap','us gaap','us-gaap'):
        unadjusted=re.sub(r'non[-\s]*gaap','',basis)
        if not re.search(r'gaap|consolidated|合并|合併',unadjusted):
            raise ValueError('GAAP 数值需要未调整报表或 GAAP 的明确依据')
    if args.basis.casefold() in ('non-gaap','adjusted') and not re.search(r'non[-\s]*gaap|adjusted|调整|調整',basis):
        raise ValueError('调整后口径未在口径引文中出现')


def calculate(operation: str, a: Value, b: Value) -> tuple[Decimal, str, str, str]:
    if a.subject != b.subject:
        raise ValueError('不同主体不得直接混算；同业比较应分别展示')
    for key in ('basis', 'frequency'):
        if getattr(a, key) != getattr(b, key):
            raise ValueError(f'计算口径不一致：{key}')
    if operation not in ('multiply', 'divide') and a.share_basis != b.share_basis:
        raise ValueError('计算口径不一致：share_basis')
    if operation not in ('multiply', 'divide') and a.currency != b.currency:
        raise ValueError('计算口径不一致：currency')
    if a.basis.lower() in ('', 'unknown', 'disclosed'):
        raise ValueError('会计口径未确认，不能默认可比')
    cross_period = operation in ('growth', 'change', 'quarterize')
    if not cross_period and a.period != b.period:
        raise ValueError('期间不同，不能混算')
    if cross_period and (a.metric != b.metric or a.role != b.role):
        raise ValueError('跨期计算需要同一指标和相同来源口径')
    if cross_period and a.period <= b.period:
        raise ValueError('跨期计算须以较新期间为左值，较早期间为右值')
    unit, period, frequency = a.unit, a.period, a.frequency
    with localcontext() as context:
        context.prec = 34
        if operation in ('add', 'subtract', 'change', 'growth', 'quarterize', 'ratio'):
            right = b.amount * conversion(b.unit, a.unit)
            if operation == 'add':
                result = a.amount + right
            elif operation in ('subtract', 'change', 'quarterize'):
                result = a.amount - right
                if operation == 'change' and UNITS.get(a.unit, (a.unit,))[0] == 'percent':
                    unit = 'percentage_points'
            else:
                if not right:
                    raise ValueError('分母不能为零')
                result = (a.amount - right) / abs(right) * 100 if operation == 'growth' else a.amount / right * 100
                unit = 'percent'
            if operation == 'quarterize':
                match_a = re.fullmatch(r'(\d{4})Q([234])', a.period)
                match_b = re.fullmatch(r'(\d{4})Q([123])', b.period)
                if a.frequency != 'ytd' or not match_a or not match_b or match_a[1] != match_b[1] or int(match_a[2]) != int(match_b[2])+1:
                    raise ValueError('累计转单季需要同财年的相邻累计期间')
                frequency = 'quarter'
        elif operation == 'multiply':
            if b.unit not in ('percent', 'ratio', 'multiple'):
                raise ValueError('乘法右值必须是比例或倍数')
            result = a.amount * b.amount / (100 if b.unit == 'percent' else 1)
        elif operation == 'divide':
            if not b.amount:
                raise ValueError('分母不能为零')
            if a.unit == b.unit:
                unit = 'ratio'
            elif b.unit in ('ADS_mn', 'shares_mn') and a.unit in ('USD_mn', 'RMB_mn'):
                expected = 'ADS' if b.unit == 'ADS_mn' else 'ordinary'
                if b.share_basis != expected or a.share_basis not in ('', expected):
                    raise ValueError('每股计算必须明确普通股或 ADS 口径')
                unit = a.unit.split('_')[0] + ('_per_ADS' if b.unit == 'ADS_mn' else '_per_share')
            else:
                raise ValueError('未登记的量纲换算')
            result = a.amount / b.amount
        else:
            raise ValueError('不支持此计算操作')
    return result, unit, period, frequency


def display(value: Value) -> str:
    quantized = value.amount.quantize(Decimal(1).scaleb(-value.precision), rounding=ROUND_HALF_UP)
    labels = {'RMB_mn': '百万元人民币', 'RMB_bn': '十亿元人民币', 'RMB_thousand': '千元人民币',
        'USD_mn':'百万美元','USD_bn':'十亿美元','USD_thousand':'千美元','USD':'美元','RMB':'元人民币',
        'percentage_points':'个百分点','RMB_per_ADS':'元人民币/ADS','USD_per_ADS':'美元/ADS','ratio':'倍','multiple':'倍'}
    return f'{quantized:,.{value.precision}f}' + ('%' if value.unit == 'percent' else ' ' + labels.get(value.unit,value.unit))
