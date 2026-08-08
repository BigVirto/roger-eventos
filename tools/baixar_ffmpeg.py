"""Baixa o binário estático do ffmpeg (Windows) e extrai ffmpeg.exe/ffprobe.exe em app/bin/.

Roda uma vez, em tempo de desenvolvimento/build — o resultado é empacotado junto com
o app pelo PyInstaller, para que quem for usar o .exe não precise instalar nada à parte.

Uso: python tools/baixar_ffmpeg.py
"""

import shutil
import urllib.request
import zipfile
from pathlib import Path

URL_FFMPEG = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
RAIZ = Path(__file__).resolve().parent.parent
PASTA_BIN = RAIZ / "app" / "bin"
ZIP_TEMP = RAIZ / ".tmp" / "ffmpeg.zip"


def main() -> None:
    PASTA_BIN.mkdir(parents=True, exist_ok=True)
    ZIP_TEMP.parent.mkdir(parents=True, exist_ok=True)

    print(f"Baixando {URL_FFMPEG} ...")
    urllib.request.urlretrieve(URL_FFMPEG, ZIP_TEMP)

    print("Extraindo ffmpeg.exe e ffprobe.exe ...")
    with zipfile.ZipFile(ZIP_TEMP) as zf:
        for nome in zf.namelist():
            if nome.endswith(("bin/ffmpeg.exe", "bin/ffprobe.exe")):
                destino = PASTA_BIN / Path(nome).name
                with zf.open(nome) as origem, open(destino, "wb") as saida:
                    shutil.copyfileobj(origem, saida)
                print(f"  -> {destino}")

    ZIP_TEMP.unlink(missing_ok=True)

    if not (PASTA_BIN / "ffmpeg.exe").exists():
        raise SystemExit("Não encontrei ffmpeg.exe dentro do zip baixado — verifique a URL/estrutura do release.")

    print("OK: ffmpeg.exe e ffprobe.exe prontos em app/bin/")


if __name__ == "__main__":
    main()
