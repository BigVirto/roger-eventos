"""Testa o relatório automático de erros sem precisar gerar o .exe.

Provoca erros de mentira pelo caminho REAL (`registro.erro()` -> manipulador -> fila ->
envio). Testar chamando o envio direto não valeria de nada: o que costuma quebrar é
justamente a ligação entre as peças.

Usar:
    python tools/testar_envio_erros.py                 # 1 erro, mostra a ficha montada
    python tools/testar_envio_erros.py --repetir 3     # confere o agrupamento
    python tools/testar_envio_erros.py --enviar        # manda de verdade para o receptor
    python tools/testar_envio_erros.py --autoteste     # só o envio de teste (abre e fecha)
    python tools/testar_envio_erros.py --limpar        # esvazia a fila local

Em modo desenvolvimento a fila fica em `ocorrencias/` na raiz do projeto (no .exe vai
para %LOCALAPPDATA%\\RogerEventos\\ocorrencias).
"""

import argparse
import getpass
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "app"))

from core import ocorrencias, registro  # noqa: E402


def provocar_erro(qual: int) -> None:
    """Estoura um erro de verdade para haver traceback autêntico na ficha."""
    try:
        caminho = Path.home() / "Music" / f"faixa {qual}.mp3"
        raise RuntimeError(f"falha fabricada ao baixar '{caminho}' (teste {qual})")
    except RuntimeError as exc:
        registro.erro(f"falhou ao baixar 'Faixa de Teste {qual}'", exc)


def mostrar_fila() -> list[dict]:
    fichas = []
    for arquivo in sorted(ocorrencias.pasta_ocorrencias().glob("*.json")):
        ficha = json.loads(arquivo.read_text(encoding="utf-8"))
        fichas.append(ficha)
        print(f"\n--- {arquivo.name} ---")
        print(f"  código do relatório: #{ficha['impressao_digital']}")
        print(f"  vezes: {ficha['ocorrencias']}")
        print(f"  tipo: {ficha['tipo']}")
        print(f"  mensagem: {ficha['mensagem']}")
        print(f"  app: {ficha['versao_app']} ({ficha['origem_codigo']})")
        print(f"  yt-dlp: {ficha['versao_ytdlp']} ({ficha['origem_ytdlp']})")
        print(f"  pedido: {ficha['pedido'] or '(nenhum)'}")
        print(f"  detalhe: {len(ficha['detalhe'])} caracteres")
        print(f"  registro: {len(ficha['registro'].splitlines())} linhas")
    return fichas


def conferir_mascaramento(fichas: list[dict]) -> int:
    """O único dado pessoal que passaria por aqui é o nome de usuário do Windows.

    Confere o texto inteiro da ficha, não só o traceback: caminho de download, mensagem
    e trecho do registro carregam `C:\\Users\\<nome>` com a mesma facilidade.
    """
    try:
        usuario = getpass.getuser()
    except Exception:  # noqa: BLE001
        print("\n[INFO]  sem nome de usuario para conferir")
        return 0

    vazando = [f for f in fichas if usuario.lower() in json.dumps(f, ensure_ascii=False).lower()]
    if vazando:
        print(f"\n[FALHA] o nome de usuario '{usuario}' aparece em {len(vazando)} ficha(s)")
        return 1
    print(f"\n[OK]    nome de usuario '{usuario}' nao aparece em nenhuma ficha")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Testa o envio automatico de erros.")
    parser.add_argument("--repetir", type=int, default=1, help="quantos erros iguais provocar")
    parser.add_argument("--enviar", action="store_true", help="manda a fila para o receptor")
    parser.add_argument("--autoteste", action="store_true", help="só o envio marcado como teste")
    parser.add_argument("--limpar", action="store_true", help="apaga a fila local e sai")
    args = parser.parse_args()

    pasta = ocorrencias.pasta_ocorrencias()

    if args.limpar:
        apagados = 0
        for arquivo in pasta.glob("*.json"):
            arquivo.unlink()
            apagados += 1
        print(f"[OK]    fila esvaziada ({apagados} arquivo(s)) em {pasta}")
        raise SystemExit(0)

    configurado = ocorrencias.esta_configurado()
    print(f"[INFO]  receptor: {'configurado' if configurado else 'URL_RECEPTOR VAZIO'}")
    print(f"[INFO]  envio ligado: {ocorrencias.envio_ligado()}")
    print(f"[INFO]  fila em: {pasta}")

    if args.autoteste:
        if not configurado:
            raise SystemExit("[FALHA] preencha URL_RECEPTOR em app/core/ocorrencias.py primeiro")
        print("[INFO]  enviando ocorrencia de teste...")
        print("[OK]    aceita pelo receptor" if ocorrencias.autoteste() else "[FALHA] recusada")
        raise SystemExit(0)

    for i in range(args.repetir):
        provocar_erro(i + 1)
    print(f"[INFO]  {args.repetir} erro(s) provocado(s)")

    fichas = mostrar_fila()
    falhas = 0

    esperado = 1 if args.repetir else 0
    if len(fichas) == esperado:
        print(f"\n[OK]    agrupamento: {args.repetir} erro(s) igual(is) viraram {len(fichas)} ficha")
    else:
        print(f"\n[FALHA] agrupamento: esperava {esperado} ficha, achei {len(fichas)}")
        falhas += 1

    if fichas and fichas[0]["ocorrencias"] != args.repetir:
        print(f"[FALHA] contagem: esperava {args.repetir}, achei {fichas[0]['ocorrencias']}")
        falhas += 1
    elif fichas:
        print(f"[OK]    contagem: {fichas[0]['ocorrencias']}x na mesma ficha")

    falhas += conferir_mascaramento(fichas)

    if args.enviar:
        if not configurado:
            print("\n[FALHA] nao da para enviar: URL_RECEPTOR esta vazio")
            falhas += 1
        else:
            enviados = ocorrencias.enviar_agora()
            print(f"\n[{'OK' if enviados else 'FALHA'}]    relatorios aceitos: {enviados}")
            falhas += 0 if enviados else 1

    print("\nRESULTADO: TUDO OK" if falhas == 0 else f"\nRESULTADO: {falhas} FALHA(S)")
    raise SystemExit(0 if falhas == 0 else 1)
