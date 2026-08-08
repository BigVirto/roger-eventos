# -*- mode: python ; coding: utf-8 -*-
# Gera o .exe do Baixador de Músicas do RE Play.
# Rodar de dentro de app/: pyinstaller build.spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# O customtkinter carrega temas (.json), fontes e ícones em tempo de execução;
# sem incluí-los aqui o .exe abre e fecha na hora.
datas_customtkinter = collect_data_files("customtkinter")

a = Analysis(
    ["main.py"],
    # Sem isto o PyInstaller não acha os pacotes locais gui/ e core/ ("No module named 'gui'").
    pathex=[SPECPATH],
    binaries=[
        ("bin/ffmpeg.exe", "bin"),
        ("bin/ffprobe.exe", "bin"),
        ("bin/deno.exe", "bin"),  # runtime JS exigido pelo yt-dlp para os desafios do YouTube
    ],
    datas=datas_customtkinter,
    hiddenimports=["customtkinter"] + collect_submodules("core") + collect_submodules("gui"),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="REPlay-BaixadorDeMusicas",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
