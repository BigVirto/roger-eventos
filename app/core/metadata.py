"""Grava tags ID3 nos MP3 baixados.

Sem isto os arquivos saem só com o nome — e Serato, Rekordbox e VirtualDJ organizam
a biblioteca lendo as tags, não o nome do arquivo. Para faixas vindas do Spotify temos
artista e título exatos, bem melhores que o título do vídeo do YouTube (que costuma vir
como "Artista - Música (Official Video) [HD] 4K").

Usa mutagen, que já vem junto por ser dependência do yt-dlp — não pesa no pacote.
"""

from pathlib import Path

from mutagen.id3 import APIC, TALB, TIT2, TPE1, ID3, ID3NoHeaderError


def gravar_tags(
    caminho_mp3: Path,
    artista: str,
    titulo: str,
    album: str | None = None,
    capa_bytes: bytes | None = None,
    capa_mime: str = "image/jpeg",
) -> None:
    """Escreve artista/título/álbum (e capa, se houver) no MP3.

    Falhas aqui não devem derrubar o download: o arquivo de áudio já está no disco e
    serve, mesmo sem as tags. Quem chama decide se registra o aviso.
    """
    try:
        tags = ID3(caminho_mp3)
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

    tags.save(caminho_mp3, v2_version=3)  # v2.3 é o que o Windows e os softwares de DJ leem melhor


def ler_tags(caminho_mp3: Path) -> dict:
    """Lê as tags de volta — usado pelo autoteste para confirmar que foram gravadas."""
    try:
        tags = ID3(caminho_mp3)
    except (ID3NoHeaderError, OSError):
        return {}
    return {
        "artista": str(tags.get("TPE1", "")),
        "titulo": str(tags.get("TIT2", "")),
        "album": str(tags.get("TALB", "")),
        "tem_capa": bool(tags.getall("APIC")),
    }
