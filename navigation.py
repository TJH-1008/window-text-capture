"""Small foreground-guarded native UI actions for the selected mini-program."""
import base64
import json
import os
import subprocess
import sys
from pathlib import Path

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
SCRIPT = BASE / 'window_navigation.ps1'
SHELL = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'


def action(handle, mode, text='', key=13, x=0, y=0, timeout=30, after=''):
    command = [str(SHELL), '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
               '-File', str(SCRIPT), '-Mode', mode, '-WindowHandle', str(handle)]
    if text:
        command += ['-TextBase64', base64.b64encode(text.encode('utf-8')).decode('ascii')]
    if after:
        command += ['-AfterBase64', base64.b64encode(after.encode('utf-8')).decode('ascii')]
    if mode == 'key':
        command += ['-Key', str(key)]
    if mode == 'point':
        command += ['-X', str(x), '-Y', str(y)]
    process = subprocess.run(command, capture_output=True, encoding='utf-8', errors='replace',
                             creationflags=subprocess.CREATE_NO_WINDOW, timeout=timeout)
    lines = process.stdout.strip().splitlines()
    try:
        result = json.loads(lines[-1])
    except (ValueError, IndexError):
        raise RuntimeError('页面操作未返回有效结果：' + process.stderr[-1200:]) from None
    if process.returncode or not result.get('ok'):
        raise RuntimeError(result.get('error') or process.stderr[-1200:])
    return result


def primary_text(snapshot):
    docs = snapshot.get('documents', [])
    return docs[-1].get('text', '') if docs else ''
