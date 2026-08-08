"""Empacota uma atualização do app para o Rogério receber sem instalador novo.

O que faz: junta `app/core/` e `app/gui/` num zip de ~100 KB e (opcionalmente) publica
como release no GitHub. O app do Rogério procura esse release sozinho, baixa, e passa a
usar o código novo na abertura seguinte.

Usar:
    python tools/publicar_atualizacao.py              # só gera o zip
    python tools/publicar_atualizacao.py --publicar   # gera e publica no GitHub (usa gh)

Antes de rodar: subir o número em `app/core/versao.py`. O app só aceita um pacote com
versão MAIOR que a que ele já tem — sem subir, nada acontece na máquina do Rogério.

O que este caminho NÃO atualiza: Python, ffmpeg, deno, ícone e nome do programa. Isso
mora dentro do .exe e continua exigindo instalador. Ver `workflows/baixar_musicas_app.md`.
"""

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA_APP = RAIZ / "app"
PASTAS_EMPACOTADAS = ("core", "gui")
SAIDA = RAIZ / ".tmp" / "roger-eventos-app.zip"
IGNORAR = ("__pycache__",)


def ler_versao() -> str:
    """Lê VERSAO de app/core/versao.py sem importar o módulo.

    Importar exigiria o resto do app instalado (customtkinter, yt-dlp); esta ferramenta
    precisa rodar em qualquer terminal, inclusive sem o ambiente virtual ativo.
    """
    texto = (PASTA_APP / "core" / "versao.py").read_text(encoding="utf-8")
    achado = re.search(r'^VERSAO\s*=\s*["\']([^"\']+)["\']', texto, re.MULTILINE)
    if not achado:
        raise SystemExit("Nao achei VERSAO em app/core/versao.py")
    return achado.group(1)


def _arquivos_a_incluir() -> list[tuple[Path, str]]:
    """Pares (caminho no disco, nome dentro do zip)."""
    itens: list[tuple[Path, str]] = []
    for pasta in PASTAS_EMPACOTADAS:
        base = PASTA_APP / pasta
        if not (base / "__init__.py").exists():
            raise SystemExit(f"Pasta {pasta}/ nao parece um pacote Python (falta __init__.py)")
        for arquivo in sorted(base.rglob("*.py")):
            if any(parte in IGNORAR for parte in arquivo.parts):
                continue
            itens.append((arquivo, str(arquivo.relative_to(PASTA_APP)).replace("\\", "/")))
    return itens


def gerar_zip(versao: str) -> Path:
    itens = _arquivos_a_incluir()
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(SAIDA, "w", zipfile.ZIP_DEFLATED) as zf:
        for caminho, nome in itens:
            zf.write(caminho, nome)

    tamanho_kb = SAIDA.stat().st_size / 1024
    print(f"[OK]    {len(itens)} arquivos, {tamanho_kb:.0f} KB -> {SAIDA}")
    return SAIDA


def conferir(versao: str) -> None:
    """Falha cedo nos erros que só apareceriam na máquina do Rogério."""
    from core.atualizador_app import NOME_ASSET, esta_configurado  # noqa: F401

    if SAIDA.name != NOME_ASSET:
        raise SystemExit(
            f"O nome do arquivo ({SAIDA.name}) precisa bater com NOME_ASSET ({NOME_ASSET}) "
            "— o app procura o release por esse nome exato."
        )
    if not esta_configurado():
        raise SystemExit(
            "REPOSITORIO ainda esta com o valor de exemplo em app/core/atualizador_app.py. "
            "Preencha com usuario/repositorio antes de publicar."
        )


def publicar(versao: str, caminho_zip: Path) -> None:
    if shutil.which("gh") is None:
        print(
            "\n[!] O gh (GitHub CLI) nao esta instalado. Duas opcoes:\n"
            "    a) instalar:  winget install GitHub.cli   e depois  gh auth login\n"
            f"    b) publicar pelo site: Releases > Draft a new release > tag v{versao} "
            f"> anexar {caminho_zip}"
        )
        return

    comando = [
        "gh", "release", "create", f"v{versao}", str(caminho_zip),
        "--title", f"Versao {versao}",
        "--notes", f"Atualizacao automatica do app (codigo core/ e gui/) — versao {versao}.",
    ]
    print(f"[INFO]  publicando release v{versao}...")
    resultado = subprocess.run(comando, cwd=RAIZ)
    if resultado.returncode != 0:
        raise SystemExit("Falhou ao publicar. Confira 'gh auth status'.")
    print(f"[OK]    release v{versao} publicado. O app do Rogerio pega em ate 6 horas.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Empacota e publica uma atualizacao do app.")
    parser.add_argument("--publicar", action="store_true", help="publica o release no GitHub")
    args = parser.parse_args()

    sys.path.insert(0, str(PASTA_APP))
    versao = ler_versao()
    print(f"[INFO]  versao em app/core/versao.py: {versao}")

    if args.publicar:
        conferir(versao)

    caminho = gerar_zip(versao)

    if args.publicar:
        publicar(versao, caminho)
    else:
        print("\nPara publicar:  python tools/publicar_atualizacao.py --publicar")
