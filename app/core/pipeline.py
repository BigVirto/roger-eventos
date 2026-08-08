"""Orquestra o fluxo único de link: detecta origem, resolve faixas e baixa.

A GUI só chama `processar_link`; toda a decisão (Spotify x YouTube x nome livre,
playlist x faixa única, correspondência por duração) fica aqui. O que muda entre baixar
música (MP3 320kbps) e vídeo (MP4 1080p) está concentrado em `PerfilMidia`, para não
espalhar `if é vídeo` por todo o arquivo.

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

MUSICA = "musica"
VIDEO = "video"

# Estimativa grosseira para avisar o tamanho de uma playlist antes de começar: 1080p em
# H.264 dá por volta de 25 MB por minuto. Serve para a ordem de grandeza ("são 7 GB"),
# não para precisão — o número exato só sairia consultando cada vídeo, o que é lento.
MB_POR_MINUTO_VIDEO = 25
MARGEM_DISCO_BYTES = 500 * 1024 * 1024  # nunca encostar no disco cheio


@dataclass(frozen=True)
class PerfilMidia:
    """O que muda entre baixar música e baixar vídeo."""

    nome: str
    extensao: str
    rotulo: str              # "música" / "vídeo", para as mensagens na tela
    partes_por_item: int     # vídeo baixa dois fluxos: imagem e som
    baixar: Callable[..., Path]
    pasta: Callable[[], Path]
    escolher: Callable[[list[dict], int], dict | None]


PERFIS = {
    MUSICA: PerfilMidia(
        nome=MUSICA,
        extensao=".mp3",
        rotulo="música",
        partes_por_item=1,
        baixar=youtube.baixar_audio,
        pasta=organizer.obter_pasta_downloads,
        escolher=matcher.escolher_melhor_candidato,
    ),
    VIDEO: PerfilMidia(
        nome=VIDEO,
        extensao=".mp4",
        rotulo="vídeo",
        partes_por_item=2,
        baixar=youtube.baixar_video,
        pasta=organizer.obter_pasta_videos,
        escolher=matcher.escolher_melhor_clipe,
    ),
}


def obter_perfil(midia: str) -> PerfilMidia:
    return PERFIS.get(midia, PERFIS[MUSICA])


class CancelamentoSolicitado(Exception):
    """O usuário clicou em Cancelar. Não é erro — não deve virar linha vermelha no log."""


class EspacoInsuficiente(Exception):
    """Não cabe no disco o que ele pediu.

    Como o cancelamento, não é defeito do app: é uma condição da máquina que só ele pode
    resolver. Separada de `Exception` comum para não entrar no relatório automático de
    erros — um disco cheio viraria chamado para o Vitor sobre algo que ele não conserta.
    """


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


def _limpar_parciais(pasta: Path, nome_base: str, extensao: str = ".mp3") -> None:
    """Remove todo resto de uma tentativa interrompida, preservando só o arquivo final.

    Lista o que sobra em vez de enumerar extensões: além do `.part`, o yt-dlp deixa
    o áudio bruto (`.m4a`, `.webm`) e a miniatura da capa (`.webp`, `.jpg`), e uma
    lista fixa sempre esquece alguma.

    `extensao` NÃO tem valor fixo por um motivo sério: com `.mp3` cravado aqui, um MP4
    já pronto cairia na categoria "resto" e seria apagado — justamente ao cancelar ou ao
    repetir um download de vídeo. Sempre passar a extensão da mídia em curso.
    """
    for resto in pasta.glob(f"{glob_escape(nome_base)}.*"):
        if resto.suffix.lower() == extensao and resto.stat().st_size > 100_000:
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
        partes_por_item: int = 1,
        aviso_callback: Callable[[str], None] | None = None,
    ):
        self.total = max(total_itens, 1)
        self.callback = callback
        self.cancelar = cancelar
        # Vídeo chega em dois arquivos (imagem e som), cada um indo de 0 a 100%. Somando
        # direto, a barra subia, zerava e subia de novo. Guardando a fração POR ARQUIVO e
        # dividindo pelo número de partes, ela anda uma vez só, do começo ao fim.
        self.partes_por_item = max(partes_por_item, 1)
        self.aviso_callback = aviso_callback
        self.concluidos = 0
        self._fracoes: dict[str, float] = {}

    def _emitir(self, fracao_do_item: float) -> None:
        if self.callback:
            self.callback(min((self.concluidos + fracao_do_item) / self.total, 1.0))

    def _emitir_parciais(self) -> None:
        soma = sum(self._fracoes.values())
        self._emitir(min(soma / self.partes_por_item, 1.0))

    def hook_ytdlp(self, evento: dict) -> None:
        # O hook é o único ponto que roda durante o download de um arquivo grande;
        # sem checar aqui, cancelar só teria efeito ao terminar a faixa atual.
        _checar_cancelamento(self.cancelar)

        arquivo = evento.get("filename") or evento.get("tmpfilename") or ""
        if evento.get("status") == "downloading":
            total = evento.get("total_bytes") or evento.get("total_bytes_estimate")
            baixado = evento.get("downloaded_bytes") or 0
            self._fracoes[arquivo] = (baixado / total) if total else 0.0
            self._emitir_parciais()
        elif evento.get("status") == "finished":
            self._fracoes[arquivo] = 1.0
            self._emitir_parciais()

    def hook_pos_processamento(self, evento: dict) -> None:
        """Avisa durante o que acontece DEPOIS do download.

        Juntar imagem e som num arquivo de 200 MB leva alguns segundos com a barra parada
        em 100% — sem uma palavra na tela, parece que travou.
        """
        _checar_cancelamento(self.cancelar)
        if not self.aviso_callback or evento.get("status") != "started":
            return
        etapa = (evento.get("postprocessor") or "").lower()
        if "merger" in etapa:
            self.aviso_callback("   juntando imagem e som...")
        elif "remux" in etapa or "convert" in etapa:
            self.aviso_callback("   convertendo para MP4...")
        elif "extractaudio" in etapa:
            self.aviso_callback("   convertendo para MP3...")

    def item_concluido(self) -> None:
        self.concluidos += 1
        self._fracoes.clear()  # o próximo item começa do zero
        self._emitir(0.0)


def _baixar_faixa_spotify(
    artista: str,
    titulo: str,
    duracao_ms: int,
    pasta: Path,
    progresso: _Progresso,
    album: str | None = None,
    cancelar: threading.Event | None = None,
    perfil: PerfilMidia = PERFIS[MUSICA],
) -> ResultadoFaixa:
    _checar_cancelamento(cancelar)
    nome_exibicao = f"{titulo} - {artista}"
    nome_arquivo = organizer.nome_arquivo_faixa(artista, titulo)
    destino = pasta / f"{nome_arquivo}{perfil.extensao}"

    if _ja_existe(destino):
        return ResultadoFaixa(nome_exibicao, str(destino), True, pulado=True)

    # Downloads feitos antes de 2026-08-07 usavam "Artista - Música". Reconhecê-los
    # evita baixar de novo tudo que o Rogério já tem.
    antigo = pasta / f"{organizer.nome_arquivo_faixa_legado(artista, titulo)}{perfil.extensao}"
    if _ja_existe(antigo):
        return ResultadoFaixa(nome_exibicao, str(antigo), True, pulado=True)

    try:
        candidatos = youtube.buscar_candidatos(f"{artista} {titulo}")
        melhor = perfil.escolher(candidatos, duracao_ms)
        if melhor is None:
            return ResultadoFaixa(nome_exibicao, None, False, erro="não achei no YouTube")

        def baixar():
            _limpar_parciais(pasta, nome_arquivo, perfil.extensao)
            return perfil.baixar(
                melhor["url"], pasta, nome_arquivo=nome_arquivo,
                progresso_callback=progresso.hook_ytdlp,
                pos_processamento_callback=progresso.hook_pos_processamento,
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
        _limpar_parciais(pasta, nome_arquivo, perfil.extensao)
        raise
    except Exception as exc:  # noqa: BLE001 - vira linha de erro na tela
        registro.erro(f"falhou ao baixar '{nome_exibicao}'", exc)
        return ResultadoFaixa(nome_exibicao, None, False, erro=str(exc))


def _avisar_tamanho(itens: list[dict], pasta: Path, avisar: Callable[[str], None]) -> None:
    """Estima o tamanho de uma playlist de vídeo e confere se cabe no disco.

    Uma playlist de 50 clipes passa dos 7 GB — muito diferente dos ~500 MB da mesma lista
    em MP3. Descobrir isso com o disco cheio no meio do caminho deixaria arquivos pela
    metade e o Windows reclamando.
    """
    minutos = sum(i.get("duracao_s") or 0 for i in itens) / 60
    if not minutos:
        return

    estimado = int(minutos * MB_POR_MINUTO_VIDEO * 1024 * 1024)
    livre = organizer.espaco_livre(pasta)
    texto = f"Cerca de {estimado / 1024**3:.1f} GB no total."
    if livre:
        texto += f" Livres no disco: {livre / 1024**3:.1f} GB."
    avisar(texto)

    if livre and estimado + MARGEM_DISCO_BYTES > livre:
        raise EspacoInsuficiente(
            f"Não há espaço suficiente: são cerca de {estimado / 1024**3:.1f} GB de vídeo "
            f"e restam {livre / 1024**3:.1f} GB no disco. Libere espaço ou escolha outra "
            "pasta antes de baixar."
        )


def _encerrar(
    resultado: ResultadoProcessamento,
    perfil: PerfilMidia,
    percentual_callback: Callable[[float], None] | None,
) -> ResultadoProcessamento:
    """Fecha a barra e registra o resumo. Único ponto de saída de `processar_link`."""
    if percentual_callback:
        percentual_callback(1.0)

    registro.info(
        f"concluído ({perfil.nome}): {len(resultado.baixados)} baixada(s), "
        f"{len(resultado.pulados)} já existia(m), {len(resultado.falhas)} falhou(ram), "
        f"{len(resultado.incertas)} para conferir"
    )
    return resultado


def processar_link(
    texto: str,
    progresso_callback: Callable[[str], None] | None = None,
    percentual_callback: Callable[[float], None] | None = None,
    cancelar: threading.Event | None = None,
    midia: str = MUSICA,
) -> ResultadoProcessamento:
    """Processa o texto colado pelo usuário e baixa a(s) faixa(s) correspondente(s).

    `cancelar`: quando acionado, interrompe assim que possível (inclusive no meio de um
    download) e levanta CancelamentoSolicitado, deixando os parciais limpos.
    `midia`: MUSICA (MP3) ou VIDEO (MP4) — muda formato, pasta de destino e o critério
    de escolha do vídeo no YouTube.
    """

    def avisar(msg: str) -> None:
        if progresso_callback:
            progresso_callback(msg)

    perfil = obter_perfil(midia)

    def novo_progresso(total: int) -> _Progresso:
        return _Progresso(
            total, percentual_callback, cancelar, perfil.partes_por_item, avisar
        )

    origem = identificar_origem(texto)
    registro.info(f"pedido recebido ({origem.value}, {perfil.nome}): {texto[:200]}")
    resultado = ResultadoProcessamento()

    if origem == Origem.SPOTIFY:
        tipo, spotify_id = extrair_spotify(texto)
        if perfil.nome == VIDEO:
            # O Spotify não tem vídeo. Buscamos o clipe no YouTube pelo nome da faixa —
            # é o mesmo caminho da música, só com outro critério de escolha.
            avisar("O Spotify não tem vídeo — vou procurar o clipe no YouTube.")

        if tipo == "track":
            avisar("Lendo a faixa no Spotify...")
            faixa = spotify.obter_faixa(spotify_id)
            progresso = novo_progresso(1)
            avisar(f"Procurando no YouTube: {faixa['artista']} - {faixa['faixa']}")
            resultado.faixas.append(
                _baixar_faixa_spotify(
                    faixa["artista"], faixa["faixa"], faixa["duracao_ms"],
                    perfil.pasta(), progresso, cancelar=cancelar, perfil=perfil,
                )
            )
        else:
            avisar("Lendo a lista no Spotify...")
            listar = spotify.listar_faixas_album if tipo == "album" else spotify.listar_faixas_playlist
            nome, faixas, truncada = listar(spotify_id)
            avisar(f"{nome}: {len(faixas)} faixa(s). Começando...")
            if truncada:
                avisar("(se a playlist tiver mais que isso, confira o total no final)")

            pasta = organizer.pasta_para_playlist(nome, base=perfil.pasta())
            if perfil.nome == VIDEO:
                _avisar_tamanho(
                    [{"duracao_s": (f.get("duracao_ms") or 0) / 1000} for f in faixas],
                    pasta, avisar,
                )
            progresso = novo_progresso(len(faixas))
            for i, faixa in enumerate(faixas, start=1):
                avisar(f"[{i}/{len(faixas)}] {faixa['artista']} - {faixa['faixa']}")
                r = _baixar_faixa_spotify(
                    faixa["artista"], faixa["faixa"], faixa["duracao_ms"], pasta, progresso,
                    album=nome,  # agrupa a playlist como álbum no software de DJ
                    cancelar=cancelar, perfil=perfil,
                )
                if r.pulado:
                    avisar("   já estava baixada, pulando")
                resultado.faixas.append(r)
                progresso.item_concluido()

    elif origem == Origem.YOUTUBE:
        if youtube.eh_playlist(texto):
            avisar("Lendo a playlist do YouTube...")
            itens = youtube.listar_itens_playlist(texto)
            pasta = organizer.pasta_para_playlist(
                f"Playlist YouTube ({len(itens)} faixas)", base=perfil.pasta()
            )
            if perfil.nome == VIDEO:
                _avisar_tamanho(itens, pasta, avisar)
            progresso = novo_progresso(len(itens))
            avisar(f"{len(itens)} vídeo(s). Começando...")

            for i, item in enumerate(itens, start=1):
                _checar_cancelamento(cancelar)
                avisar(f"[{i}/{len(itens)}] {item['titulo']}")
                nome_arquivo = organizer.nome_seguro(item["titulo"])
                destino = pasta / f"{nome_arquivo}{perfil.extensao}"

                if _ja_existe(destino):
                    avisar("   já estava baixada, pulando")
                    resultado.faixas.append(
                        ResultadoFaixa(item["titulo"], str(destino), True, pulado=True)
                    )
                    progresso.item_concluido()
                    continue

                try:
                    def baixar(url=item["url"], nome=nome_arquivo):
                        _limpar_parciais(pasta, nome, perfil.extensao)
                        return perfil.baixar(
                            url, pasta, nome_arquivo=nome,
                            progresso_callback=progresso.hook_ytdlp,
                            pos_processamento_callback=progresso.hook_pos_processamento,
                        )

                    caminho = _com_retentativa(baixar, youtube.e_bloqueio_definitivo)
                    resultado.faixas.append(ResultadoFaixa(item["titulo"], str(caminho), True))
                except CancelamentoSolicitado:
                    _limpar_parciais(pasta, nome_arquivo, perfil.extensao)
                    raise
                except Exception as exc:  # noqa: BLE001
                    registro.erro(f"falhou ao baixar '{item['titulo']}'", exc)
                    resultado.faixas.append(ResultadoFaixa(item["titulo"], None, False, erro=str(exc)))
                progresso.item_concluido()
        else:
            progresso = novo_progresso(1)
            pasta = perfil.pasta()

            # Para vídeo, descobrir o nome antes vale os ~2s de consulta: é o que evita
            # rebaixar 200 MB que já estão na pasta e o que permite limpar os pedaços se
            # ele cancelar no meio. Para música o download inteiro leva ~10s e a consulta
            # não se pagaria — esse caminho segue exatamente como sempre foi.
            nome_arquivo = None
            if perfil.nome == VIDEO:
                avisar("Consultando o vídeo...")
                titulo = youtube.obter_titulo(texto)
                if titulo:
                    nome_arquivo = organizer.nome_seguro(titulo)
                    destino = pasta / f"{nome_arquivo}{perfil.extensao}"
                    if _ja_existe(destino):
                        avisar("   já estava baixado, pulando")
                        resultado.faixas.append(
                            ResultadoFaixa(titulo, str(destino), True, pulado=True)
                        )
                        progresso.item_concluido()
                        return _encerrar(resultado, perfil, percentual_callback)

            avisar(f"Baixando o {perfil.rotulo}...")
            try:
                if nome_arquivo:
                    _limpar_parciais(pasta, nome_arquivo, perfil.extensao)
                caminho = perfil.baixar(
                    texto, pasta, nome_arquivo=nome_arquivo,
                    progresso_callback=progresso.hook_ytdlp,
                    pos_processamento_callback=progresso.hook_pos_processamento,
                )
                resultado.faixas.append(ResultadoFaixa(Path(caminho).stem, str(caminho), True))
            except CancelamentoSolicitado:
                if nome_arquivo:
                    _limpar_parciais(pasta, nome_arquivo, perfil.extensao)
                raise
            except Exception as exc:  # noqa: BLE001
                registro.erro(f"falhou ao baixar '{texto}'", exc)
                resultado.faixas.append(ResultadoFaixa(texto, None, False, erro=str(exc)))

    else:  # TEXTO_LIVRE
        avisar(f"Procurando no YouTube: {texto}")
        progresso = novo_progresso(1)
        candidatos = youtube.buscar_candidatos(texto, limite=1)
        if not candidatos:
            resultado.faixas.append(ResultadoFaixa(texto, None, False, erro="nenhum resultado"))
        else:
            melhor = candidatos[0]
            avisar(f"Baixando: {melhor['titulo']}")
            try:
                caminho = perfil.baixar(
                    melhor["url"],
                    perfil.pasta(),
                    progresso_callback=progresso.hook_ytdlp,
                    pos_processamento_callback=progresso.hook_pos_processamento,
                )
                resultado.faixas.append(ResultadoFaixa(melhor["titulo"], str(caminho), True))
            except CancelamentoSolicitado:
                raise
            except Exception as exc:  # noqa: BLE001
                registro.erro(f"falhou ao baixar '{melhor['titulo']}'", exc)
                resultado.faixas.append(ResultadoFaixa(melhor["titulo"], None, False, erro=str(exc)))

    return _encerrar(resultado, perfil, percentual_callback)
