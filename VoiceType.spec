# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/WorkBuddyWorkSpace/语音转换应用程序/run.py'],
    pathex=['D:/WorkBuddyWorkSpace/语音转换应用程序'],
    binaries=[],
    datas=[('D:/WorkBuddyWorkSpace/语音转换应用程序/README.md', '.')],
    hiddenimports=['app'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.QtNetwork', 'tkinter', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceType',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceType',
)
