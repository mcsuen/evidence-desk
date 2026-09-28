"""Install-time CoreText registration and runtime family detection."""
import ctypes
import os
from pathlib import Path
import platform
import shutil
import subprocess

FAMILY = 'Noto Sans CJK SC'


def coretext():
    cf = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    ct = ctypes.CDLL('/System/Library/Frameworks/CoreText.framework/CoreText')
    cf.CFRelease.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_uint]
    cf.CFStringGetCString.restype = ctypes.c_bool
    return cf, ct


def available():
    if platform.system() == 'Darwin':
        cf, ct = coretext()
        ct.CTFontManagerCopyAvailableFontFamilyNames.restype = ctypes.c_void_p
        names = ct.CTFontManagerCopyAvailableFontFamilyNames()
        try:
            for i in range(cf.CFArrayGetCount(names)):
                buffer = ctypes.create_string_buffer(1024)
                cf.CFStringGetCString(cf.CFArrayGetValueAtIndex(names, i), buffer, 1024, 0x08000100)
                if buffer.value.decode() == FAMILY:
                    return True
            return False
        finally:
            cf.CFRelease(names)
    if shutil.which('fc-list'):
        result = subprocess.run(['fc-list', ':family='+FAMILY, 'family'], capture_output=True, text=True, timeout=10)
        return FAMILY in result.stdout
    return False


def register(path):
    if platform.system() != 'Darwin':
        subprocess.run(['fc-cache', '-f', str(Path(path).parent)], check=True)
    elif not available():
        cf, ct = coretext()
        cf.CFURLCreateFromFileSystemRepresentation.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_bool]
        cf.CFURLCreateFromFileSystemRepresentation.restype = ctypes.c_void_p
        ct.CTFontManagerRegisterFontsForURL.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]
        ct.CTFontManagerRegisterFontsForURL.restype = ctypes.c_bool
        raw = os.fsencode(Path(path).resolve())
        url = cf.CFURLCreateFromFileSystemRepresentation(None, raw, len(raw), False)
        error = ctypes.c_void_p()
        try:
            # User scope persists across sessions and is visible to LibreOffice.
            ct.CTFontManagerRegisterFontsForURL(url, 2, ctypes.byref(error))
        finally:
            cf.CFRelease(url)
            if error.value:
                cf.CFRelease(error)
    if not available():
        raise RuntimeError('项目中文字体未注册到系统字体目录')
