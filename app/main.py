"""Ponto de entrada do app de download de músicas e vídeos do Roger Eventos.

Não precisa de credenciais nem de arquivo de configuração: o Spotify é lido pela
página pública e o YouTube pelo yt-dlp, ambos sem autenticação.

ATENÇÃO ao mexer neste arquivo: ele é o único que fica congelado dentro do .exe e
NÃO pode ser corrigido por atualização automática. Tudo que estiver aqui só muda
com instalador novo. Manter o mínimo possível — a lógica de verdade mora em core/.

Modos de execução:
  (sem argumentos)  abre a janela
  --autoteste       verifica ffmpeg, Spotify, YouTube e os downloads de música e vídeo,
                    e sai sem abrir a janela. O teste em si mora em core/autoteste.py,
                    para poder ser corrigido sem instalador novo.
  --reverter        apaga a atualização automática e volta ao código embutido no .exe.
                    Saída manual para quando o código novo abre mas funciona mal.
"""

import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --- Bootstrap: precisa vir ANTES de qualquer import de core/ ou gui/ -----------------
# É aqui que uma versão mais nova do app, baixada numa execução anterior, passa a valer.
from core import atualizador_app  # noqa: E402

# Guarda a versão do executável antes da troca. Depois dela, `core.versao` passa a ser a
# do pacote baixado, e não haveria mais como saber o que veio dentro do .exe.
os.environ[atualizador_app.VARIAVEL_VERSAO_EXE] = atualizador_app.versao_embutida()

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
    """Roda o autoteste, que mora em core/ para poder evoluir sem instalador novo."""
    try:
        from core import autoteste
    except ImportError as exc:
        print(f"[FALHA] core/autoteste.py não encontrado ({exc}).")
        print("RESULTADO: 1 FALHA(S)")
        return 1

    return autoteste.executar(VERSAO_ATIVA, bool(VERSAO_ATUALIZADA))


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
