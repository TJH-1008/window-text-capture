"""PyInstaller spec：版本号取自 workspace_ui.VERSION，避免打包名和界面版本不一致。

用法：pyinstaller --noconfirm opendesign.spec
产物：dist/WindowCapture_<版本>.exe
"""
import re
from pathlib import Path

base = Path(SPECPATH)
version = re.search(r"^VERSION = '([^']+)'", (base / 'workspace_ui.py').read_text(encoding='utf-8'), re.M).group(1)

a = Analysis(
    [str(base / 'app.py')],
    pathex=[str(base)], binaries=[],
    datas=[(str(base / name), '.') for name in
           ('window_reader.ps1', 'window_navigation.ps1', 'generic_reader.ps1', 'generic_native.cs')]
          # 只带 assets 顶层的图标/封面，跳过 icons-lab 这类比选产物
          + [(str(path), 'assets') for path in sorted((base / 'assets').iterdir()) if path.is_file()],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['numpy'],
    noarchive=False, optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name=f'WindowCapture_{version}', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, upx_exclude=[], runtime_tmpdir=None, console=False,
    icon=str(base / 'assets' / 'app.ico'), manifest=str(base / 'display.manifest'),
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
