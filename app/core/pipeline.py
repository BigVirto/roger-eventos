"""Orquestra o fluxo único de link: detecta origem, resolve faixas e baixa em MP3 320kbps.

A GUI só chama `processar_link`; toda a decisão (Spotify x YouTube x nome livre,
playlist x faixa única, correspondência por duração) fica aqui.

Dois canais de retorno para a interface:
- `progresso_callback(texto)`: o que está acontecendo agora, em português
- `percentual_callback(0..1)`: quanto do trabalho total já foi feito
"""

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core import matcher, metadata, organizer, registro, spotify, youtube
from core.link_detector import Origem, extrair_spotify, identificar_origem


TENTATIVAS = 3
ESPERA_ENTRE_TENTATIVAS_S = (2, 5)


class CancelamentoSolicitado(Exception):
    """O usuário clicou em Cancelar. Não é erro — não deve virar linha vermelha no log."""


def _checar_cancelamento(cancelar: threading.Event | None) -> None:
    if cancelar is not None and cancelar.is_set():
        raise CancelamentoSolicitado()


@dataclass
class ResultadoFaixa:
    nome: str
    caminho: str | None
    sucesso: bool
    incerto: bool = False
    erro: str | None = None
    pulado: bool = False  # já estava baixado


@dataclass
class ResultadoProcessamento:
    faixas: list[ResultadoFaixa] = field(default_factory=list)

    @property
    def falhas(self) -> list[ResultadoFaixa]:
        return [f for f in self.faixas if not f.sucesso]

    @property
    def incertas(self) -> list[ResultadoFaixa]:
        return [f for f in self.faixas if f.sucesso and f.incerto]

    @property
    def pulados(self) -> list[ResultadoFaixa]:
        return [f for f in self.faixas if f.pulado]

    @property
    def baixados(self) -> list[ResultadoFaixa]:
        return [f for f in self.faixas if f.sucesso and not f.pulado]


def _ja_existe(caminho: Path) -> bool:
    """Arquivo já baixado e não truncado. Evita rebaixar playlist inteira ao repetir."""
    return caminho.exists() and caminho.stat().st_size > 100_000


def _limpar_parciais(pasta: Path, nome_base: str) -> None:
    """Remove todo resto de uma tentativa interrompida, preservando só o MP3 completo.

    Lista o que sobra em vez de enumerar extensões: além do `.part`, o yt-dlp deixa
    o áudio bruto (`.m4a`, `.webm`) e a miniatura da capa (`.webp`, `.jpg`), e uma
    lista fixa sempre esquece alguma.
    """
    for resto in pasta.glob(f"{glob_escape(nome_base)}.*"):
        if resto.suffix.lower() == ".mp3" and resto.stat().st_size > 100_000:
            continue  # download completo: preservar
        resto.unlink(missing_ok=True)


def glob_escape(texto: str) -> str:
    """Neutraliza [ ] ? * em nomes de música para o glob não interpretá-los como padrão."""
    return "".join(f"[{c}]" if c in "[]?*" else c for c in texto)


def _com_retentativa(operacao: Callable[[], object], eh_definitivo: Callable[[Exception], bool]):
    """Repete uma operação em falhas passageiras. Não insiste no que já é definitivo."""
    ultimo: Exception | None = None
    for tentativa in range(TENTATIVAS):
        try:
            return operacao()
        except CancelamentoSolicitado:
            raise  # pedido do usuário: sai na hora, sem repetir
        except Exception as exc:  # noqa: BLE001
            ultimo = exc
            if eh_definitivo(exc) or tentativa == TENTATIVAS - 1:
                raise
            time.sleep(ESPERA_ENTRE_TENTATIVAS_S[min(tentativa, len(ESPERA_ENTRE_TENTATIVAS_S) - 1)])
    raise ultimo  # type: ignore[misc]


class _Progresso:
    """Converte os eventos do yt-dlp em fração 0..1 do trabalho total."""

    def __init__(
        self,
        total_itens: int,
        callback: Callable[[float], None] | None,
        cancelar: threading.Event | None = None,
    ):
        self.total = max(total_itens, 1)
        self.callback = callback
        self.cancelar = cancelar
        self.concluidos = 0

    def _emitir(self, fracao_do_item: float) -> None:
        if self.callback:
            self.callback(min((self.concluidos + fracao_do_item) / self.total, 1.0))

    def hook_ytdlp(self, evento: dict) -> None:
        # O hook é o único ponto que roda durante o download de um arquivo grande;
        # sem checar aqui, cancelar só teria efeito ao terminar a faixa atual.
        _checar_cancelamento(self.cancelar)

        if evento.get("status") == "downloading":
            total = evento.get("total_bytes") or evento.get("total_bytes_estimate")
            baixado = evento.get("downloaded_bytes") or 0
            self._emitir(baixado / total if total else 0.0)
        elif evento.get("status") == "finished":
            self._emitir(1.0)

    def item_concluido(self) -> None:
        self.concluidos += 1
        self._emitir(0.0)


