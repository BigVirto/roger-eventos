"""Busca e download de áudio e vídeo no YouTube via yt-dlp."""

import sys
from pathlib import Path
from typing import Callable

import yt_dlp

from core import registro

QUALIDADE_MP3 = "320"

# Vídeo: 1080p em H.264 + AAC dentro de MP4. Não é "a melhor qualidade" de propósito —
# o YouTube entrega VP9/AV1 dentro de WebM quando não se pede nada, e VirtualDJ, Serato
# Video e Resolume não abrem esses formatos. Um arquivo que não toca no telão não serve.
ALTURA_MAXIMA_VIDEO = 1080

# Abaixo disto o vídeo fica visivelmente ruim num telão. Serve de piso: preferimos trocar
# de codec a entregar 360p.
ALTURA_MINIMA_BOA = 720

# Dois ramos, e o segundo é ordenado por `format_sort` (abaixo).
#
# 1) o ideal, e o que acontece na prática: H.264 de 720p ao teto, com áudio AAC. Toca em
#    qualquer software de DJ, em TV e em projetor, sem conversão nenhuma.
# 2) quando não existe H.264 em boa resolução, vale o que houver — e aí quem decide é o
#    format_sort, que põe resolução na frente do codec.
_MODELO_FORMATO_VIDEO = (
    "bestvideo[vcodec^=avc1][height<=?{h}][height>={min}]+bestaudio[acodec^=mp4a]/"
    "bestvideo[height<=?{h}]+bestaudio/best[height<=?{h}]/best"
)

# Ordem de desempate, do mais importante para o menos. Duas lições viraram esta linha:
#
# - `res` PRIMEIRO: pedir H.264 acima de tudo fazia o app escolher 360p em H.264 no lugar
#   de 1080p em VP9. Codec certo, imagem impossível de projetar.
# - `acodec:aac` explícito: sem isso o yt-dlp juntava vídeo H.264 com áudio **opus**, que
#   a maioria dos programas de DJ não toca. Pego pelo autoteste, não a olho nu.
_ORDEM_FORMATO_VIDEO = ("res:{h}", "vcodec:h264", "acodec:aac", "ext:mp4")

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
CLIENTES = ("android", "ios", "android_vr", "web_embedded", "mweb", "web")

# Para VÍDEO a ordem tem que ser outra. Medido em 2026-08-08: `android` e `mweb` — os
# únicos que passavam no bloqueio — oferecem **só 360p**. Não é limite do seletor de
# formato: é a lista que o YouTube entrega para aquele aparelho. `web_embedded` oferece
# H.264 até 1080p. Sem esta lista separada, todo vídeo saía borrado no telão.
CLIENTES_VIDEO = ("web_embedded", "tv", "web_safari", "android", "ios", "mweb", "web")

# Memória do que funcionou, SEPARADA por tipo de mídia. Uma memória só era armadilha:
# baixar uma música memorizava `android`, e o vídeo seguinte reusava esse cliente e vinha
# em 360p sem ninguém perceber.
_memoria_cliente: dict[str, str | None] = {"audio": None, "video": None}

# Mantido para o autoteste congelado dentro do .exe 1.2.0, que importa este nome.
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
    # O YouTube entrega mídia em fragmentos (DASH). Baixar alguns em paralelo acelera
    # bastante o vídeo, que é grande, e ajuda também no áudio. Mantido baixo de propósito:
    # muitas conexões simultâneas do mesmo IP é justamente o que dispara o 429.
    "concurrent_fragment_downloads": 4,
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


def _executar_com_fallback(acao: Callable[[dict], object], midia: str = "audio") -> object:
    """Roda `acao(opcoes_extra)` tentando contornar o bloqueio anti-bot do YouTube.

    Ordem: cliente que já funcionou → cada cliente da lista → cookies.txt → navegadores.
    Só desiste depois de tudo isso, e aí com uma mensagem em português.

    `midia` escolhe a lista e a memória: vídeo precisa de clientes que ofereçam alta
    resolução, áudio precisa dos que passam no bloqueio mais rápido.
    """
    global _cliente_que_funciona, _navegador_que_funciona

    clientes = CLIENTES_VIDEO if midia == "video" else CLIENTES
    lembrado = _memoria_cliente.get(midia)

    def memorizar(cliente: str | None) -> None:
        global _cliente_que_funciona
        _memoria_cliente[midia] = cliente
        if midia == "audio":
            _cliente_que_funciona = cliente  # compatibilidade com o .exe antigo

    if lembrado:
        try:
            return acao(_opcoes_cliente(lembrado))
        except Exception as exc:  # noqa: BLE001
            if not _e_bloqueio_de_bot(exc):
                raise
            memorizar(None)  # o que funcionava caiu: recomeça a busca

    ultimo_erro: Exception | None = None
    for cliente in clientes:
        try:
            resultado = acao(_opcoes_cliente(cliente))
            memorizar(cliente)
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

# Usado pelo autoteste para conferir os codecs do MP4 gerado. Já vai empacotado no .exe
# junto com o ffmpeg (build.spec), então não custa nada disponibilizar.
FFPROBE_LOCATION = _localizar_binario("ffprobe.exe")

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


def _caminho_final(ydl, info: dict, extensao: str) -> Path:
    """Descobre onde o arquivo realmente foi parar depois dos pós-processadores.

    Não dá para deduzir do template: `prepare_filename` devolve o nome do fluxo baixado
    (`.webm`, `.m4a`), e quem muda a extensão é o pós-processamento — extrair MP3 ou juntar
    imagem e som num MP4. O yt-dlp anota o caminho definitivo em `requested_downloads`;
    o `with_suffix` fica só como plano B para o caso de essa chave não vir.
    """
    baixados = info.get("requested_downloads") or []
    if baixados and baixados[0].get("filepath"):
        return Path(baixados[0]["filepath"])
    return Path(ydl.prepare_filename(info)).with_suffix(extensao)


