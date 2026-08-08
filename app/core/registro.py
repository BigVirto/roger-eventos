"""Arquivo de log ao lado do .exe, para diagnosticar problemas na máquina do Rogério.

Sem isto, quando algo falha na casa dele a única fonte é o relato verbal. Com o arquivo,
ele manda `registro.txt` e dá para ver exatamente qual faixa falhou e por quê.

Escreve em português e sem jargão onde der: quem lê primeiro é o Vitor, mas o Rogério
pode abrir o arquivo e entender o que aconteceu.
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

    O botão "Erros" na janela abre este arquivo, então o Rogério nunca precisa saber
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

    return _logger


def info(mensagem: str) -> None:
    obter().info(mensagem)


def aviso(mensagem: str) -> None:
    obter().warning(mensagem)


def erro(mensagem: str, excecao: BaseException | None = None) -> None:
    """Registra erro. Com exceção, inclui o traceback — é o que permite achar a causa."""
    obter().error(mensagem, exc_info=excecao)
