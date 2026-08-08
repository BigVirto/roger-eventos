"""Baixa o Deno (runtime JavaScript) e extrai deno.exe em app/bin/.

O yt-dlp precisa de um runtime JS para resolver os desafios do YouTube; sem ele
o download cai em caminhos alternativos lentos ou falha. Como o app é entregue
como .exe único, o Deno vai empacotado junto — o usuário não instala nada.

Uso: python tools/baixar_deno.py
"""

import shutil
import urllib.request
import zipfile
from pathlib import Path

URL_DENO = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
RAIZ = Path(__file__).resolve().parent.parent
PASTA_BIN = RAIZ / "app" / "bin"
ZIP_TEMP = RAIZ / ".tmp" / "deno.zip"


def main() -> None:
    PASTA_BIN.mkdir(parents=True, exist_ok=True)
    ZIP_TEMP.parent.mkdir(parents=True, exist_ok=True)

    print(f"Baixando {URL_DENO} ...")
    urllib.request.urlretrieve(URL_DENO, ZIP_TEMP)

    print("Extraindo deno.exe ...")
    with zipfile.ZipFile(ZIP_TEMP) as zf:
        for nome in zf.namelist():
            if nome.endswith("deno.exe"):
                destino = PASTA_BIN / "deno.exe"
                with zf.open(nome) as origem, open(destino, "wb") as saida:
                    shutil.copyfileobj(origem, saida)
                print(f"  -> {destino}")

    ZIP_TEMP.unlink(missing_ok=True)

    if not (PASTA_BIN / "deno.exe").exists():
        raise SystemExit("Não encontrei deno.exe no zip — verifique a URL do release.")

    print("OK: deno.exe pronto em app/bin/")


if __name__ == "__main__":
    main()
