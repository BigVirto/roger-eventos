"""Busca e download de áudio no YouTube via yt-dlp."""

import sys
from pathlib import Path
from typing import Callable

import yt_dlp

QUALIDADE_MP3 = "320"

# O YouTube bloqueia downloads não autenticados com "Sign in to confirm you're not a bot".
# A saída recomendada pelo próprio yt-dlp é reusar os cookies de um navegador onde o
# usuário já está logado. Tentamos os navegadores em ordem e guardamos o que funcionar,
# para o Rogério não precisar configurar nada.
NAVEGADORES = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi")
_navegador_que_funciona: str | None = None

# O YouTube aplica regras de bloqueio diferentes conforme o tipo de aparelho que se
# conecta. Medido em 2026-08-07 com o IP já marcado: 'android' baixou normalmente
# (13s) enquanto tv_embedded/android_vr levavam "not a bot" e os demais falhavam.
# Tentar vários em ordem evita depender de cookies — que no Windows moderno o yt-dlp
# quase nunca consegue ler (banco travado com o navegador aberto, ou App-Bound Encryption).
CLIENTES = ("android", "ios", "android_vr", "tv_embedded", "mweb", "web")
_cliente_que_funciona: str | None = None

# Sem limitar as tentativas, um bloqueio 429 do YouTube faz o yt-dlp repetir em silêncio
# com esperas crescentes — chegou a 322 segundos travado antes de desistir. Preferimos
# falhar rápido e explicar ao usuário a esperar cinco minutos sem retorno.
OPCOES_REDE = {
    # Força IPv4. Medido em 2026-08-07: a rota IPv6 para o YouTube fica pendurada até
    # estourar o timeout antes de cair para IPv4 — a MESMA busca levava 161,5s no modo
    # padrão e 1,9s forçando IPv4 (85x). Era esta a causa real da lentidão, não o
    # bloqueio anti-bot. Redes só-IPv6 são raras em uso doméstico no Windows.
    "source_address": "0.0.0.0",
    "socket_timeout": 20,
    "retries": 2,
    "extractor_retries": 1,
    "fragment_retries": 2,
}


def _localizar_binario(nome: str) -> str | None:
    """Acha um executável empacotado em app/bin/ (dev ou dentro do .exe)."""
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(__file__).resolve().parent.parent  # app/
    candidato = base / "bin" / nome
    return str(candidato) if candidato.exists() else None


def _arquivo_cookies() -> str | None:
    """Procura um cookies.txt ao lado do .exe (escape manual quando o navegador falha).

    Em Windows moderno o yt-dlp muitas vezes não consegue ler os cookies do Chrome/Edge
    (banco travado com o navegador aberto, ou criptografia App-Bound). Um cookies.txt
    exportado por extensão resolve sem depender disso.
    """
    base = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
    arquivo = base / "cookies.txt"
    return str(arquivo) if arquivo.exists() else None


def _e_bloqueio_de_bot(erro: Exception) -> bool:
    msg = str(erro).lower()
    return "not a bot" in msg or "sign in to confirm" in msg or "cookies" in msg


def e_bloqueio_definitivo(erro: Exception) -> bool:
    """Diz se insistir é inútil.

    Quando `_executar_com_fallback` desiste, já tentou todos os clientes, o cookies.txt
    e todos os navegadores — repetir só faria o Rogério esperar à toa. O mesmo vale para
    vídeo removido ou privado.
    """
    msg = str(erro).lower()
    if isinstance(erro, RuntimeError) and "bloqueando os downloads" in msg:
        return True
    return any(
        t in msg for t in ("private video", "video unavailable", "removed by the uploader",
                           "não achei no youtube", "members-only")
    )


def _opcoes_cliente(cliente: str) -> dict:
    return {"extractor_args": {"youtube": {"player_client": [cliente]}}}


