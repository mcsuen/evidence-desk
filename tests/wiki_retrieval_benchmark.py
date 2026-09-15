"""Run only on an explicit developer request. Uses a temporary synthetic corpus.

python tests/wiki_retrieval_benchmark.py --model-root /tmp/pitr-wiki-onnx-validation
No models are downloaded and no real research is adopted by this script.
"""
import argparse
import json
from pathlib import Path
import tempfile
from pitr.desk.service import Desk
from pitr.desk.sources import parse_document
from pitr.desk.contracts import Citation
from pitr.wiki.contracts import ProposalInput,RevisionDraft,Reference,DecisionRecord
from pitr.wiki.search import build_vectors
from pitr.wiki.evaluation import evaluate


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model-root',type=Path);args=parser.parse_args()
    repository=Path(__file__).resolve().parents[1]
    dataset=json.loads((repository/'tests/fixtures/wiki_retrieval.json').read_text())
    with tempfile.TemporaryDirectory(prefix='pitr-wiki-benchmark-') as td:
        desk=Desk(Path(td));wiki=desk.wiki
        raw=('Synthetic software evaluation, not a company disclosure.\n\n'+'\n\n'.join(d['content'] for d in dataset['documents'])).encode()
        doc=parse_document(raw,'text/plain','https://investor.pddholdings.com/synthetic-retrieval-fixture','PDD','合成检索题集')
        (desk.files/doc.file_name).write_bytes(raw);desk.put_document(doc)
        changes=[RevisionDraft(id=d['id'],kind='page',page_type='concept',title=d['title'],content=d['content'],
            citations=[Citation(source_id=doc.id,block_id=b.id,quote=b.text) for b in doc.blocks if d['content']==b.text],reason='合成软件评估数据') for d in dataset['documents']]
        p=wiki.propose(ProposalInput(operation_id='fixture-proposal',company='PDD',policy=Reference(id=wiki.policy()['id'],version=1),changes=changes,reason='合成软件评估数据，不代表真实人工采纳'))
        wiki.review(p['id'],DecisionRecord(operation_id='fixture-publication',digest=p['digest'],action='adopt',reason='测试夹具发布，不是实际公司研究结论'))
        reports={'bm25':evaluate(wiki,dataset,save=False)}
        if args.model_root:
            (wiki.store.root/'models').symlink_to(args.model_root.resolve()/'models',target_is_directory=True)
            reports['index']=build_vectors(wiki)
            reports['hybrid']=evaluate(wiki,dataset,hybrid=True,save=False)
        destination=repository/'output/wiki-retrieval.json'
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(reports,ensure_ascii=False,indent=2))
        print(json.dumps({k:{'metrics':v['metrics'],'latency_ms':v['latency_ms'],'semantic_available':v['semantic_available']} for k,v in reports.items() if k!='index'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
