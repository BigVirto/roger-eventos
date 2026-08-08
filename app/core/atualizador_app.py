"""Mantém o CÓDIGO DO APP atualizado sem precisar mandar instalador novo.

Por que existe: até agora, qualquer melhoria (interface, leitura do Spotify, nome de
arquivo, correção de bug) exigia gerar um instalador de ~142 MB e o usuário instalar de
novo. Só o yt-dlp se atualizava sozinho, via `core/atualizador.py`.

Como funciona: o app é Python puro em `core/` e `gui/` — texto, não binário. Dá para
baixar uma versão nova desses arquivos (~100 KB) e usá-la na abertura seguinte, sem
tocar no .exe. É o mesmo truque de `core/atualizador.py`, aplicado ao próprio app.

O que isso NÃO cobre: trocar a versão do Python, o ffmpeg, o deno, o ícone ou o nome do
programa. Essas coisas moram dentro do .exe e continuam exigindo instalador novo.

Regra de ouro (a mesma do outro atualizador): uma atualização ruim NUNCA pode deixar o
app pior que estava. Três camadas de proteção:
  1. só aceita pacote com versão MAIOR que a embutida (`core/versao.py`);
  2. na abertura, se o código atualizado não importar, é descartado e volta o embutido;
  3. se o app estourar erro ao iniciar com ele, `main.py` descarta e pede para reabrir.

Escape manual: rodar o .exe com `--reverter` apaga a atualização e volta ao embutido.
É a saída para o caso em que o código novo abre normalmente mas funciona mal — nenhum
teste automático pega isso.
"""

import io
import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

# Importado no topo de propósito: main.py carrega este módulo ANTES de qualquer troca de
# código, então o valor capturado aqui é sempre o que veio dentro do .exe. Depois que a
# atualização entra no sys.path, `core.versao` passa a devolver a versão baixada — e
# `core/atualizador.py` depende de saber a embutida para detectar que o .exe foi trocado.
from core.versao import VERSAO as _VERSAO_EMBUTIDA

# Onde o app procura versões novas. É um repositório público de propósito: privado
# exigiria uma chave dentro do .exe, que é extraível e vence com o tempo — e quando
# vencesse, as atualizações parariam em silêncio. Ver workflows/baixar_musicas_app.md.
REPOSITORIO = "BigVirto/roger-eventos"

NOME_ASSET = "roger-eventos-app.zip"
INTERVALO_VERIFICACAO_S = 6 * 3600
PASTAS_DO_APP = ("core", "gui")
ARQUIVO_VERSAO = "versao.txt"
# Versão que já se mostrou ruim nesta máquina. Sem isto, descartar uma atualização só
# durava até a próxima verificação (6h) — o app rebaixava exatamente a mesma versão e o
# problema voltava. Guarda só a recusada: uma versão mais nova continua sendo aceita.
ARQUIVO_RECUSADA = "recusada.txt"

# Onde main.py grava a versão do .exe antes de trocar o código. Ver versao_embutida().
VARIAVEL_VERSAO_EXE = "RE_PLAY_VERSAO_EXE"

# Nota: chegou a existir aqui uma trava que segurava atualizações de sexta a domingo,
# para não trocar o código do app em dia de evento. Removida em 2026-08-07: o usuário
# baixa as músicas com antecedência e deixa tudo programado antes da festa, então não há
# app rodando durante o evento para proteger. A trava só atrasaria correção — e a maioria
# delas é justamente "o YouTube mudou e parou de baixar".

# Módulos exigidos para considerar a atualização utilizável. Importar todos eles pega
# erro de sintaxe e import quebrado — as falhas mais prováveis de um pacote ruim.
MODULOS_ESSENCIAIS = (
    "core.versao",
    "core.organizer",
    "core.registro",
    "core.ocorrencias",
    "core.link_detector",
    "core.matcher",
    "core.metadata",
    "core.spotify",
    "core.youtube",
    "core.pipeline",
    "gui.main_window",
)


def _url_ultimo_release() -> str:
    return f"https://api.github.com/repos/{REPOSITORIO}/releases/latest"


def esta_configurado() -> bool:
    return "SEU-USUARIO" not in REPOSITORIO


def pasta_atualizacao() -> Path:
    """Fica em AppData: a pasta de instalação pode ser somente-leitura."""
    from core.organizer import pasta_dados

    return pasta_dados() / "app_atualizado"