def _baixar_faixa_spotify(
    artista: str,
    titulo: str,
    duracao_ms: int,
    pasta: Path,
    progresso: _Progresso,
    album: str | None = None,
    cancelar: threading.Event | None = None,
) -> ResultadoFaixa:
    _checar_cancelamento(cancelar)
    nome_exibicao = f"{titulo} - {artista}"
    nome_arquivo = organizer.nome_arquivo_faixa(artista, titulo)
    destino = pasta / f"{nome_arquivo}.mp3"

    if _ja_existe(destino):
        return ResultadoFaixa(nome_exibicao, str(destino), True, pulado=True)

    # Downloads feitos antes de 2026-08-07 usavam "Artista - Música". Reconhecê-los
    # evita baixar de novo tudo que o Rogério já tem.
    antigo = pasta / f"{organizer.nome_arquivo_faixa_legado(artista, titulo)}.mp3"
    if _ja_existe(antigo):
        return ResultadoFaixa(nome_exibicao, str(antigo), True, pulado=True)

    try:
        candidatos = youtube.buscar_candidatos(f"{artista} {titulo}")
        melhor = matcher.escolher_melhor_candidato(candidatos, duracao_ms)
        if melhor is None:
            return ResultadoFaixa(nome_exibicao, None, False, erro="não achei no YouTube")

        def baixar():
            _limpar_parciais(pasta, nome_arquivo)
            return youtube.baixar_audio(
                melhor["url"], pasta, nome_arquivo=nome_arquivo,
                progresso_callback=progresso.hook_ytdlp,
            )

        caminho = _com_retentativa(baixar, youtube.e_bloqueio_definitivo)

        # Sobrescreve o que o yt-dlp gravou: os dados do Spotify são exatos, o título
        # do vídeo do YouTube costuma vir sujo ("... (Official Video) [HD]").
        try:
            metadata.gravar_tags(Path(caminho), artista, titulo, album)
        except Exception as exc:  # noqa: BLE001 - áudio já está salvo; tag é um extra
            registro.aviso(f"não consegui gravar as tags de '{nome_exibicao}': {exc}")

        if melhor["incerto"]:
            registro.aviso(
                f"'{nome_exibicao}': melhor opção difere {melhor['diferenca_s']:.0f}s da "
                f"duração do Spotify — pode ser a versão errada ({melhor['titulo']})"
            )
        return ResultadoFaixa(nome_exibicao, str(caminho), True, incerto=melhor["incerto"])
    except CancelamentoSolicitado:
        _limpar_parciais(pasta, nome_arquivo)
        raise
    except Exception as exc:  # noqa: BLE001 - vira linha de erro na tela
        registro.erro(f"falhou ao baixar '{nome_exibicao}'", exc)
        return ResultadoFaixa(nome_exibicao, None, False, erro=str(exc))


