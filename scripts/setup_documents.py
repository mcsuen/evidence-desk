#!/usr/bin/env python3
"""Install project-local LibreOffice and the OFL Chinese font, without admin rights.

macOS uses the official versioned distribution and its SHA-256 checksum. Linux
may supply /usr/bin/libreoffice or PITR_SOFFICE; no desktop-app runtime is needed.
"""
import hashlib
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VERSION = '26.2.6'


def download(url, target):
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix(target.suffix+'.download')
    print('Downloading '+target.name,flush=True)
    with urllib.request.urlopen(url,timeout=90) as stream, temporary.open('wb') as output:
        shutil.copyfileobj(stream,output,1024*1024)
    temporary.replace(target)


def main():
    font=ROOT/'.tools/fonts/NotoSansCJKsc-Regular.otf'
    if not font.exists():
        download('https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/Sans/OTF/SimplifiedChinese/NotoSansCJKsc-Regular.otf',font)
    if hashlib.sha256(font.read_bytes()).hexdigest()!='2c76254f6fc379fddfce0a7e84fb5385bb135d3e399294f6eeb6680d0365b74b':raise ValueError('中文字体下载校验失败')
    if not (font.parent/'LICENSE.txt').exists():
        download('https://raw.githubusercontent.com/notofonts/noto-cjk/Sans2.004/LICENSE',font.parent/'LICENSE.txt')
    installed=Path.home()/('Library/Fonts' if platform.system()=='Darwin' else '.local/share/fonts')/font.name
    installed.parent.mkdir(parents=True,exist_ok=True)
    if not installed.exists():shutil.copy2(font,installed)
    from pitr.artifacts.fonts import register
    register(installed)
    if platform.system()!='Darwin':
        if shutil.which('fc-cache'):subprocess.run(['fc-cache','-f',str(installed.parent)],check=True)
        if not shutil.which('libreoffice'):
            raise SystemExit('Install LibreOffice with your system package manager, or set PITR_SOFFICE.')
        return
    app=ROOT/'.tools/libreoffice/LibreOffice.app'
    if app.exists():return
    arch='aarch64' if platform.machine()=='arm64' else 'x86_64'
    filename=f'LibreOffice_{VERSION}_MacOS_{arch}.dmg'
    url=f'https://download.documentfoundation.org/libreoffice/stable/{VERSION}/mac/{arch}/{filename}'
    package=ROOT/'.tools/downloads'/filename
    if not package.exists():download(url,package)
    with urllib.request.urlopen(url+'.sha256',timeout=60) as stream:
        expected=stream.read().decode().split()[0]
    if hashlib.sha256(package.read_bytes()).hexdigest()!=expected:raise ValueError('LibreOffice download checksum mismatch')
    with tempfile.TemporaryDirectory(prefix='pitr-lo-mount-') as mount:
        result=subprocess.run(['hdiutil','attach',str(package),'-nobrowse','-readonly','-mountpoint',mount,'-plist'],capture_output=True,check=True)
        plistlib.loads(result.stdout)
        try:
            source=next(Path(mount).glob('*.app'))
            app.parent.mkdir(parents=True,exist_ok=True)
            subprocess.run(['ditto',str(source),str(app)],check=True)
        finally:subprocess.run(['hdiutil','detach',mount],check=True)
    print('Word renderer and Chinese font are ready.',flush=True)


if __name__=='__main__':main()
