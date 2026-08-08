"""Autoteste do app: verifica as dependências externas e os dois caminhos de download.

Mora em `core/` de propósito. Antes vivia dentro de `main.py`, que é o único arquivo
congelado no `.exe` — o portão de entrega ficava justamente fora do alcance da
atualização automática, e todo ajuste no teste exigia instalador novo. Daqui, o teste
evolui junto com o resto do código.

Rodar: `python app/main.py --autoteste`, ou `RogerEventos-BaixadorDeMusicas.exe --autoteste`.
Termina com `RESULTADO: TUDO OK` (saída 0) ou `RESULTADO: N FALHA(S)` (saída 1).
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path

# Vídeo curto e estável, do próprio canal do YouTube. Baixar um clipe de 4 minutos em
# 1080p só para testar gastaria minutos e centenas de MB a cada rodada.
URL_VIDEO_CURTO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"  # "Me at the zoo", 19s
ALTURA_TESTE_VIDEO = 480  # o que se testa é o formato e o merge, não a resolução


class _Placar:
    def __init__(self) -> None:
        self.falhas = 0

    def ok(self, msg: str) -> None:
        print(f"[OK]    {msg}")

    def info(self, msg: str) -> None:
        print(f"[INFO]  {msg}")

    def falha(self, msg: str) -> None:
        print(f"[FALHA] {msg}")
        self.falhas += 1


def _codecs(caminho: Path) -> list[str]:
    """Lista os codecs das faixas do arquivo, usando o ffprobe empacotado.

    É o que separa "baixou um arquivo" de "baixou um arquivo que toca no telão": um WebM
    com VP9 tem o mesmo tamanho e o mesmo nome, e só falharia na hora do evento.
    """
    from core.youtube import FFPROBE_LOCATION

    if not FFPROBE_LOCATION:
        return []
    saida = subprocess.run(
        [FFPROBE_LOCATION, "-v", "error", "-show_entries", "stream=codec_name",
         "-of", "json", str(caminho)],
        capture_output=True, text=True, timeout=60,
    )
    if saida.returncode != 0:
        return []
    fluxos = json.loads(saida.stdout or "{}").get("streams", []) or []
    return [f.get("codec_name", "") for f in fluxos]


def _testar_dependencias(placar: _Placar) -> None:
    from core.organizer import obter_pasta_downloads, obter_pasta_videos
    from core.youtube import DENO_LOCATION, FFMPEG_LOCATION, FFPROBE_LOCATION

    for rotulo, caminho in (("ffmpeg", FFMPEG_LOCATION), ("ffprobe", FFPROBE_LOCATION),
                            ("deno", DENO_LOCATION)):
        if caminho and Path(caminho).exists():
            placar.ok(f"{rotulo} encontrado: {caminho}")
        else:
            placar.falha(f"{rotulo} NAO encontrado (valor: {caminho})")

    placar.info(f"musicas serao salvas em: {obter_pasta_downloads()}")
    placar.info(f"videos serao salvos em: {obter_pasta_videos()}")


def _testar_spotify(placar: _Placar) -> None:
    try:
        from core.spotify import listar_faixas_playlist

        nome, faixas, _ = listar_faixas_playlist("37i9dQZF1DX0FOF1IUWK1W")
        placar.ok(f"Spotify lido: '{nome}' com {len(faixas)} faixas")
    except Exception as exc:  # noqa: BLE001
        placar.falha(f"Spotify: {type(exc).__name__}: {exc}")


def _testar_musica(placar: _Placar) -> None:
    """Busca + download real + tags. É o caminho que mais quebrou historicamente."""
    from core.youtube import buscar_candidatos

    try:
        candidatos = buscar_candidatos("Queen Bohemian Rhapsody", limite=1)
        placar.ok(f"YouTube busca: {candidatos[0]['titulo']}")
    except Exception as exc:  # noqa: BLE001
        placar.falha(f"YouTube: {type(exc).__name__}: {exc}")
        return

    from core.metadata import gravar_tags, ler_tags
    from core.youtube import baixar_audio

    try:
        inicio = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = baixar_audio(candidatos[0]["url"], Path(tmp))
            from core.youtube import _cliente_que_funciona as cliente

            placar.ok(
                f"Download de musica: {arquivo.stat().st_size / 1024 / 1024:.1f} MB em "
                f"{time.time() - inicio:.0f}s (cliente: {cliente or 'padrão'})"
            )
            # Tags e capa: sem isso os arquivos entram desorganizados no Serato/Rekordbox.
            gravar_tags(arquivo, "Artista Teste", "Titulo Teste", "Album Teste")
            tags = ler_tags(arquivo)
            if tags.get("artista") == "Artista Teste" and tags.get("album") == "Album Teste":
                placar.ok(f"Tags ID3 gravadas e lidas de volta (capa: {tags['tem_capa']})")
            else:
                placar.falha(f"Tags ID3 não conferem: {tags}")
    except Exception as exc:  # noqa: BLE001
        placar.falha(f"Download de musica: {type(exc).__name__}: {str(exc)[:150]}")


def _testar_video(placar: _Placar) -> None:
    """Baixa um vídeo curto e confere que o resultado é MP4 com H.264 + AAC."""
    from core.metadata import gravar_tags, ler_tags
    from core.youtube import baixar_video

    try:
        inicio = time.time()
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = baixar_video(
                URL_VIDEO_CURTO, Path(tmp), altura_maxima=ALTURA_TESTE_VIDEO
            )
            if not arquivo.exists():
                placar.falha(f"Download de video: arquivo não encontrado em {arquivo}")
                return

            placar.ok(
                f"Download de video: {arquivo.name} "
                f"({arquivo.stat().st_size / 1024 / 1024:.1f} MB em {time.time() - inicio:.0f}s)"
            )

            if arquivo.suffix.lower() != ".mp4":
                placar.falha(f"Video nao saiu em MP4 (saiu {arquivo.suffix})")

            # A checagem que importa: VP9/AV1 em WebM baixa igual, tem o mesmo nome e o
            # mesmo tamanho — e nao toca no VirtualDJ/Serato Video.
            codecs = _codecs(arquivo)
            if not codecs:
                placar.falha("Nao consegui ler os codecs do video (ffprobe falhou)")
            elif "h264" in codecs and "aac" in codecs:
                placar.ok(f"Codecs compativeis com software de DJ: {', '.join(codecs)}")
            else:
                placar.falha(
                    f"Codecs INCOMPATIVEIS: {', '.join(codecs) or 'nenhum'} "
                    "(esperado h264 + aac)"
                )

            gravar_tags(arquivo, "Artista Teste", "Titulo Teste", "Album Teste")
            tags = ler_tags(arquivo)
            if tags.get("artista") == "Artista Teste" and tags.get("album") == "Album Teste":
                placar.ok("Tags MP4 gravadas e lidas de volta")
            else:
                placar.falha(f"Tags MP4 não conferem: {tags}")
    except Exception as exc:  # noqa: BLE001
        placar.falha(f"Download de video: {type(exc).__name__}: {str(exc)[:150]}")


def executar(versao_ativa: str, foi_atualizado: bool) -> int:
    """Roda o autoteste inteiro. Retorna 0 se tudo passou, 1 se algo falhou."""
    placar = _Placar()
    placar.info(f"app versao {versao_ativa} ({'atualizado' if foi_atualizado else 'embutido'})")

    _testar_dependencias(placar)
    _testar_spotify(placar)
    _testar_musica(placar)
    _testar_video(placar)

    import yt_dlp

    from core import atualizador

    origem = "atualizado" if atualizador.caminho_yt_dlp_atualizado() else "embutido"
    placar.info(f"yt-dlp {yt_dlp.version.__version__} ({origem})")

    print("RESULTADO: TUDO OK" if placar.falhas == 0 else f"RESULTADO: {placar.falhas} FALHA(S)")
    return 0 if placar.falhas == 0 else 1
