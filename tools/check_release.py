"""Check public source files and exact release-package allowlists."""
import argparse
import hashlib
import io
import re
import struct
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = {
    'Excel模板/业态对照表_Excel参考.xlsx',
    'Excel模板/品牌明细导出模板_11字段.xlsx',
    'Excel模板/自定义商场清单_空白模板.xlsx',
}
DATA_DIRS = {'采集数据', 'captures', 'Excel结果', '原始数据库', '清单任务',
             '__pycache__', 'build', 'dist', 'release', '.venv', 'venv'}
LOCAL_DIRS = DATA_DIRS | {'.git', '.pytest_cache', '.idea', '.vscode'}
TEXT_SUFFIXES = {'.py', '.ps1', '.cs', '.md', '.spec', '.yml', '.yaml',
                 '.bat', '.cmd', '.txt', '.json', '.csv', '.manifest'}
PERSONAL_PATH = re.compile(r'(?i)(?:\b[a-z]:[\\/]+(?:users|documents and settings)[\\/]+|/Users/[^/\s]+/)')
SECRET = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----)')


def version(root=ROOT):
    text = (root / 'workspace_ui.py').read_text(encoding='utf-8-sig')
    match = re.search(r"^VERSION = '([^']+)'", text, re.M)
    if not match:
        raise ValueError('workspace_ui.py does not define VERSION')
    return match.group(1)


def public_files(root=ROOT):
    """Include staged files (even ignored ones); also inspect untracked sources."""
    selected = set()
    try:
        top = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=root,
                             capture_output=True, check=False)
        if top.returncode == 0 and Path(top.stdout.decode('utf-8').strip()).resolve() == root.resolve():
            result = subprocess.run(['git', 'ls-files', '-z'], cwd=root,
                                    capture_output=True, check=True)
            selected.update(n for n in result.stdout.decode('utf-8').split('\0') if n)
    except (OSError, subprocess.CalledProcessError):
        pass
    for path in root.rglob('*'):
        rel = path.relative_to(root)
        if any(p in LOCAL_DIRS or p.startswith('verification') for p in rel.parts):
            continue
        if path.is_file():
            selected.add(rel.as_posix())
    return sorted(selected)


def source_problems(names):
    problems = []
    for name in names:
        p = PurePosixPath(name)
        if any(part in DATA_DIRS or part.startswith('verification') for part in p.parts):
            problems.append(f'Runtime/build data in source: {name}')
        if p.suffix.lower() in {'.exe', '.zip', '.7z', '.rar', '.log', '.db', '.sqlite', '.sqlite3', '.jsonl', '.pem', '.key'}:
            problems.append(f'Non-source or private file: {name}')
        if p.suffix.lower() == '.xlsx' and name not in TEMPLATES:
            problems.append(f'Unexpected workbook: {name}')
        if p.name.startswith(('商务局商场采集清单', '商务局商场采集队列', '.env')):
            problems.append(f'Private input/configuration: {name}')
    return problems


def text_problems(name, text, strict=False):
    result = []
    if name != 'tools/check_release.py' and PERSONAL_PATH.search(text):
        result.append(f'Personal absolute path: {name}')
    if SECRET.search(text):
        result.append(f'Possible credential (value omitted): {name}')
    if strict and 'github.com/' + 'USER/' in text:
        result.append(f'Unresolved repository placeholder: {name}')
    return result


def workbook_problems(data, name):
    problems = []
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for part in archive.namelist():
                if part.endswith('.xml'):
                    text = archive.read(part).decode('utf-8-sig')
                    if PERSONAL_PATH.search(text) or SECRET.search(text):
                        problems.append(f'Private workbook metadata/content: {name} ({part})')
    except (zipfile.BadZipFile, UnicodeDecodeError):
        problems.append(f'Invalid workbook package: {name}')
    return problems


def package_files(release_version, upgrade=False):
    files = {f'WindowCapture_{release_version}.exe', '启动采集器.cmd', 'LICENSE', 'README.md'}
    if not upgrade:
        files |= {'业态对照表.csv', '使用说明.md', '版本说明.md'} | TEMPLATES
    return files


def zip_problems(path, release_version):
    """Only known files may be distributed. Reject arbitrary data and traversal."""
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        all_names = [x.filename for x in entries]
        if len(set(all_names)) != len(all_names):
            return ['Duplicate ZIP entries']
        file_names = [x.filename for x in entries if not x.is_dir()]
        expected_root = f'WindowCapture_{release_version}'
        expected = package_files(release_version, upgrade='升级包' in Path(path).name)
        actual = set()
        for name in all_names:
            p = PurePosixPath(name)
            if '\\' in name or p.is_absolute() or '..' in p.parts or ':' in name:
                return ['Unsafe ZIP path']
            if not p.parts or p.parts[0] != expected_root:
                return [f'Unexpected package root: {name}']
            if name in file_names:
                actual.add('/'.join(p.parts[1:]))
            elif '/'.join(p.parts[1:]) not in {'', 'Excel模板'}:
                return [f'Unexpected directory: {name}']
        problems = [f'Unexpected package file: {n}' for n in sorted(actual - expected)]
        problems += [f'Missing package file: {n}' for n in sorted(expected - actual)]
        for name in file_names:
            if name.endswith('.xlsx'):
                problems.extend(workbook_problems(archive.read(name), name))
            if PurePosixPath(name).suffix.lower() in TEXT_SUFFIXES or PurePosixPath(name).name == 'LICENSE':
                try:
                    text = archive.read(name).decode('utf-8-sig')
                except UnicodeDecodeError:
                    text = archive.read(name).decode('gb18030')
                problems.extend(text_problems(name, text, strict=True))
        return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', action='append', default=[])
    parser.add_argument('--strict', action='store_true')
    args = parser.parse_args(argv)
    names = public_files()
    problems = source_problems(names)
    for name in names:
        path = ROOT / name
        if not path.is_file():
            problems.append(f'Missing staged file: {name}')
        elif path.suffix.lower() == '.xlsx':
            problems.extend(workbook_problems(path.read_bytes(), name))
        elif path.suffix.lower() in TEXT_SUFFIXES or path.name in {'LICENSE', '.gitignore', '.gitattributes'}:
            try:
                text = path.read_text(encoding='utf-8-sig')
            except UnicodeDecodeError:
                problems.append(f'Non-UTF8 public text: {name}')
                continue
            problems.extend(text_problems(name, text, args.strict))
    value = version()
    for name in ('README.md', 'CHANGELOG.md', 'docs/发布清单.md', f'docs/releases/v{value}.md'):
        path = ROOT / name
        if not path.is_file() or value not in path.read_text(encoding='utf-8-sig'):
            problems.append(f'Missing version {value}: {name}')
    from PIL import Image
    with Image.open(ROOT / 'assets/app.png') as icon:
        if icon.size != (1024, 1024):
            problems.append('app.png must be 1024 x 1024')
    ico = (ROOT / 'assets/app.ico').read_bytes()
    if struct.unpack('<H', ico[4:6])[0] < 8:
        problems.append('app.ico is missing icon sizes')
    for path in map(Path, args.zip):
        try:
            problems.extend(f'{path.name}: {p}' for p in zip_problems(path, value))
            print(f'SHA256 {hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            problems.append(f'{path.name}: {exc}')
    for item in problems:
        print('FAIL:', item)
    print(f'Checked {len(names)} public files, version {value}, {len(args.zip)} packages; {len(problems)} problems.')
    print('Review screenshots and workbook contents separately; this is a pattern/allowlist check.')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
