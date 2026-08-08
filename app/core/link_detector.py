"""Identifica a origem de um texto colado pelo usuário: Spotify, YouTube ou nome livre."""

import re
from enum import Enum


class Origem(Enum):
    SPOTIFY = "spotify"
    YOUTUBE = "youtube"
    TEXTO_LIVRE = "texto_livre"


_RE_SPOTIFY = re.compile(r"open\.spotify\.com/(?:intl-\w+/)?(track|playlist|album)/([A-Za-z0-9]+)")
_RE_YOUTUBE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|playlist\?list=)|youtu\.be/)([A-Za-z0-9_-]+)"
)


def identificar_origem(texto: str) -> Origem:
    """Recebe o texto colado pelo usuário e diz de onde ele veio."""
    texto = texto.strip()
    if _RE_SPOTIFY.search(texto):
        return Origem.SPOTIFY
    if _RE_YOUTUBE.search(texto):
        return Origem.YOUTUBE
    return Origem.TEXTO_LIVRE


def extrair_spotify(texto: str) -> tuple[str, str] | None:
    """Retorna (tipo, id) para um link do Spotify, ex: ('playlist', '37i9dQZF1...')."""
    match = _RE_SPOTIFY.search(texto.strip())
    if not match:
        return None
    return match.group(1), match.group(2)
