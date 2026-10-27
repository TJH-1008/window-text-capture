"""Build public ZIPs from an executable and an explicit resource allowlist."""
import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_release import ROOT, TEMPLATES, package_files, version, zip_problems


def create_package(exe, destination, root=ROOT, upgrade=False):
    value = version(root)
    exe = Path(exe)
    if exe.name != f'WindowCapture_{value}.exe' or exe.read_bytes()[:2] != b'MZ':
        raise ValueError('Expected the versioned Windows executable')
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    startup = f'@echo off\r\nsetlocal\r\ncd /d "%~dp0"\r\nstart "" "WindowCapture_{value}.exe" %*\r\n'
    if upgrade:
        readme = f'''# 窗口文本采集器 {value} 升级包

关闭旧程序，将本包文件复制到旧程序目录，再运行新的启动采集器.cmd。
本包不含 CSV/XLSX，不覆盖自定义对照表、采集数据或任务进度。
新版默认表请从便携版单独取出，先备份旧表。不要同时留下多份不一致的业态表。
原始目录与数据由你保留；本包不会自动迁移、删除或合并历史记录。
'''
    else:
        readme = f'''# 窗口文本采集器 {value} Windows 便携版

解压到可写目录，双击启动采集器.cmd。无需 Python 或 Office。
首次运行自动创建采集数据目录；本包不附带真实清单、业务数据库或采集数据。
请填写 Excel模板/自定义商场清单_空白模板.xlsx，再在“商场清单”页导入。
完整说明见使用说明.md，变更与验证范围见版本说明.md。
工具会操作你选择的目标窗口进行搜索、输入、点击和滚动；请保持目标窗口前台。
项目：https://github.com/TJH-1008/window-text-capture
'''
    files = {
        exe.name: exe,
        '启动采集器.cmd': startup.encode('ascii'),
        'LICENSE': root / 'LICENSE',
        'README.md': readme.encode('utf-8'),
    }
    if not upgrade:
        files.update({n: root / n for n in TEMPLATES | {'业态对照表.csv'}})
        files['使用说明.md'] = root / 'docs/使用说明.md'
        files['版本说明.md'] = root / f'docs/releases/v{value}.md'
    assert set(files) == package_files(value, upgrade)
    with zipfile.ZipFile(destination, 'x', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in sorted(files.items()):
            info = zipfile.ZipInfo(f'WindowCapture_{value}/{name}', (2026, 10, 27, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, source if isinstance(source, bytes) else source.read_bytes())
    problems = zip_problems(destination, value)
    if problems:
        raise ValueError(problems)
    return hashlib.sha256(destination.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'release')
    args = parser.parse_args()
    value = version()
    args.output.mkdir(parents=True, exist_ok=True)
    digests = []
    for kind, upgrade in (('便携版', False), ('升级包', True)):
        path = args.output / f'WindowCapture_{value}_{kind}.zip'
        digest = create_package(args.exe, path, upgrade=upgrade)
        digests.append(f'{digest}  {path.name}')
        print(digests[-1])
    (args.output / 'SHA256.txt').write_text('\n'.join(digests) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
