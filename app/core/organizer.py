"""Organiza pastas por playlist/evento, nomes de arquivo seguros e a pasta de destino.

A pasta onde as músicas são salvas é escolhida pelo usuário e guardada entre sessões
(`configuracao.json` ao lado do .exe). Sem escolha salva, usa uma pasta ao lado do
executável — nunca um caminho derivado de __file__, que no modo empacotado aponta
para o diretório temporário do PyInstaller e faria os downloads sumirem.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

_CARACTERES_INVALIDOS = re.compile(r'[<>:"/\\|?*]')
NOME_PASTA_PADRAO = "Músicas Baixadas"
NOME_PASTA_VIDEOS_PADRAO = "Vídeos Baixados"
ARQUIVO_CONFIG = "configuracao.json"


def _pasta_base() -> Path:
    """Onde o executável está instalado."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def pasta_dados() -> Path:
    """Onde o app grava config, log e atualizações.

    Separado do local de instalação de propósito: com instalador, o .exe pode ficar
    numa pasta onde o Windows bloqueia escrita. AppData é sempre gravável pelo usuário.
    """
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RogerEventos"
        base.mkdir(parents=True, exist_ok=True)
        return base
    return _pasta_base()


def _caminho_config() -> Path:
    return pasta_dados() / ARQUIVO_CONFIG


def _pasta_do_windows(chave_registro: str, nome_reserva: str) -> Path | None:
    """Pasta pessoal do usuário (Músicas, Vídeos...), lida do registro.

    Não dá para assumir `~/Music` ou `~/Videos`: o usuário pode tê-las movido (comum com
    OneDrive), e o nome em disco varia com o idioma. O registro é a fonte confiável.
    """
    try:
        import winreg

        chave = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as k:
            caminho = Path(winreg.QueryValueEx(k, chave_registro)[0])
        return caminho if caminho.exists() else None
    except Exception:  # noqa: BLE001 - qualquer falha cai no plano B
        candidato = Path.home() / nome_reserva
        return candidato if candidato.exists() else None


def pasta_downloads_padrao() -> Path:
    """Destino padrão: dentro de 'Músicas' do Windows, onde o Rogério espera achar.

    Antes ficava ao lado do .exe, o que funcionava quando o app era um arquivo solto —
    mas com instalador o executável vai para uma pasta de programas, e música não é
    lugar de ficar lá.
    """
    musicas = _pasta_do_windows("My Music", "Music")
    if musicas:
        return musicas / "Roger Eventos"
    return _pasta_base() / NOME_PASTA_PADRAO


def pasta_videos_padrao() -> Path:
    """Destino padrão dos vídeos: 'Vídeos\\Roger Eventos'.

    Separado das músicas de propósito. Serato, Rekordbox e VirtualDJ varrem a pasta de
    música para montar a biblioteca — um MP4 de 200 MB no meio dos MP3 aparece como faixa
    e bagunça o acervo de trabalho dele.
    """
    videos = _pasta_do_windows("My Video", "Videos")
    if videos:
        return videos / "Roger Eventos"
    return _pasta_base() / NOME_PASTA_VIDEOS_PADRAO


def obter_config(chave: str, padrao=None):
    """Lê uma preferência salva. Config ilegível vale como config vazia."""
    try:
        return json.loads(_caminho_config().read_text(encoding="utf-8")).get(chave, padrao)
    except (OSError, ValueError, AttributeError):
        return padrao


def definir_config(chave: str, valor) -> None:
    """Salva uma preferência preservando as demais."""
    try:
        config = json.loads(_caminho_config().read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            config = {}
    except (OSError, ValueError):
        config = {}
    config[chave] = valor
    _caminho_config().write_text(
        json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def obter_pasta_downloads() -> Path:
    """Pasta escolhida pelo usuário, ou a padrão se não houver escolha utilizável."""
    escolhida = obter_config("pasta_downloads")
    if escolhida:
        caminho = Path(escolhida)
        # Se o destino sumiu (pendrive removido, pasta apagada), cair no padrão
        # é melhor do que estourar erro na cara do usuário.
        if caminho.parent.exists():
            return caminho
    return pasta_downloads_padrao()


def definir_pasta_downloads(caminho: Path) -> None:
    """Salva a escolha do usuário para as próximas sessões."""
    definir_config("pasta_downloads", str(caminho))


def obter_pasta_videos() -> Path:
    """Pasta de vídeos escolhida pelo usuário, ou a padrão se não houver escolha utilizável."""
    escolhida = obter_config("pasta_videos")
    if escolhida:
        caminho = Path(escolhida)
        if caminho.parent.exists():
            return caminho
    return pasta_videos_padrao()


def definir_pasta_videos(caminho: Path) -> None:
    """Salva a escolha do usuário para as próximas sessões."""
    definir_config("pasta_videos", str(caminho))


def espaco_livre(pasta: Path) -> int:
    """Bytes livres no disco da pasta. 0 quando não dá para saber.

    Uma playlist de vídeo passa fácil dos 5 GB; encher o disco no meio deixaria arquivos
    truncados e o Windows reclamando. Melhor avisar antes de começar.
    """
    try:
        alvo = pasta
        while not alvo.exists() and alvo != alvo.parent:
            alvo = alvo.parent  # a pasta de destino pode ainda não ter sido criada
        return shutil.disk_usage(alvo).free
    except OSError:
        return 0


def abrir_pasta(caminho: Path) -> None:
    """Abre a pasta no Explorer do Windows."""
    caminho.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(caminho)])


def nome_seguro(nome: str) -> str:
    """Remove caracteres inválidos para nomes de arquivo/pasta no Windows."""
    limpo = _CARACTERES_INVALIDOS.sub("", nome).strip()
    return limpo.rstrip(". ") or "sem_nome"


def pasta_para_playlist(nome_playlist: str, base: Path | None = None) -> Path:
    """Cria (se preciso) e retorna a pasta de destino para uma playlist/evento."""
    pasta = (base or obter_pasta_downloads()) / nome_seguro(nome_playlist)
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def nome_arquivo_faixa(artista: str, faixa: str) -> str:
    """Nome do arquivo com a MÚSICA primeiro — é por ela que se procura numa festa."""
    return nome_seguro(f"{faixa} - {artista}")


def nome_arquivo_faixa_legado(artista: str, faixa: str) -> str:
    """Formato antigo (artista primeiro), usado até 2026-08-07.

    Mantido só para reconhecer downloads anteriores e não baixá-los de novo.
    """
    return nome_seguro(f"{artista} - {faixa}")
