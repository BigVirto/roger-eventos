"""Manda os erros da máquina do Rogério para o Vitor, sozinho e em segundo plano.

Por que existe: `core/registro.py` já grava tudo em `registro.txt`, mas o arquivo fica
parado na casa do Rogério. Alguém precisa pedir para ele abrir, achar e mandar — o que
na prática vira "não tá baixando" no WhatsApp e diagnóstico às cegas. Aqui o erro sobe
sozinho e vira um chamado, e a correção desce pela atualização automática que já existe.

Como o erro é capturado: em vez de espalhar chamadas por todo o código, este módulo
pendura um manipulador no logger que `core/registro.py` já usa. Toda chamada a
`registro.erro()` que existe hoje — e qualquer uma escrita no futuro — vira ocorrência
sem alterar uma linha de `pipeline.py` ou `youtube.py`.

Caminho até o Vitor:

    app  ──▶  Apps Script (Google)  ──▶  Issue no GitHub

O app NÃO fala com o GitHub. Criar Issue exige uma chave, e chave dentro do .exe é
extraível (o repositório é público) e, pior, vence — e o envio morreria em silêncio,
sendo que quem avisaria disso é justamente este módulo. Então o app só deposita a carta
num endereço que só recebe; a chave mora do outro lado, na conta do Vitor.

Três regras que este arquivo nunca quebra:

1. **Nunca derruba o app.** Toda função engole exceção. Mesma disciplina de
   `atualizador_app.verificar_e_atualizar()`.
2. **Nunca atrasa o app.** O envio roda em thread daemon; quem provoca o erro só
   escreve um arquivo na fila e segue.
3. **Nunca chama `registro.erro()`.** Isso se reportaria a si mesmo em círculo. Falha
   deste módulo vira `registro.aviso()`, que fica abaixo do nível capturado.
"""

import getpass
import hashlib
import json
import logging
import platform
import re
import sys
import threading
import time
import traceback
import urllib.request
from datetime import date, datetime
from pathlib import Path

# Endereço da "caixa de correio" (Web App do Google Apps Script). Só recebe; não
# devolve nada útil e não guarda chave nenhuma do lado do app.
# Trocar aqui e publicar uma atualização é o conserto caso o endereço vaze e receba lixo.
URL_RECEPTOR = "https://script.google.com/macros/s/AKfycbzp_nCg4yj4rzMAcVp6wW9j0QqSHEYGdx-6eBx4b3mOgXnkvWffIv0GpZ3-s4nkGFdQ/exec"

# Vai junto em toda carta e o receptor descarta o que vier sem ela. NÃO é segredo — este
# arquivo está num repositório público. Serve contra tráfego acidental, não contra
# alguém determinado; ver o comentário de URL_RECEPTOR para o conserto de verdade.
PALAVRA_COMBINADA = "roger-eventos-baixador"

ESPERA_AGRUPAMENTO_S = 60  # janela para uma rajada de falhas virar um relatório só
ESPERA_MAXIMA_S = 600  # ... mas não segura mais que isso, mesmo com a rajada em curso
INTERVALO_REVISAO_S = 300  # revisita a fila (sobra de sessão anterior, internet que caiu)
LIMITE_DIARIO = 20  # tetos para um defeito em laço não virar enxurrada de chamados
LIMITE_FILA = 50
LINHAS_DE_REGISTRO = 40
MAXIMO_DETALHE = 20_000
MAXIMO_PEDIDO = 200

CHAVE_ENVIO = "enviar_erros"
CHAVE_CONTADOR = "envio_erros_por_dia"

_evento_novo = threading.Event()
_trava = threading.Lock()
_thread: threading.Thread | None = None
_pedido_atual: str | None = None
_reentrante = threading.local()


# --------------------------------------------------------------------------- básico


def esta_configurado() -> bool:
    return bool(URL_RECEPTOR)


def envio_ligado() -> bool:
    """O Rogério pode desligar mexendo em `configuracao.json`. Padrão: ligado."""
    from core.organizer import obter_config

    return bool(obter_config(CHAVE_ENVIO, True))


def pasta_ocorrencias() -> Path:
    from core.organizer import pasta_dados

    return pasta_dados() / "ocorrencias"


def definir_pedido_atual(texto: str | None) -> None:
    """Guarda o que o usuário colou, para o relatório dizer o que ele estava tentando.

    Sem isto, o chamado mostra o erro mas não o que o provocou — e "falhou ao baixar"
    sem saber se era playlist do Spotify ou vídeo solto rende pouco.
    """
    global _pedido_atual
    _pedido_atual = (texto or "")[:MAXIMO_PEDIDO] or None


# ---------------------------------------------------------------------- mascaramento