def _resolucao_baixada(info: dict) -> int:
    """Altura do fluxo de vídeo que o yt-dlp acabou escolhendo. 0 se não for vídeo."""
    fluxos = info.get("requested_formats") or [info]
    return max((f.get("height") or 0) for f in fluxos)


def _baixar(
    url: str,
    pasta_destino: Path,
    nome_arquivo: str | None,
    extensao: str,
    opcoes_da_midia: dict,
    progresso_callback: Callable[[dict], None] | None = None,
    pos_processamento_callback: Callable[[dict], None] | None = None,
    midia: str = "audio",
) -> Path:
    """Base comum de `baixar_audio` e `baixar_video`: só o formato e o destino mudam."""
    pasta_destino.mkdir(parents=True, exist_ok=True)
    template_saida = str(pasta_destino / (nome_arquivo or "%(title)s")) + ".%(ext)s"

    def acao(extra: dict):
        opcoes = {
            "outtmpl": template_saida,
            "quiet": True,
            # `quiet` sozinho não cala a barra de progresso do yt-dlp: ela continua indo
            # para o console e deixa a saída do autoteste ilegível. Quem mostra progresso
            # aqui é a janela, via progress_hooks.
            "noprogress": True,
            "no_warnings": True,
            "noplaylist": True,
            **opcoes_da_midia,
            **OPCOES_REDE,
            **extra,
        }
        if FFMPEG_LOCATION:
            opcoes["ffmpeg_location"] = FFMPEG_LOCATION
        if progresso_callback:
            opcoes["progress_hooks"] = [progresso_callback]
        if pos_processamento_callback:
            opcoes["postprocessor_hooks"] = [pos_processamento_callback]

        with yt_dlp.YoutubeDL(opcoes) as ydl:
            info = ydl.extract_info(url, download=True)
            if midia == "video":
                # Registrar a resolução obtida. Foi assim que um bug passou despercebido:
                # o app entregava 360p, o download "dava certo", e só dava para saber
                # abrindo o arquivo. Agora fica no registro.txt de toda entrega.
                altura = _resolucao_baixada(info)
                cliente = _memoria_cliente.get("video") or "padrão"
                if altura and altura < ALTURA_MINIMA_BOA:
                    registro.aviso(
                        f"vídeo baixado em apenas {altura}p (cliente {cliente}) — "
                        "o YouTube não ofereceu resolução melhor para este vídeo"
                    )
                else:
                    registro.info(f"vídeo baixado em {altura or '?'}p (cliente {cliente})")
            return _caminho_final(ydl, info, extensao)

    return _executar_com_fallback(acao, midia=midia)


def baixar_audio(
    url: str,
    pasta_destino: Path,
    nome_arquivo: str | None = None,
    progresso_callback: Callable[[dict], None] | None = None,
    pos_processamento_callback: Callable[[dict], None] | None = None,
) -> Path:
    """Baixa o áudio de um vídeo do YouTube como MP3 320kbps na pasta destino."""
    return _baixar(
        url,
        pasta_destino,
        nome_arquivo,
        ".mp3",
        {
            "format": "bestaudio/best",
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
        },
        progresso_callback,
        pos_processamento_callback,
    )


def obter_titulo(url: str) -> str | None:
    """Descobre o título de um vídeo sem baixá-lo. `None` se não der.

    Custa ~2s de rede, e é o que permite saber o nome do arquivo ANTES do download:
    sem isso não dá para checar se ele já está na pasta nem para saber o que apagar
    quando o usuário cancela no meio. Vale a pena para vídeo, que pesa centenas de MB;
    para música o download inteiro leva ~10s e a consulta não se pagaria.
    """
    def acao(extra: dict):
        opcoes = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
            "noplaylist": True,
            **OPCOES_REDE,
            **extra,
        }
        with yt_dlp.YoutubeDL(opcoes) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        # midia="video" de propósito: esta consulta só existe no caminho do vídeo, e usar
        # a lista de áudio aqui memorizaria um cliente de 360p logo antes do download.
        return (_executar_com_fallback(acao, midia="video") or {}).get("title")
    except Exception:  # noqa: BLE001 - é um extra; sem título o download segue normal
        return None


def baixar_video(
    url: str,
    pasta_destino: Path,
    nome_arquivo: str | None = None,
    progresso_callback: Callable[[dict], None] | None = None,
    pos_processamento_callback: Callable[[dict], None] | None = None,
    altura_maxima: int = ALTURA_MAXIMA_VIDEO,
) -> Path:
    """Baixa o vídeo completo como MP4 (H.264 + AAC), pronto para tocar no telão."""
    return _baixar(
        url,
        pasta_destino,
        nome_arquivo,
        ".mp4",
        {
            "format": _MODELO_FORMATO_VIDEO.format(h=altura_maxima, min=ALTURA_MINIMA_BOA),
            "format_sort": [s.format(h=altura_maxima) for s in _ORDEM_FORMATO_VIDEO],
            "merge_output_format": "mp4",
            "postprocessors": [
                # Se o seletor tiver caído no último ramo (WebM/VP9), converte o container
                # para MP4. Sem isto um arquivo que o software de DJ não abre passaria
                # como sucesso e só falharia na hora do evento.
                {"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"},
                {"key": "FFmpegMetadata", "add_metadata": True},
                # Miniatura embutida: é o que faz o Explorer mostrar a capa do vídeo.
                {"key": "EmbedThumbnail", "already_have_thumbnail": False},
            ],
            "writethumbnail": True,
        },
        progresso_callback,
        pos_processamento_callback,
        midia="video",
    )
