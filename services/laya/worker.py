"""Offline JSON-lines subprocess. stdout is reserved for the versioned protocol."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', USE_TF='0', TOKENIZERS_PARALLELISM='false')
home = Path(sys.argv[1])
agent = embedder = tokenizer = None
peak_mps_driver_bytes = 0
lock = json.loads((home / 'model-lock.json').read_text())


def verify():
    for name, expected in lock['files'].items():
        sha = hashlib.sha256()
        with (home / name).open('rb') as f:
            for block in iter(lambda: f.read(8*1024*1024), b''): sha.update(block)
        if sha.hexdigest() != expected: raise ValueError('本地模型文件不匹配：'+name)


def predict(data):
    global agent, peak_mps_driver_bytes
    import torch
    if agent is None:
        import laya
        agent = laya.load(str(home / 'laya/multilingual'))
    budget = agent.cfg['max_len'] - agent.cfg['head_max_len']
    # Allocate explicitly; never rely on Laya's silent state truncation.
    context_ids = agent.tok.encode(data['context'], add_special_tokens=False)[:min(260, budget//2)]
    context = agent.tok.decode(context_ids)
    prefix = 'Company research context:\n'+context+'\nNews excerpt:\n'
    remaining = budget - len(agent.tok.encode(prefix, add_special_tokens=False)) - 8
    article_ids = agent.tok.encode(data['text'], add_special_tokens=False)[:max(1, remaining)]
    state = prefix+agent.tok.decode(article_ids)
    questions = {
        'relevance': {'type': 'noul', 'instructions': 'Does this news directly or indirectly affect the company or its named business dependencies in the research context?'},
        'materiality': {'type': 'noul', 'instructions': 'Does this excerpt report a concrete development with substantial potential impact on this company business, demand, costs, competition or regulation?'},
        'research_impact': {'type': 'noul', 'instructions': 'Does this news provide concrete evidence supporting or challenging a stated company hypothesis, or helping answer a stated open research question?'}
    }
    result = agent.predict(state, questions)
    if str(agent.device) == 'mps':
        peak_mps_driver_bytes = max(peak_mps_driver_bytes, torch.mps.driver_allocated_memory())
    return {'result': result, 'state': state, 'input_tokens': len(agent.tok.encode(state, add_special_tokens=False)),
            'state_budget': budget, 'device': str(agent.device), 'model': lock['laya'], 'sdk': lock['sdk'],
            'peak_mps_driver_bytes': peak_mps_driver_bytes}


def encode(data):
    global embedder, tokenizer
    import torch
    from transformers import AutoModel, AutoTokenizer
    if embedder is None:
        tokenizer = AutoTokenizer.from_pretrained(str(home / 'e5'), local_files_only=True)
        embedder = AutoModel.from_pretrained(str(home / 'e5'), local_files_only=True).eval()
    result = []
    texts = data['texts']
    for i in range(0, len(texts), 16):
        batch = tokenizer(texts[i:i+16], padding=True, truncation=True, max_length=512, return_tensors='pt')
        with torch.inference_mode():
            output = embedder(**batch).last_hidden_state.masked_fill(~batch['attention_mask'][..., None].bool(), 0)
            pooled = output.sum(1) / batch['attention_mask'].sum(1)[..., None]
            result.extend(torch.nn.functional.normalize(pooled, p=2, dim=1).tolist())
    return result


try:
    with contextlib.redirect_stdout(sys.stderr):
        verify()
        import torch
        torch.set_num_threads(2)
except Exception as error:
    print(json.dumps({'id': 'startup', 'error': str(error)}), flush=True)
    sys.exit(1)

for line in sys.stdin:
    request = {}
    try:
        request = json.loads(line)
        with contextlib.redirect_stdout(sys.stderr):
            if request['method'] == 'encode': result = encode(request['data'])
            elif request['method'] == 'predict': result = predict(request['data'])
            elif request['method'] == 'health': result = {'device': str(agent.device) if agent else '尚未加载', 'laya': lock['laya'], 'sdk': lock['sdk']}
            else: raise ValueError('未知推理方法')
        print(json.dumps({'id': request['id'], 'result': result}, ensure_ascii=False, allow_nan=False), flush=True)
    except Exception as error:
        print(json.dumps({'id': request.get('id'), 'error': str(error)}, ensure_ascii=False), flush=True)