def _mascarar(texto: str | None) -> str:
    """Tira o nome do usuário do Windows de tudo que sai da máquina.

    Traceback do PyInstaller e caminhos de download carregam `C:\\Users\\<nome>\\...`.
    Nada disso ajuda a corrigir bug e é a única informação pessoal que passaria por aqui.
    """
    if not texto:
        return ""

    resultado = texto
    for original, substituto in _disfarces():
        if original:
            resultado = re.sub(
                re.escape(original), lambda _m, s=substituto: s, resultado, flags=re.IGNORECASE
            )
    return resultado


def _disfarces() -> list[tuple[str, str]]:
    """Pares (o que esconder, pelo que trocar). A pasta pessoal vem antes do nome solto:
    ela contém o nome, e trocar o nome primeiro deixaria o caminho pela metade."""
    itens: list[tuple[str, str]] = []
    try:
        lar = str(Path.home())
        itens += [(lar, "~"), (lar.replace("\\", "/"), "~")]
    except Exception:  # noqa: BLE001
        pass
    try:
        itens.append((getpass.getuser(), "usuario"))
    except Exception:  # noqa: BLE001
        pass
    return itens


# ------------------------------------------------------------------ impressão digital


def impressao_digital(tipo: str, excecao: BaseException | None, mensagem: str) -> str:
    """Código curto que identifica *o mesmo defeito*, para agrupar repetições.

    É o que faz uma playlist com 50 falhas iguais virar um chamado dizendo "50 vezes"
    em vez de 50 chamados — a diferença entre um sistema que se lê e um que se ignora.

    Usa os três últimos passos do traceback por **arquivo e função**, sem número de
    linha: mexer no código desloca as linhas e criaria chamado novo para o mesmo defeito.

    A versão do app de propósito NÃO entra. O mesmo defeito atravessando versões deve
    continuar no mesmo chamado; e se ele voltar depois de corrigido, o chamado já estará
    fechado e o receptor abre um novo — que é exatamente o aviso de recaída que se quer.
    """
    partes = [tipo]
    if excecao is not None and excecao.__traceback__ is not None:
        for quadro in traceback.extract_tb(excecao.__traceback__)[-3:]:
            partes.append(f"{Path(quadro.filename).name}:{quadro.name}")
    else:
        # Sem traceback, resta a mensagem. Números viram "N" para que "faixa 3 falhou" e
        # "faixa 7 falhou" não contem como defeitos diferentes.
        partes.append(re.sub(r"\d+", "N", mensagem)[:200])

    return hashlib.sha1("|".join(partes).encode("utf-8", "replace")).hexdigest()[:6]


# ------------------------------------------------------------------------- a ficha


def _ultimas_linhas_do_registro(quantas: int = LINHAS_DE_REGISTRO) -> str:
    """O que aconteceu logo antes do erro — costuma ser a pista que falta."""
    try:
        from core import registro

        linhas = registro.caminho_log().read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(linhas[-quantas:])
    except Exception:  # noqa: BLE001
        return ""


def _identificador_da_maquina() -> str:
    """Distingue máquinas sem dizer de quem são. Hoje só o Rogério usa; se um dia forem
    vários, é isto que separa "o app está quebrado" de "aquela máquina está estranha"."""
    try:
        cru = f"{platform.node()}|{getpass.getuser()}"
    except Exception:  # noqa: BLE001
        cru = "desconhecida"
    return hashlib.sha1(cru.encode("utf-8", "replace")).hexdigest()[:8]


def _versao_do_ytdlp() -> tuple[str, str]:
    """Versão do yt-dlp e se é a embutida ou a baixada.

    Lê de `sys.modules` em vez de importar: importar o yt_dlp custa cerca de 1s, e a
    hora de montar um relatório de erro não é hora de gastar isso. Quando há erro de
    download ele já está importado de qualquer forma.
    """
    modulo = sys.modules.get("yt_dlp")
    try:
        versao = modulo.version.__version__ if modulo else "não carregado"
    except Exception:  # noqa: BLE001
        versao = "desconhecida"

    try:
        from core.atualizador import caminho_yt_dlp_atualizado

        origem = "atualizado" if caminho_yt_dlp_atualizado() else "embutido"
    except Exception:  # noqa: BLE001
        origem = "desconhecida"
    return versao, origem


