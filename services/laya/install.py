"""Explicit, repeatable installation. Never executed during a normal read request."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

LAYA_REV = '1c5edc17a7acd8701df6fc341c0d179f1c62c982'
E5_REV = '614241f622f53c4eeff9890bdc4f31cfecc418b3'


def install(home):
    home = Path(home).resolve()
    home.mkdir(parents=True, exist_ok=True)
    uv = shutil.which('uv')
    if not uv: raise RuntimeError('请先安装 uv，随后重试本地模型安装')
    python = home / 'venv/bin/python'
    if not python.exists(): subprocess.run([uv, 'venv', str(home / 'venv'), '--python', '3.12'], check=True)
    subprocess.run([uv, 'pip', 'install', '--python', str(python), '-r', str(Path(__file__).with_name('requirements.txt'))], check=True)
    code = '''
import sys
from huggingface_hub import snapshot_download
root=sys.argv[1]
snapshot_download('convaiinnovations/laya', revision=sys.argv[2], local_dir=root+'/laya', allow_patterns=['multilingual/*'])
snapshot_download('intfloat/multilingual-e5-small', revision=sys.argv[3], local_dir=root+'/e5', allow_patterns=['config.json','model.safetensors','tokenizer*','special_tokens_map.json','sentencepiece.bpe.model'])
'''
    subprocess.run([str(python), '-c', code, str(home), LAYA_REV, E5_REV], check=True,
                   env={**os.environ, 'HF_HUB_DISABLE_TELEMETRY': '1'})
    files = {}
    for folder in ('laya', 'e5'):
        for path in (home / folder).rglob('*'):
            if path.is_file() and '.cache' not in path.parts:
                sha = hashlib.sha256()
                with path.open('rb') as stream:
                    for part in iter(lambda: stream.read(8 * 1024 * 1024), b''): sha.update(part)
                files[str(path.relative_to(home))] = sha.hexdigest()
    lock = {'sdk': '573e5b62696ba441230cd6be71d593331b5d23af', 'laya': LAYA_REV, 'embedding': E5_REV, 'files': files}
    temp = home / 'model-lock.tmp'
    temp.write_text(json.dumps(lock, indent=2))
    temp.replace(home / 'model-lock.json')
    print('本地模型已安装；首次评分将验证文件并加载模型。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True)
    install(parser.parse_args().home)
