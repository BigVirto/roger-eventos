"""Arquivo de log ao lado do .exe, para diagnosticar problemas na máquina do usuário.

Sem isto, quando algo falha na casa dele a única fonte é o relato verbal. Com o arquivo,
dá para ver exatamente qual faixa falhou e por quê.

Desde 2026-08-08 ele não depende mais de o usuário mandar o arquivo: tudo que passa por
`erro()` também vira um relatório enviado sozinho para quem mantém o app — ver
`core/ocorrencias.py`.

Escreve em português e sem jargão onde der: quem lê primeiro é quem mantém o app, mas o
usuário pode abrir o arquivo e entender o que aconteceu.
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

NOME_ARQUIVO = "registro.txt"
TAMANHO_MAXIMO_BYTES = 2 * 1024 * 1024  # 2 MB: o suficiente para várias sessões
COPIAS_ANTIGAS = 2

_logger: logging.Logger | None = None


def caminho_log() -> Path:
    """Fica junto com os demais dados do app (AppData), não na pasta de instalação.

    O botão "Erros" na janela abre este arquivo, então o usuário nunca precisa saber
    onde ele está.
    """
    from core.organizer import pasta_dados

    return pasta_dados() / NOME_ARQUIVO


def obter() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    _logger = logging.getLogger("roger_eventos")
    _logger.setLevel(logging.INFO)
    _logger.propagate = False

    try:
        manipulador = RotatingFileHandler(
            caminho_log(), maxBytes=TAMANHO_MAXIMO_BYTES,
            backupCount=COPIAS_ANTIGAS, encoding="utf-8",
        )
        manipulador.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(message)s", datefmt="%d/%m/%Y %H:%M:%S")
        )
        _logger.addHandler(manipulador)
    except OSError:
        # Sem permissão de escrita (ex: rodando de um pendrive protegido): o app
        # continua funcionando, só fica sem registro.
        _logger.addHandler(logging.NullHandler())

    _pendurar_relator(_logger)
    return _logger


def _pendurar_relator(logger: logging.Logger) -> None:
    """Faz todo `erro()` daqui virar também um relatório enviado a quem mantém o app.

    Pendurar no logger em vez de chamar o relator em cada ponto de falha: as chamadas a
    `erro()` já existem espalhadas por `pipeline.py`, `youtube.py` e pela janela, e as
    que forem escritas no futuro entram cobertas sem ninguém lembrar de nada.

    Só ERROR sobe — `info()` e `aviso()` ficam abaixo do nível do manipulador. É o que
    permite ao próprio relator usar `aviso()` para contar que falhou em enviar sem se
    reportar em círculo.
    """
    try:
        from core.ocorrencias import ManipuladorDeOcorrencias

        logger.addHandler(ManipuladorDeOcorrencias())
    except Exception:  # noqa: BLE001 - sem relator o app segue igual, só sem avisar
        pass


def info(mensagem: str) -> None:
    obter().info(mensagem)


def aviso(mensagem: str) -> None:
    obter().warning(mensagem)


def erro(mensagem: str, excecao: BaseException | None = None) -> None:
    """Registra erro. Com exceção, inclui o traceback — é o que permite achar a causa."""
    obter().error(mensagem, exc_info=excecao)
