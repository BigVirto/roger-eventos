"""Grava tags nos arquivos baixados: ID3 nos MP3, tags do QuickTime nos MP4.

Sem isto os arquivos saem só com o nome — e Serato, Rekordbox e VirtualDJ organizam
a biblioteca lendo as tags, não o nome do arquivo. Para faixas vindas do Spotify temos
artista e título exatos, bem melhores que o título do vídeo do YouTube (que costuma vir
como "Artista - Música (Official Video) [HD] 4K").

`gravar_tags` e `ler_tags` despacham pela extensão do arquivo: quem chama não precisa
saber se está lidando com música ou vídeo.

Usa mutagen, que já vem junto por ser dependência do yt-dlp — não pesa no pacote.
"""

from pathlib import Path

from mutagen.id3 import APIC, TALB, TIT2, TPE1, ID3, ID3NoHeaderError
from mutagen.mp4 import MP4, MP4Cover

EXTENSOES_MP4 = (".mp4", ".m4v", ".m4a")


def gravar_tags(
    caminho: Path,
    artista: str,
    titulo: str,
    album: str | None = None,
    capa_bytes: bytes | None = None,
    capa_mime: str = "image/jpeg",
) -> None:
    """Escreve artista/título/álbum (e capa, se houver) no arquivo.

    Falhas aqui não devem derrubar o download: o arquivo já está no disco e serve, mesmo
    sem as tags. Quem chama decide se registra o aviso.
    """
    caminho = Path(caminho)
    if caminho.suffix.lower() in EXTENSOES_MP4:
        _gravar_tags_mp4(caminho, artista, titulo, album, capa_bytes, capa_mime)
    else:
        _gravar_tags_mp3(caminho, artista, titulo, album, capa_bytes, capa_mime)


def ler_tags(caminho: Path) -> dict:
    """Lê as tags de volta — usado pelo autoteste para confirmar que foram gravadas."""
    caminho = Path(caminho)
    if caminho.suffix.lower() in EXTENSOES_MP4:
        return _ler_tags_mp4(caminho)
    return _ler_tags_mp3(caminho)


# --------------------------------------------------------------------------- MP3 (ID3)


def _gravar_tags_mp3(caminho, artista, titulo, album, capa_bytes, capa_mime) -> None:
    try:
        tags = ID3(caminho)
    except ID3NoHeaderError:
        tags = ID3()

    tags.setall("TPE1", [TPE1(encoding=3, text=artista)])
    tags.setall("TIT2", [TIT2(encoding=3, text=titulo)])
    if album:
        tags.setall("TALB", [TALB(encoding=3, text=album)])
    if capa_bytes:
        tags.setall(
            "APIC",
            [APIC(encoding=3, mime=capa_mime, type=3, desc="Cover", data=capa_bytes)],
        )

    tags.save(caminho, v2_version=3)  # v2.3 é o que o Windows e os softwares de DJ leem melhor


def _ler_tags_mp3(caminho: Path) -> dict:
    try:
        tags = ID3(caminho)
    except (ID3NoHeaderError, OSError):
        return {}
    return {
        "artista": str(tags.get("TPE1", "")),
        "titulo": str(tags.get("TIT2", "")),
        "album": str(tags.get("TALB", "")),
        "tem_capa": bool(tags.getall("APIC")),
    }


# --------------------------------------------------------------------------- MP4

# O MP4 não usa ID3: as tags são átomos do QuickTime, com nomes iniciados por ©.
# É o que o Explorer do Windows e os softwares de vídeo leem.
_NOME, _ARTISTA, _ALBUM, _CAPA = "\xa9nam", "\xa9ART", "\xa9alb", "covr"


def _gravar_tags_mp4(caminho, artista, titulo, album, capa_bytes, capa_mime) -> None:
    arquivo = MP4(caminho)
    arquivo[_ARTISTA] = [artista]
    arquivo[_NOME] = [titulo]
    if album:
        arquivo[_ALBUM] = [album]
    if capa_bytes:
        formato = MP4Cover.FORMAT_PNG if "png" in capa_mime else MP4Cover.FORMAT_JPEG
        arquivo[_CAPA] = [MP4Cover(capa_bytes, imageformat=formato)]
    arquivo.save()


def _ler_tags_mp4(caminho: Path) -> dict:
    try:
        arquivo = MP4(caminho)
    except Exception:  # noqa: BLE001 - arquivo sem tags ou ilegível vale como vazio
        return {}

    def primeiro(chave: str) -> str:
        valores = arquivo.get(chave) or []
        return str(valores[0]) if valores else ""

    return {
        "artista": primeiro(_ARTISTA),
        "titulo": primeiro(_NOME),
        "album": primeiro(_ALBUM),
        "tem_capa": bool(arquivo.get(_CAPA)),
    }
