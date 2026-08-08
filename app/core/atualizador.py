"""Mantém o yt-dlp atualizado sem exigir nada do Rogério.

Por que existe: o yt-dlp vai congelado dentro do .exe. Quando o YouTube muda alguma
coisa (acontece com frequência), a versão congelada para de funcionar e o Rogério não
tem como consertar sozinho — dependeria de alguém regerar o executável.

Como funciona: no máximo uma vez por semana, verifica no GitHub se saiu versão nova.
Se saiu, baixa o pacote Python (yt-dlp é Python puro, não precisa de pip nem compilar)
e extrai para `atualizacoes/` ao lado do .exe. Na próxima abertura, `main.py` coloca
essa pasta na frente do sys.path e o app passa a usar a versão nova.

Regra de ouro: uma atualização ruim NUNCA pode deixar o app pior que estava. Se o
yt_dlp atualizado não importar, a pasta é descartada e volta a valer o embutido.
"""

import json
import io
import os
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

URL_ULTIMO_RELEASE = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
NOME_ASSET = "yt-dlp.tar.gz"
INTERVALO_VERIFICACAO_S = 7 * 24 * 3600  # uma vez por semana
# Guarda a versão do app sob a qual este yt-dlp foi baixado. Ver `_exe_foi_trocado()`.
ARQUIVO_CARIMBO = "baixado_na_versao_do_app.txt"


def pasta_atualizacoes() -> Path:
    """Fica em AppData: a pasta de instalação pode ser somente-leitura."""
    from core.organizer import pasta_dados

    return pasta_dados() / "atualizacoes"


def _marca_de_tempo() -> Path:
    return pasta_atualizacoes() / "ultima_verificacao.txt"


def caminho_yt_dlp_atualizado() -> Path | None:
    """Retorna a pasta a colocar no sys.path, se houver uma atualização utilizável."""
    destino = pasta_atualizacoes()
    return destino if (destino / "yt_dlp" / "__init__.py").exists() else None


def descartar_atualizacao() -> None:
    """Remove a atualização — usado quando ela se mostra quebrada."""
    shutil.rmtree(pasta_atualizacoes() / "yt_dlp", ignore_errors=True)
    (pasta_atualizacoes() / ARQUIVO_CARIMBO).unlink(missing_ok=True)


def _carimbo() -> Path:
    return pasta_atualizacoes() / ARQUIVO_CARIMBO


def _exe_foi_trocado() -> bool:
    """Diz se o .exe foi reinstalado depois que este yt-dlp foi baixado.

    Por que existe: o yt-dlp baixado entra na frente do embutido sem comparar versões.
    Ao instalar um .exe novo — que já traz um yt-dlp recente — o app continuaria usando
    o pacote velho guardado no AppData por até uma semana, até a próxima verificação.
    Era exatamente o caso de "publiquei a correção e não adiantou".

    Comparar as versões de verdade exigiria importar o yt_dlp embutido só para ler o
    número, e depois de novo o atualizado — cerca de 1s a mais em toda abertura. O
    carimbo resolve lendo um arquivo de texto: se a versão do app mudou, o .exe é outro.
    """
    from core.atualizador_app import versao_embutida
    from core.versao import como_tupla

    try:
        carimbada = _carimbo().read_text(encoding="utf-8").strip()
    except OSError:
        return True  # pacote anterior ao carimbo: tratar como velho é o lado seguro
    return como_tupla(carimbada) < como_tupla(versao_embutida())


def _versao_instalada() -> str:
    try:
        import yt_dlp

        return yt_dlp.version.__version__
    except Exception:  # noqa: BLE001
        return "0"


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


def _baixar_e_extrair(url: str) -> None:
    """Extrai só o pacote yt_dlp/ do sdist para a pasta de atualizações."""
    dados = urllib.request.urlopen(url, timeout=180).read()
    destino = pasta_atualizacoes()
    temporaria = destino / "_novo"
    shutil.rmtree(temporaria, ignore_errors=True)

    with tarfile.open(fileobj=io.BytesIO(dados), mode="r:gz") as tf:
        raiz = tf.getnames()[0].split("/")[0]
        prefixo = f"{raiz}/yt_dlp/"
        membros = [m for m in tf.getmembers() if m.name.startswith(prefixo)]
        if not membros:
            raise RuntimeError("o pacote yt_dlp/ não veio no arquivo baixado")
        for m in membros:
            m.name = m.name[len(raiz) + 1 :]
        tf.extractall(temporaria, members=membros, filter="data")

    # Troca só no fim: se algo falhar acima, a versão anterior continua intacta.
    definitiva = destino / "yt_dlp"
    shutil.rmtree(definitiva, ignore_errors=True)
    shutil.move(str(temporaria / "yt_dlp"), str(definitiva))
    shutil.rmtree(temporaria, ignore_errors=True)

    from core.atualizador_app import versao_embutida

    _carimbo().write_text(versao_embutida(), encoding="utf-8")


def verificar_e_atualizar() -> str | None:
    """Verifica e aplica atualização. Retorna a versão baixada, ou None.

    Nunca levanta exceção: falhar em atualizar é aceitável, derrubar o app não é.
    """
    try:
        if not _deve_verificar():
            return None

        _registrar_verificacao()

        with urllib.request.urlopen(URL_ULTIMO_RELEASE, timeout=30) as resposta:
            release = json.load(resposta)

        ultima = release.get("tag_name", "")
        if not ultima or ultima <= _versao_instalada():
            return None

        url = next(a["browser_download_url"] for a in release["assets"] if a["name"] == NOME_ASSET)
        _baixar_e_extrair(url)
        return ultima
    except Exception:  # noqa: BLE001 - silencioso de propósito; o app segue com o embutido
        return None


def preparar_sys_path() -> None:
    """Coloca a atualização na frente do sys.path, descartando-a se estiver quebrada.

    Precisa rodar ANTES de qualquer import de yt_dlp.
    """
    pasta = caminho_yt_dlp_atualizado()
    if not pasta:
        return

    if _exe_foi_trocado():
        descartar_atualizacao()
        # Zera a marca semanal para o app rebaixar hoje mesmo, se houver algo mais novo
        # que o recém-embutido — sem isso ficaria até uma semana só com o do .exe.
        _marca_de_tempo().unlink(missing_ok=True)
        return

    sys.path.insert(0, str(pasta))
    try:
        import yt_dlp  # noqa: F401

        yt_dlp.version.__version__  # noqa: B018 - confirma que o módulo está íntegro
    except Exception:  # noqa: BLE001
        sys.path.remove(str(pasta))
        descartar_atualizacao()
        for modulo in [m for m in sys.modules if m.startswith("yt_dlp")]:
            del sys.modules[modulo]
