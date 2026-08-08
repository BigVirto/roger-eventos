"""Ponto de entrada do app de download de músicas do Roger Eventos.

Não precisa de credenciais nem de arquivo de configuração: o Spotify é lido pela
página pública e o YouTube pelo yt-dlp, ambos sem autenticação.

ATENÇÃO ao mexer neste arquivo: ele é o único que fica congelado dentro do .exe e
NÃO pode ser corrigido por atualização automática. Tudo que estiver aqui só muda
com instalador novo. Manter o mínimo possível — a lógica de verdade mora em core/.

Modos de execução:
  (sem argumentos)  abre a janela
  --autoteste       verifica ffmpeg, Spotify e YouTube e sai, sem abrir a janela.
                    Serve para validar o .exe empacotado antes de entregar.
  --reverter        apaga a atualização automática e volta ao código embutido no .exe.
                    Saída manual para quando o código novo abre mas funciona mal.
"""

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- Bootstrap: precisa vir ANTES de qualquer import de core/ ou gui/ -----------------
# É aqui que uma versão mais nova do app, baixada numa execução anterior, passa a valer.
from core import atualizador_app  # noqa: E402

if "--reverter" in sys.argv:
    # recusar=True e essencial: sem isso o app rebaixaria a mesma versao em ate 6 horas
    # e o problema voltaria sozinho. Uma versao mais nova continua sendo aceita.
    revertida = atualizador_app.descartar(recusar=True)
    if revertida:
        print(f"Atualizacao {revertida} removida e marcada como ruim; nao sera baixada de novo.")
        print("O app voltou a versao embutida no executavel.")
    else:
        print("Nao havia atualizacao instalada. O app ja estava na versao do executavel.")
    sys.exit(0)

VERSAO_ATUALIZADA = atualizador_app.preparar_sys_path()
VERSAO_ATIVA = VERSAO_ATUALIZADA or atualizador_app.versao_embutida()

# A partir daqui, os imports de core/ e gui/ já vêm da versão ativa.
from core import atualizador  # noqa: E402

atualizador.preparar_sys_path()


def _autoteste() -> int:
    """Verifica as três dependências externas do app. Retorna 0 se tudo passou."""
    falhas = 0

    from core.organizer import obter_pasta_downloads
    from core.youtube import DENO_LOCATION, FFMPEG_LOCATION, buscar_candidatos

    origem_app = "atualizado" if VERSAO_ATUALIZADA else "embutido"
    print(f"[INFO]  app versao {VERSAO_ATIVA} ({origem_app})")

    for rotulo, caminho in (("ffmpeg", FFMPEG_LOCATION), ("deno", DENO_LOCATION)):
        if caminho and Path(caminho).exists():
            print(f"[OK]    {rotulo} encontrado: {caminho}")
        else:
            print(f"[FALHA] {rotulo} NAO encontrado (valor: {caminho})")
            falhas += 1

    print(f"[INFO]  musicas serao salvas em: {obter_pasta_downloads()}")

    try:
        from core.spotify import listar_faixas_playlist

        nome, faixas, _ = listar_faixas_playlist("37i9dQZF1DX0FOF1IUWK1W")
        print(f"[OK]    Spotify lido: '{nome}' com {len(faixas)} faixas")
    except Exception as exc:  # noqa: BLE001
        print(f"[FALHA] Spotify: {type(exc).__name__}: {exc}")
        falhas += 1

    try:
        candidatos = buscar_candidatos("Queen Bohemian Rhapsody", limite=1)
        print(f"[OK]    YouTube busca: {candidatos[0]['titulo']}")
    except Exception as exc:  # noqa: BLE001
        print(f"[FALHA] YouTube: {type(exc).__name__}: {exc}")
        falhas += 1
        candidatos = []

    # Download de verdade: é o caminho que mais quebrou (ffmpeg, bloqueio, caminhos do
    # pacote). Validar só busca dá falsa sensação de que o app funciona.
    if candidatos:
        import tempfile

        from core.youtube import baixar_audio

        try:
            inicio = time.time()
            with tempfile.TemporaryDirectory() as tmp:
                arquivo = baixar_audio(candidatos[0]["url"], Path(tmp))
                tamanho_mb = arquivo.stat().st_size / 1024 / 1024
                from core.youtube import _cliente_que_funciona as cliente

                print(
                    f"[OK]    Download real: {tamanho_mb:.1f} MB em {time.time() - inicio:.0f}s "
                    f"(cliente: {cliente or 'padrão'})"
                )
                # Tags e capa: sem isso os arquivos entram desorganizados no Serato/Rekordbox.
                from core.metadata import gravar_tags, ler_tags

                gravar_tags(arquivo, "Artista Teste", "Titulo Teste", "Album Teste")
                tags = ler_tags(arquivo)
                if tags.get("artista") == "Artista Teste" and tags.get("album") == "Album Teste":
                    print(f"[OK]    Tags ID3 gravadas e lidas de volta (capa: {tags['tem_capa']})")
                else:
                    print(f"[FALHA] Tags ID3 não conferem: {tags}")
                    falhas += 1
        except Exception as exc:  # noqa: BLE001
            print(f"[FALHA] Download real: {type(exc).__name__}: {str(exc)[:150]}")
            falhas += 1

    import yt_dlp

    origem = "atualizado" if atualizador.caminho_yt_dlp_atualizado() else "embutido"
    print(f"[INFO]  yt-dlp {yt_dlp.version.__version__} ({origem})")

    print("RESULTADO: TUDO OK" if falhas == 0 else f"RESULTADO: {falhas} FALHA(S)")
    return 0 if falhas == 0 else 1


def _abrir_janela() -> None:
    """Abre a janela, descartando a atualização se ela impedir o app de subir.

    Terceira camada de proteção do atualizador: o pacote passou na checagem de import
    mas estourou erro ao iniciar. Descartar aqui garante que a próxima abertura volte
    ao código embutido, em vez de deixar o Rogério com um app que não abre.
    """
    try:
        from gui.main_window import iniciar

        iniciar()
    except Exception:
        if VERSAO_ATUALIZADA:
            atualizador_app.descartar(recusar=True)
            print(
                f"A atualizacao {VERSAO_ATUALIZADA} falhou ao iniciar e foi removida. "
                "Abra o app novamente."
            )
        raise


if __name__ == "__main__":
    if "--autoteste" in sys.argv:
        sys.exit(_autoteste())

    from core import registro

    registro.info(f"App iniciado — versão {VERSAO_ATIVA} ({'atualizada' if VERSAO_ATUALIZADA else 'embutida'})")

    # Verificações de atualização em segundo plano: nunca atrasam a abertura da janela.
    # As duas só passam a valer na próxima abertura.
    threading.Thread(target=atualizador.verificar_e_atualizar, daemon=True).start()
    threading.Thread(target=atualizador_app.verificar_e_atualizar, daemon=True).start()

    _abrir_janela()
