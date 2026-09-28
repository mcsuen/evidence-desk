#!/usr/bin/env python3
"""Real renderer fixture: Chinese, long tables, negative/missing values and both papers."""
import argparse
from pitr.application.service import Workstation
from pitr.application.tools import ToolService
from pitr.research.queue import ResearchQueue
from pitr.domain.common import uid
from pitr.domain.contracts import Scope,CreateCase,StartRun


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);args=parser.parse_args()
    station=Workstation(args.root,runtime=False)
    station.register_subject('layout',identity='EXAMPLE',name='中文跨页验收公司')
    source=station.import_source(('中文跨页验收公司 Example Ltd 2025Q2 GAAP RMB millions\nRevenue 100.000\nOperating loss (20.000)\n'
        '这是用于结构和分页验收的合成原件，不是真实公司披露。'*5).encode(),'text/plain',subjects=['EXAMPLE'])
    case=station.create_case(CreateCase(operation_id='layout-case',question='中文、长表、缺项、负数与跨页引用验收',scope=Scope(subjects=['EXAMPLE']),sources=[source.ref]))
    station.start_run(case['id'],StartRun(operation_id='layout-run',expected_revision=1),binding={'provider':'local'})
    queue=ResearchQueue(station,start=False);run=queue.claim('local');tools=ToolService(station);token=tools.issue(run.id,run.generation)
    def call(name,**arguments):return tools.call(token,{'operation_id':uid('layout'),'name':name,'arguments':arguments})
    ref=lambda v:{'id':v['id'],'revision':v['revision']}
    evidence=call('evidence.quote',source=source.ref.model_dump(),block_id=source.blocks[0].id,quote=source.blocks[0].text)
    values=[]
    for metric,literal in [('revenue','100.000'),('operating_loss','(20.000)')]:
        values.append(call('value.bind',evidence=ref(evidence),literal=literal,start=evidence['quote'].index(literal),metric=metric,subject='EXAMPLE',period='2025Q2',original_unit='RMB_mn',unit='RMB_mn',unit_evidence=ref(evidence),period_evidence=ref(evidence),basis_evidence=ref(evidence),basis='GAAP',frequency='quarter',currency='CNY'))
    rows=[[[{'type':'text','text':f'经营指标说明项目 {i+1}：中文较长名称及披露口径'}],
           [{'type':'value','ref':ref(values[i%2])}],
           [{'type':'text','text':'未披露；不填零'}],
           [{'type':'citation','ref':ref(evidence)}]] for i in range(52)]
    call('report.save',title='中文与原生 Word 长表验收（合成资料）',summary=[{'id':'summary','inlines':[{'type':'text','text':'本报告仅验证原生 Word 编译、图表数据与分页。所有数字来自明确标注的合成原件。'}]}],
        sections=[{'id':'long_table','title':'跨页表格、负数与缺项','blocks':[{'type':'table','id':'table','title':'经营数据表','columns':['指标与口径','数值','待补充内容','来源'],'rows':rows}]},
        {'id':'charts1','title':'原生柱形图','blocks':[{'type':'chart','id':'column','title':'正负值与缺项','kind':'column','categories':['收入','经营亏损','缺项'],'series':[{'name':'合成指标','values':[ref(v) for v in values]+[None]}],'unit':'RMB_mn'}]},
        {'id':'charts2','title':'原生折线图','blocks':[{'type':'chart','id':'line','title':'缺项不连接','kind':'line','categories':['收入','缺项','经营亏损'],'series':[{'name':'合成指标','values':[ref(values[0]),None,ref(values[1])]}],'unit':'RMB_mn'}]},
        {'id':'very_long_section_id_for_word_bookmark_length_constraint_should_be_hashed','title':'跨页引用','blocks':[{'type':'paragraph','id':'tail','inlines':[{'type':'text','text':'最终段落再次引用同一准确原件。'},{'type':'citation','ref':ref(evidence)}]}]}],gaps=['合成验收材料，不提供真实研究结论。'])
    queue.finish(run,'completed')
    print(station.get_run(run.id).report)


if __name__=='__main__':main()
