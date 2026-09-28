from pathlib import Path
from pitr.domain.common import digest

PACKAGES = {
    'framing': ('问题界定与研究计划', '开始研究、追加要求或范围变化'),
    'originals': ('原件读取与冲突处理', '读取原件、复杂表格、来源冲突或身份不明'),
    'earnings': ('财报与经营变化', '季度／年度变化、盈利及现金质量'),
    'diligence': ('公司与产业尽调', '竞争、供需、客户／供应关系'),
    'valuation': ('预测与估值', '明确需要预测、情景或估值'),
    'writing': ('研究论证与报告写作', '形成正式报告或修订叙事'),
    'review': ('独立质询与复核', '核心判断、材料冲突、模型或正式长报告'),
}


def catalog():
    return [{'name': name, 'title': title, 'when': when, 'version': '1.0'} for name, (title, when) in PACKAGES.items()]


def load(name):
    if name not in PACKAGES:
        raise KeyError('未登记的方法包')
    content = (Path(__file__).parent / name / 'SKILL.md').read_text()
    return {'name': name, 'title': PACKAGES[name][0], 'version': '1.0', 'content': content,
        'digest': digest(content.encode()), 'contracts': 'research.1', 'tools_version': 'tools.1',
        'template_version': 'research.1', 'evaluation_version': 'acceptance.1'}


def references(subjects):
    import json
    return [json.loads(p.read_text()) for p in (Path(__file__).parent/'references').glob('*.json')
            if set(subjects).intersection(json.loads(p.read_text())['subjects'])]