def _executar_com_fallback(acao: Callable[[dict], object]) -> object:
    """Roda `acao(opcoes_extra)` tentando contornar o bloqueio anti-bot do YouTube.

    Ordem: cliente que já funcionou → cada cliente da lista → cookies.txt → navegadores.
    Só desiste depois de tudo isso, e aí com uma mensagem em português.
    """
    global _cliente_que_funciona, _navegador_que_funciona

    if _cliente_que_funciona:
        try:
            return acao(_opcoes_cliente(_cliente_que_funciona))
        except Exception as exc:  # noqa: BLE001
            if not _e_bloqueio_de_bot(exc):
                raise
            _cliente_que_funciona = None  # o que funcionava caiu: recomeça a busca

    ultimo_erro: Exception | None = None
    for cliente in CLIENTES:
        try:
            resultado = acao(_opcoes_cliente(cliente))
            _cliente_que_funciona = cliente
            return resultado
        except Exception as exc:  # noqa: BLE001
            if not _e_bloqueio_de_bot(exc):
                raise
            ultimo_erro = exc

    cookies = _arquivo_cookies()
    if cookies:
        try:
            return acao({"cookiefile": cookies})
        except Exception:  # noqa: BLE001 - arquivo velho/inválido: seguimos tentando
            pass

    if _navegador_que_funciona:
        try:
            return acao({"cookiesfrombrowser": (_navegador_que_funciona, None, None, None)})
        except Exception:  # noqa: BLE001
            _navegador_que_funciona = None

    for navegador in NAVEGADORES:
        try:
            resultado = acao({"cookiesfrombrowser": (navegador, None, None, None)})
            _navegador_que_funciona = navegador
            return resultado
        except Exception:  # noqa: BLE001 - navegador ausente, fechado ou sem sessão
            continue

    raise RuntimeError(
        "O YouTube está bloqueando os downloads no momento. "
        "Isso costuma passar sozinho em algumas horas. "
        "Se persistir, tente de outra rede (por exemplo, o 4G do celular)."
    ) from ultimo_erro


FFMPEG_LOCATION = _localizar_binario("ffmpeg.exe")

# O yt-dlp precisa de um runtime JavaScript para resolver os desafios do YouTube.
# Sem ele cai em caminhos alternativos mais lentos e frágeis. Empacotamos o Deno junto.
DENO_LOCATION = _localizar_binario("deno.exe")
if DENO_LOCATION:
    OPCOES_REDE["js_runtimes"] = {"deno": {"path": DENO_LOCATION}}


def buscar_candidatos(termo: str, limite: int = 5) -> list[dict]:
    """Busca no YouTube e retorna candidatos com título, url e duração (segundos)."""
    def acao(extra: dict):
        opcoes = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            **OPCOES_REDE,
            **extra,
        }
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            return ydl.extract_info(f"ytsearch{limite}:{termo}", download=False)

    resultado = _executar_com_fallback(acao)

    candidatos = []
    for entrada in resultado.get("entries", []) or []:
        if not entrada:
            continue
        candidatos.append(
            {
                "titulo": entrada.get("title"),
                "url": entrada.get("url") or entrada.get("webpage_url"),
                "duracao_s": entrada.get("duration"),
                "canal": entrada.get("uploader") or entrada.get("channel"),
            }
        )
    return candidatos


def eh_playlist(url: str) -> bool:
    """Diz se a URL é de playlist olhando só o endereço — sem consultar a rede.

    Antes isto fazia uma chamada ao YouTube que levava vários segundos e era repetida
    logo depois pelo download. Para vídeo avulso (o caso mais comum) o ganho é direto.
    """
    return "list=" in url and "watch?v=" not in url


def listar_itens_playlist(url: str) -> list[dict]:
    """Lista os vídeos de uma playlist do YouTube sem baixar."""
    def acao(extra: dict):
        opcoes = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            **OPCOES_REDE,
            **extra,
        }
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            return ydl.extract_info(url, download=False)

    info = _executar_com_fallback(acao)
    itens = []
    for entrada in info.get("entries", []) or []:
        if not entrada:
            continue
        itens.append(
            {
                "titulo": entrada.get("title"),
                "url": entrada.get("url") or entrada.get("webpage_url") or entrada.get("id"),
                "duracao_s": entrada.get("duration"),
            }
        )
    return itens


def baixar_audio(
    url: str,
    pasta_destino: Path,
    nome_arquivo: str | None = None,
    progresso_callback: Callable[[dict], None] | None = None,
) -> Path:
    """Baixa o áudio de um vídeo do YouTube como MP3 320kbps na pasta destino."""
    pasta_destino.mkdir(parents=True, exist_ok=True)
    template_saida = str(pasta_destino / (nome_arquivo or "%(title)s")) + ".%(ext)s"

    def acao(extra: dict):
        opcoes = {
            "format": "bestaudio/best",
            "outtmpl": template_saida,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": QUALIDADE_MP3,
                },
                # Sem estes, o MP3 sai sem artista/título/capa e entra desorganizado
                # no Serato/Rekordbox. Para faixas do Spotify o pipeline sobrescreve
                # depois com os dados exatos (core/metadata.py).
                {"key": "FFmpegMetadata", "add_metadata": True},
                {"key": "EmbedThumbnail", "already_have_thumbnail": False},
            ],
            "writethumbnail": True,
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            **OPCOES_REDE,
            **extra,
        }
        if FFMPEG_LOCATION:
            opcoes["ffmpeg_location"] = FFMPEG_LOCATION
        if progresso_callback:
            opcoes["progress_hooks"] = [progresso_callback]

        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=True)
            return Path(ydl.prepare_filename(info)).with_suffix(".mp3")

    return _executar_com_fallback(acao)