def _marca_de_tempo() -> Path:
    return pasta_atualizacao() / "ultima_verificacao.txt"


def versao_embutida() -> str:
    """Versão que veio dentro do .exe — não muda com atualização automática.

    Lê da variável de ambiente que `main.py` grava ANTES de trocar o código. O valor de
    `_VERSAO_EMBUTIDA` só serve de reserva: depois de uma atualização, este módulo passa
    a ser o baixado, e aí a constante teria o número da atualização, não o do executável.
    Era o bastante para `core/atualizador.py` achar que o .exe tinha sido reinstalado e
    rebaixar o yt-dlp a cada atualização do app.
    """
    return os.environ.get(VARIAVEL_VERSAO_EXE) or _VERSAO_EMBUTIDA


CHAVE_VERSAO_VISTA = "ultima_versao_vista"


def versao_mudou_desde_a_ultima_vez() -> str | None:
    """Se a versão em uso mudou desde a última abertura, devolve a nova. Marca como vista.

    Por que existe: atualizar sem pedir permissão é o certo aqui — o usuário não teria
    como decidir, e recusar deixaria o app quebrado quando o YouTube mudasse. Mas
    atualizar sem CONTAR é outra coisa: diante de "parou de funcionar", ninguém saberia
    que o código mudou no meio. Avisar depois resolve isso sem transferir a decisão para
    quem não tem base para tomá-la.

    Na primeira abertura não avisa nada — não houve mudança, só não havia registro.
    """
    from core.organizer import definir_config, obter_config
    from core.versao import VERSAO

    anterior = obter_config(CHAVE_VERSAO_VISTA)
    if anterior != VERSAO:
        definir_config(CHAVE_VERSAO_VISTA, VERSAO)
    return VERSAO if (anterior and anterior != VERSAO) else None


def versao_baixada(pasta: Path | None = None) -> str | None:
    """Versão do pacote já baixado, ou None se não houver pacote utilizável."""
    destino = pasta or pasta_atualizacao()
    try:
        versao = (destino / ARQUIVO_VERSAO).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    completo = all((destino / p / "__init__.py").exists() for p in PASTAS_DO_APP)
    return versao if (versao and completo) else None


def versao_recusada() -> str | None:
    """Versão marcada como ruim nesta máquina, se houver."""
    try:
        return (pasta_atualizacao() / ARQUIVO_RECUSADA).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def descartar(recusar: bool = False) -> str | None:
    """Remove a atualização e volta a valer o código embutido no .exe.

    Com `recusar=True`, anota a versão descartada para não baixá-la de novo. Usar
    sempre que o descarte veio de um problema (pacote quebrado, app não abriu, ou o
    usuário rodou --reverter); sem isso o app rebaixaria a mesma versão em até 6 horas.

    Retorna a versão que foi descartada, ou None se não havia nada.
    """
    destino = pasta_atualizacao()
    descartada = versao_baixada()
    for pasta in PASTAS_DO_APP:
        shutil.rmtree(destino / pasta, ignore_errors=True)
    (destino / ARQUIVO_VERSAO).unlink(missing_ok=True)

    if recusar and descartada:
        destino.mkdir(parents=True, exist_ok=True)
        (destino / ARQUIVO_RECUSADA).write_text(descartada, encoding="utf-8")
    return descartada


def _deve_verificar() -> bool:
    marca = _marca_de_tempo()
    if not marca.exists():
        return True
    try:
        return time.time() - float(marca.read_text().strip()) > INTERVALO_VERIFICACAO_S
    except (ValueError, OSError):
        return True


def _registrar_verificacao() -> None:
    marca = _marca_de_tempo()
    marca.parent.mkdir(parents=True, exist_ok=True)
    marca.write_text(str(time.time()))