def montar(
    tipo: str, mensagem: str, detalhe: str, digital: str, pedido: str | None = None
) -> dict:
    """A ficha padronizada. Sempre os mesmos campos — é o que permite comparar e contar."""
    from core.versao import VERSAO

    try:
        from core.atualizador_app import versao_embutida

        versao_exe = versao_embutida()
    except Exception:  # noqa: BLE001
        versao_exe = "desconhecida"

    versao_ytdlp, origem_ytdlp = _versao_do_ytdlp()
    agora = datetime.now()

    return {
        "palavra": PALAVRA_COMBINADA,
        "impressao_digital": digital,
        "quando": agora.isoformat(timespec="seconds"),
        "criado_em": time.time(),
        "ocorrencias": 1,
        "versao_app": VERSAO,
        "versao_exe": versao_exe,
        "origem_codigo": "atualizada" if VERSAO != versao_exe else "embutida",
        "versao_ytdlp": versao_ytdlp,
        "origem_ytdlp": origem_ytdlp,
        "sistema": platform.platform(),
        "maquina": _identificador_da_maquina(),
        "pedido": _mascarar(pedido or _pedido_atual or "")[:MAXIMO_PEDIDO],
        "tipo": tipo,
        "mensagem": _mascarar(mensagem)[:500],
        "detalhe": _mascarar(detalhe)[:MAXIMO_DETALHE],
        "registro": _mascarar(_ultimas_linhas_do_registro()),
        "teste": False,
    }


# --------------------------------------------------------------------------- a fila


def registrar(
    tipo: str, mensagem: str, excecao: BaseException | None = None, detalhe: str = ""
) -> str | None:
    """Anota uma ocorrência na fila. Devolve o código do relatório, ou None se não anotou.

    Repetição do mesmo defeito não cria arquivo novo: soma no que já está lá. É aqui que
    50 falhas de uma playlist viram um relatório só.
    """
    try:
        if not envio_ligado():
            return None

        if excecao is not None and not detalhe:
            detalhe = "".join(
                traceback.format_exception(type(excecao), excecao, excecao.__traceback__)
            )

        digital = impressao_digital(tipo, excecao, mensagem)
        pasta = pasta_ocorrencias()
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / f"{digital}.json"

        with _trava:
            if arquivo.exists():
                ficha = json.loads(arquivo.read_text(encoding="utf-8"))
                ficha["ocorrencias"] = int(ficha.get("ocorrencias", 1)) + 1
                ficha["quando"] = datetime.now().isoformat(timespec="seconds")
            else:
                if len(list(pasta.glob("*.json"))) >= LIMITE_FILA:
                    return None  # fila cheia: parar de anotar é melhor que encher o disco
                ficha = montar(tipo, mensagem, detalhe, digital)

            arquivo.write_text(json.dumps(ficha, ensure_ascii=False), encoding="utf-8")

        _evento_novo.set()
        return digital
    except Exception:  # noqa: BLE001 - relatar erro nunca pode virar erro
        return None


# ------------------------------------------------------------------------- captura


