"""Leitura de playlists/faixas públicas do Spotify pela página pública (sem credencial).

Não usa a API oficial de propósito: desde 2026 ela exige assinatura Premium ativa do dono
da credencial e não devolve playlists editoriais (Top Brasil e afins) — justamente as que o
Rogério mais usa. A página pública de embed devolve nome, artista e duração de todas elas.

Nunca baixa áudio daqui: o Spotify é só a fonte da LISTA. O áudio vem do YouTube.
"""

import json
import re
import urllib.request

URL_EMBED = "https://open.spotify.com/embed/{tipo}/{id}"
_CABECALHOS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
_RE_NEXT_DATA = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)

# A página separa múltiplos artistas com espaços unicode incomuns; normalizamos para vírgula.
_RE_SEPARADOR_ARTISTAS = re.compile(r"[,     ]+\s*")

# O embed devolve a lista em blocos; se vier exatamente num desses tamanhos, pode estar cortada.
_TAMANHOS_SUSPEITOS = {50, 100}


class SpotifyIndisponivel(RuntimeError):
    """A página pública não pôde ser lida ou mudou de formato."""


def _buscar_entidade(tipo: str, spotify_id: str) -> dict:
    url = URL_EMBED.format(tipo=tipo, id=spotify_id)
    requisicao = urllib.request.Request(url, headers=_CABECALHOS)
    try:
        html = urllib.request.urlopen(requisicao, timeout=30).read().decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        raise SpotifyIndisponivel(f"não consegui abrir a página do Spotify: {exc}") from exc

    correspondencia = _RE_NEXT_DATA.search(html)
    if not correspondencia:
        raise SpotifyIndisponivel(
            "o Spotify mudou o formato da página — precisa atualizar core/spotify.py"
        )

    dados = json.loads(correspondencia.group(1))
    try:
        return dados["props"]["pageProps"]["state"]["data"]["entity"]
    except KeyError as exc:
        raise SpotifyIndisponivel(
            "não encontrei os dados da playlist na página — formato mudou"
        ) from exc


def _normalizar_artistas(subtitle: str | None) -> str:
    if not subtitle:
        return ""
    partes = [p.strip() for p in _RE_SEPARADOR_ARTISTAS.split(subtitle) if p.strip()]
    return ", ".join(partes)


def _faixa_para_dict(item: dict) -> dict:
    return {
        "artista": _normalizar_artistas(item.get("subtitle")),
        "faixa": item.get("title"),
        "duracao_ms": item.get("duration"),
    }


def listar_faixas_playlist(spotify_id: str) -> tuple[str, list[dict], bool]:
    """Retorna (nome_da_playlist, faixas, possivelmente_truncada)."""
    entidade = _buscar_entidade("playlist", spotify_id)
    nome = entidade.get("name") or "Playlist do Spotify"
    faixas = [_faixa_para_dict(i) for i in entidade.get("trackList", []) if i.get("title")]
    return nome, faixas, len(faixas) in _TAMANHOS_SUSPEITOS


def obter_faixa(spotify_id: str) -> dict:
    """Retorna os dados de uma única faixa do Spotify."""
    entidade = _buscar_entidade("track", spotify_id)
    lista = entidade.get("trackList") or []
    if lista:
        return _faixa_para_dict(lista[0])
    return {
        "artista": _normalizar_artistas(entidade.get("subtitle")),
        "faixa": entidade.get("name") or entidade.get("title"),
        "duracao_ms": entidade.get("duration"),
    }


def listar_faixas_album(spotify_id: str) -> tuple[str, list[dict], bool]:
    """Retorna (nome_do_album, faixas, possivelmente_truncada)."""
    entidade = _buscar_entidade("album", spotify_id)
    nome = entidade.get("name") or "Álbum do Spotify"
    faixas = [_faixa_para_dict(i) for i in entidade.get("trackList", []) if i.get("title")]
    return nome, faixas, len(faixas) in _TAMANHOS_SUSPEITOS