def processar_link(
    texto: str,
    progresso_callback: Callable[[str], None] | None = None,
    percentual_callback: Callable[[float], None] | None = None,
    cancelar: threading.Event | None = None,
) -> ResultadoProcessamento:
    """Processa o texto colado pelo usuário e baixa a(s) faixa(s) correspondente(s).

    `cancelar`: quando acionado, interrompe assim que possível (inclusive no meio de um
    download) e levanta CancelamentoSolicitado, deixando os parciais limpos.
    """

    def avisar(msg: str) -> None:
        if progresso_callback:
            progresso_callback(msg)

    origem = identificar_origem(texto)
    registro.info(f"pedido recebido ({origem.value}): {texto[:200]}")
    resultado = ResultadoProcessamento()

    if origem == Origem.SPOTIFY:
        tipo, spotify_id = extrair_spotify(texto)

        if tipo == "track":
            avisar("Lendo a faixa no Spotify...")
            faixa = spotify.obter_faixa(spotify_id)
            progresso = _Progresso(1, percentual_callback, cancelar)
            avisar(f"Procurando no YouTube: {faixa['artista']} - {faixa['faixa']}")
            resultado.faixas.append(
                _baixar_faixa_spotify(
                    faixa["artista"], faixa["faixa"], faixa["duracao_ms"],
                    organizer.obter_pasta_downloads(), progresso, cancelar=cancelar,
                )
            )
        else:
            avisar("Lendo a lista no Spotify...")
            listar = spotify.listar_faixas_album if tipo == "album" else spotify.listar_faixas_playlist
            nome, faixas, truncada = listar(spotify_id)
            avisar(f"{nome}: {len(faixas)} faixa(s). Começando...")
            if truncada:
                avisar("(se a playlist tiver mais que isso, confira o total no final)")

            pasta = organizer.pasta_para_playlist(nome)
            progresso = _Progresso(len(faixas), percentual_callback, cancelar)
            for i, faixa in enumerate(faixas, start=1):
                avisar(f"[{i}/{len(faixas)}] {faixa['artista']} - {faixa['faixa']}")
                r = _baixar_faixa_spotify(
                    faixa["artista"], faixa["faixa"], faixa["duracao_ms"], pasta, progresso,
                    album=nome,  # agrupa a playlist como álbum no software de DJ
                    cancelar=cancelar,
                )
                if r.pulado:
                    avisar("   já estava baixada, pulando")
                resultado.faixas.append(r)
                progresso.item_concluido()

    elif origem == Origem.YOUTUBE:
        if youtube.eh_playlist(texto):
            avisar("Lendo a playlist do YouTube...")
            itens = youtube.listar_itens_playlist(texto)
            pasta = organizer.pasta_para_playlist(f"Playlist YouTube ({len(itens)} faixas)")
            progresso = _Progresso(len(itens), percentual_callback, cancelar)
            avisar(f"{len(itens)} vídeo(s). Começando...")

            for i, item in enumerate(itens, start=1):
                _checar_cancelamento(cancelar)
                avisar(f"[{i}/{len(itens)}] {item['titulo']}")
                nome_arquivo = organizer.nome_seguro(item["titulo"])
                destino = pasta / f"{nome_arquivo}.mp3"

                if _ja_existe(destino):
                    avisar("   já estava baixada, pulando")
                    resultado.faixas.append(
                        ResultadoFaixa(item["titulo"], str(destino), True, pulado=True)
                    )
                    progresso.item_concluido()
                    continue

                try:
                    def baixar(url=item["url"], nome=nome_arquivo):
                        _limpar_parciais(pasta, nome)
                        return youtube.baixar_audio(
                            url, pasta, nome_arquivo=nome, progresso_callback=progresso.hook_ytdlp
                        )

                    caminho = _com_retentativa(baixar, youtube.e_bloqueio_definitivo)
                    resultado.faixas.append(ResultadoFaixa(item["titulo"], str(caminho), True))
                except CancelamentoSolicitado:
                    _limpar_parciais(pasta, nome_arquivo)
                    raise
                except Exception as exc:  # noqa: BLE001
                    registro.erro(f"falhou ao baixar '{item['titulo']}'", exc)
                    resultado.faixas.append(ResultadoFaixa(item["titulo"], None, False, erro=str(exc)))
                progresso.item_concluido()
        else:
            avisar("Baixando o vídeo...")
            progresso = _Progresso(1, percentual_callback, cancelar)
            try:
                caminho = youtube.baixar_audio(
                    texto, organizer.obter_pasta_downloads(), progresso_callback=progresso.hook_ytdlp
                )
                resultado.faixas.append(ResultadoFaixa(Path(caminho).stem, str(caminho), True))
            except Exception as exc:  # noqa: BLE001
                resultado.faixas.append(ResultadoFaixa(texto, None, False, erro=str(exc)))

    else:  # TEXTO_LIVRE
        avisar(f"Procurando no YouTube: {texto}")
        progresso = _Progresso(1, percentual_callback, cancelar)
        candidatos = youtube.buscar_candidatos(texto, limite=1)
        if not candidatos:
            resultado.faixas.append(ResultadoFaixa(texto, None, False, erro="nenhum resultado"))
        else:
            melhor = candidatos[0]
            avisar(f"Baixando: {melhor['titulo']}")
            try:
                caminho = youtube.baixar_audio(
                    melhor["url"],
                    organizer.obter_pasta_downloads(),
                    progresso_callback=progresso.hook_ytdlp,
                )
                resultado.faixas.append(ResultadoFaixa(melhor["titulo"], str(caminho), True))
            except CancelamentoSolicitado:
                raise
            except Exception as exc:  # noqa: BLE001
                registro.erro(f"falhou ao baixar '{melhor['titulo']}'", exc)
                resultado.faixas.append(ResultadoFaixa(melhor["titulo"], None, False, erro=str(exc)))

    if percentual_callback:
        percentual_callback(1.0)

    registro.info(
        f"concluído: {len(resultado.baixados)} baixada(s), {len(resultado.pulados)} já existia(m), "
        f"{len(resultado.falhas)} falhou(ram), {len(resultado.incertas)} para conferir"
    )
    return resultado