class ManipuladorDeOcorrencias(logging.Handler):
    """Transforma em ocorrência tudo que passa por `registro.erro()`.

    Pendurado no logger que já existe: nenhum ponto de falha do app precisou ser
    alterado, e os que forem escritos daqui para frente já entram cobertos.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        # Trava contra círculo: se algo aqui dentro registrar um erro, ele não pode
        # voltar a entrar e se reportar para sempre.
        if getattr(_reentrante, "dentro", False):
            return
        _reentrante.dentro = True
        try:
            excecao = record.exc_info[1] if record.exc_info else None
            tipo = type(excecao).__name__ if excecao else "ErroRegistrado"
            registrar(tipo, record.getMessage(), excecao)
        except Exception:  # noqa: BLE001
            pass
        finally:
            _reentrante.dentro = False


def instalar_capturadores() -> None:
    """Pega também o que estoura fora de qualquer `try` — inclusive em outra thread."""
    try:
        anterior = sys.excepthook

        def ao_estourar(tipo, valor, tb):
            registrar(getattr(tipo, "__name__", "Erro"), str(valor), valor)
            anterior(tipo, valor, tb)

        sys.excepthook = ao_estourar

        anterior_thread = threading.excepthook

        def ao_estourar_em_thread(args):
            registrar(
                getattr(args.exc_type, "__name__", "Erro"), str(args.exc_value), args.exc_value
            )
            anterior_thread(args)

        threading.excepthook = ao_estourar_em_thread
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- envio


def _contador_de_hoje() -> int:
    from core.organizer import obter_config

    dados = obter_config(CHAVE_CONTADOR) or {}
    return int(dados.get("enviados", 0)) if dados.get("data") == date.today().isoformat() else 0


def _somar_ao_contador() -> None:
    from core.organizer import definir_config

    definir_config(
        CHAVE_CONTADOR, {"data": date.today().isoformat(), "enviados": _contador_de_hoje() + 1}
    )


def _postar(ficha: dict) -> bool:
    dados = json.dumps(ficha, ensure_ascii=False).encode("utf-8")
    requisicao = urllib.request.Request(
        URL_RECEPTOR, data=dados, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(requisicao, timeout=30) as resposta:
        return 200 <= resposta.status < 300


def _esta_madura(ficha: dict, arquivo: Path) -> bool:
    """Se já passou da janela de agrupamento.

    Enquanto a rajada continua, o arquivo é reescrito e a espera reinicia — é assim que
    uma playlist inteira vira um relatório só. O teto de ESPERA_MAXIMA_S garante que uma
    rajada muito longa não segure o aviso para sempre.
    """
    agora = time.time()
    try:
        parado_ha = agora - arquivo.stat().st_mtime
    except OSError:
        parado_ha = ESPERA_AGRUPAMENTO_S
    esperando_ha = agora - float(ficha.get("criado_em", agora))
    return parado_ha >= ESPERA_AGRUPAMENTO_S or esperando_ha >= ESPERA_MAXIMA_S


def enviar_pendentes(forcar: bool = False) -> int:
    """Esvazia a fila. Devolve quantos relatórios foram aceitos.

    O que não for aceito fica no disco e vai na próxima rodada — sem internet, o
    relatório espera a próxima abertura do app em vez de se perder.
    """
    if not esta_configurado() or not envio_ligado():
        return 0

    enviados = 0
    try:
        from core import registro

        for arquivo in sorted(pasta_ocorrencias().glob("*.json")):
            if _contador_de_hoje() >= LIMITE_DIARIO:
                return enviados

            try:
                ficha = json.loads(arquivo.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                arquivo.unlink(missing_ok=True)  # arquivo corrompido não serve para nada
                continue

            if not forcar and not _esta_madura(ficha, arquivo):
                continue

            try:
                if _postar(ficha):
                    arquivo.unlink(missing_ok=True)
                    _somar_ao_contador()
                    enviados += 1
                    registro.info(
                        f"relatório de erro #{ficha.get('impressao_digital')} enviado "
                        f"({ficha.get('ocorrencias')}x)"
                    )
            except Exception as exc:  # noqa: BLE001 - fica na fila para a próxima
                registro.aviso(f"não consegui enviar o relatório de erro agora: {exc}")
                return enviados
    except Exception:  # noqa: BLE001
        pass
    return enviados


def _laco() -> None:
    # Uma passada logo de saída: dá vazão ao que sobrou de uma sessão sem internet.
    enviar_pendentes()
    while True:
        houve_novidade = _evento_novo.wait(timeout=INTERVALO_REVISAO_S)
        _evento_novo.clear()
        if houve_novidade:
            # Deixa a rajada acontecer antes de empacotar.
            time.sleep(ESPERA_AGRUPAMENTO_S)
            _evento_novo.clear()
        enviar_pendentes()


def iniciar_envio_em_segundo_plano() -> None:
    """Thread daemon, no mesmo padrão dos dois atualizadores: nunca atrasa a janela."""
    global _thread
    if _thread is not None or not esta_configurado():
        return
    _thread = threading.Thread(target=_laco, daemon=True, name="envio-de-erros")
    _thread.start()


def enviar_agora() -> int:
    """Botão "Avisar o Vitor agora": manda a fila inteira sem esperar o agrupamento."""
    return enviar_pendentes(forcar=True)


def vai_avisar() -> bool:
    """Se um erro agora viraria mesmo um aviso ao Vitor.

    A janela consulta antes de escrever "já avisei" na tela: prometer isso com o envio
    desligado ou sem endereço configurado seria mentir para o Rogério.
    """
    return esta_configurado() and envio_ligado()


def codigo_do_erro(excecao: BaseException, mensagem: str = "") -> str:
    """O código curto que a janela mostra. Dá o mesmo resultado do que foi para a fila —
    é o que permite casar um "deu erro aqui" no WhatsApp com o chamado exato."""
    return impressao_digital(type(excecao).__name__, excecao, mensagem)


def relatar_manualmente(observacao: str = "") -> str | None:
    """Relato pedido pelo Rogério, sem erro nenhum ter estourado.

    Existe pelo mesmo motivo do `--reverter`: o caso em que o app funciona, não acusa
    falha, mas o resultado está errado (baixou a versão ao vivo, a playlist veio pela
    metade). Nenhuma checagem automática pega isso — só ele percebe.
    """
    return registrar(
        "RelatoManual",
        observacao or "o Rogério pediu para avisar o Vitor",
        detalhe="Sem erro técnico: relato aberto pelo botão da janela.",
    )


def ha_pendentes() -> int:
    try:
        return len(list(pasta_ocorrencias().glob("*.json")))
    except Exception:  # noqa: BLE001
        return 0


# ------------------------------------------------------------------------- autoteste


def autoteste() -> bool:
    """Envia uma ocorrência marcada como teste, para validar o caminho inteiro de ponta
    a ponta. O receptor rotula e fecha na hora, então não polui a lista de chamados."""
    if not esta_configurado():
        return False
    ficha = montar(
        "AutoTeste",
        "envio de teste do --autoteste",
        "sem traceback: ocorrência fabricada para validar o caminho de envio",
        "teste0",
        pedido="(autoteste)",
    )
    ficha["teste"] = True
    return _postar(ficha)