def _baixar_e_extrair(url: str, versao: str) -> None:
    """Extrai core/ e gui/ do zip, trocando o conteúdo só no final."""
    dados = urllib.request.urlopen(url, timeout=180).read()
    destino = pasta_atualizacao()
    temporaria = destino / "_novo"
    shutil.rmtree(temporaria, ignore_errors=True)
    temporaria.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(dados)) as zf:
        # Recusa caminho absoluto ou com "..": um zip malformado não pode escrever fora
        # da pasta de destino.
        for nome in zf.namelist():
            alvo = (temporaria / nome).resolve()
            if not str(alvo).startswith(str(temporaria.resolve())):
                raise RuntimeError(f"caminho suspeito no pacote: {nome}")
        zf.extractall(temporaria)

    faltando = [p for p in PASTAS_DO_APP if not (temporaria / p / "__init__.py").exists()]
    if faltando:
        shutil.rmtree(temporaria, ignore_errors=True)
        raise RuntimeError(f"pacote incompleto, faltou: {', '.join(faltando)}")

    # Troca só no fim: se algo falhar acima, o que já existia continua intacto.
    for pasta in PASTAS_DO_APP:
        shutil.rmtree(destino / pasta, ignore_errors=True)
        shutil.move(str(temporaria / pasta), str(destino / pasta))
    (destino / ARQUIVO_VERSAO).write_text(versao, encoding="utf-8")
    shutil.rmtree(temporaria, ignore_errors=True)


def verificar_e_atualizar() -> str | None:
    """Verifica e baixa atualização do app. Retorna a versão baixada, ou None.

    Roda em segundo plano na abertura. Nunca levanta exceção: falhar em atualizar é
    aceitável, derrubar o app não é. O código novo só passa a valer na abertura seguinte.
    """
    try:
        if not esta_configurado() or not _deve_verificar():
            return None

        _registrar_verificacao()

        requisicao = urllib.request.Request(
            _url_ultimo_release(), headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(requisicao, timeout=30) as resposta:
            release = json.load(resposta)

        from core.versao import como_tupla

        publicada = release.get("tag_name", "").lstrip("vV")
        if not publicada or publicada == versao_recusada():
            return None

        # Tem de ser maior que a embutida E que a já baixada, senão o app ficaria
        # trocando de versão para frente e para trás.
        atual = max(
            como_tupla(versao_embutida()),
            como_tupla(versao_baixada() or "0"),
        )
        if como_tupla(publicada) <= atual:
            return None

        url = next(
            a["browser_download_url"] for a in release["assets"] if a["name"] == NOME_ASSET
        )
        _baixar_e_extrair(url, publicada)
        return publicada
    except Exception:  # noqa: BLE001 - silencioso de propósito; o app segue com o embutido
        return None


def preparar_sys_path() -> str | None:
    """Ativa o código atualizado, se houver um mais novo e utilizável.

    Retorna a versão ativada, ou None se ficou com o código embutido.

    Precisa rodar ANTES de qualquer import de `core` ou `gui` — é isso que faz o Python
    achar os arquivos novos em vez dos que vieram dentro do .exe.
    """
    baixada = versao_baixada()
    if not baixada:
        return None

    if baixada == versao_recusada():
        # Já se mostrou ruim aqui. Só chega neste ponto se o pacote foi baixado antes da
        # recusa; apagar agora evita que ele volte a valer na abertura seguinte.
        descartar()
        return None

    from core.versao import como_tupla

    if como_tupla(baixada) <= como_tupla(versao_embutida()):
        # Acontece depois de instalar um .exe novo: o pacote guardado em AppData ficou
        # para trás. Sem descartar aqui, o app rodaria código mais velho que o instalado.
        descartar()
        return None

    pasta = str(pasta_atualizacao())
    _esquecer_modulos_do_app()
    sys.path.insert(0, pasta)

    try:
        for modulo in MODULOS_ESSENCIAIS:
            __import__(modulo)
    except Exception:  # noqa: BLE001 - pacote quebrado: volta ao embutido
        # Nesta ordem de propósito: tirar do caminho e esquecer os módulos ANTES de
        # apagar, para que `descartar()` use o código embutido e não o que acabou de
        # falhar ao importar.
        sys.path.remove(pasta)
        _esquecer_modulos_do_app()
        descartar(recusar=True)
        return None

    return baixada


def _esquecer_modulos_do_app() -> None:
    """Tira core/gui do cache de módulos para que o próximo import releia do disco.

    Sem isto, `core` importado antes da troca continuaria valendo e os imports seguintes
    viriam do .exe, não da atualização.
    """
    alvos = [
        m
        for m in sys.modules
        if m in ("core", "gui") or m.startswith("core.") or m.startswith("gui.")
    ]
    for modulo in alvos:
        del sys.modules[modulo]
