"""Mostra os erros que chegaram da máquina do Rogério, agrupados e em ordem de dor.

Por que existe: abrir o navegador e ler chamado por chamado não escala e não responde a
pergunta que importa — "o que está atrapalhando MAIS?". Aqui a ordem é por quantidade de
ocorrências, que é a fila de trabalho de verdade.

Usar:
    python tools/ver_erros.py               # lista o que está aberto, do pior para o menor
    python tools/ver_erros.py 12            # abre o chamado 12 inteiro (traceback e registro)
    python tools/ver_erros.py --fechados    # inclui o que já foi corrigido

Precisa do gh (GitHub CLI) autenticado: `winget install GitHub.cli` e `gh auth login`.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys

REPOSITORIO_ERROS = "BigVirto/roger-eventos-erros"
ROTULO = "erro-automatico"

# O console do Windows abre em cp1252 e engole os acentos dos títulos vindos do GitHub.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def gh(*argumentos: str) -> str:
    if shutil.which("gh") is None:
        raise SystemExit(
            "O gh (GitHub CLI) nao esta instalado.\n"
            "  winget install GitHub.cli   e depois   gh auth login"
        )
    resultado = subprocess.run(
        ["gh", *argumentos], capture_output=True, text=True, encoding="utf-8"
    )
    if resultado.returncode != 0:
        raise SystemExit(f"gh falhou: {resultado.stderr.strip()[:400]}")
    return resultado.stdout


def contar_ocorrencias(issue: dict) -> int:
    """Quantas vezes o defeito aconteceu.

    A primeira vez está no corpo e cada repetição virou um comentário com a contagem
    daquela rajada. Somar os números é o que transforma "3 comentários" em "aconteceu
    57 vezes" — a diferença entre um chamado curioso e um chamado urgente.
    """
    total = 0
    for texto in [issue.get("body") or ""] + [c.get("body", "") for c in issue.get("comments", [])]:
        achado = re.search(r"\|\s*Vezes\s*\|\s*(\d+)\s*\|", texto)
        if achado:
            total += int(achado.group(1))
    return total or 1


def versoes(issue: dict) -> str:
    marcas = sorted(
        r["name"][1:] for r in issue.get("labels", []) if re.fullmatch(r"v[\d.]+", r["name"])
    )
    return ", ".join(marcas) or "?"


def listar(incluir_fechados: bool) -> int:
    estado = "all" if incluir_fechados else "open"
    bruto = gh(
        "issue", "list", "-R", REPOSITORIO_ERROS, "--label", ROTULO, "--state", estado,
        # `body` é obrigatório aqui: a primeira ocorrência do defeito está no corpo do
        # chamado, e só as repetições viram comentário. Sem ele a contagem começa errada.
        "--limit", "100", "--json", "number,title,state,body,createdAt,updatedAt,labels,comments",
    )
    issues = json.loads(bruto)
    if not issues:
        print("Nenhum erro registrado. O app esta se comportando.")
        return 0

    issues.sort(key=contar_ocorrencias, reverse=True)
    print(f"{len(issues)} chamado(s) em {REPOSITORIO_ERROS}, do que mais dói para o que menos:\n")

    for issue in issues:
        estado_txt = "" if issue["state"] == "OPEN" else "  [fechado]"
        print(f"#{issue['number']:<4} {contar_ocorrencias(issue):>5}x   {issue['title']}")
        print(
            f"      versoes: {versoes(issue)}   ultimo: {issue['updatedAt'][:10]}"
            f"   repeticoes: {len(issue.get('comments', []))}{estado_txt}"
        )
    print(f"\nPara ver um inteiro:  python tools/ver_erros.py {issues[0]['number']}")
    return 0


def detalhar(numero: int) -> int:
    print(
        gh(
            "issue", "view", str(numero), "-R", REPOSITORIO_ERROS,
            "--comments",
        )
    )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Le os erros enviados pelo app.")
    parser.add_argument("numero", nargs="?", type=int, help="numero do chamado a abrir")
    parser.add_argument("--fechados", action="store_true", help="inclui os ja corrigidos")
    args = parser.parse_args()

    sys.exit(detalhar(args.numero) if args.numero else listar(args.fechados))
