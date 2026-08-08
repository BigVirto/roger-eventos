"""Traduz erro técnico para uma frase que o usuário consegue usar.

Por que existe: as falhas chegam do yt-dlp em inglês de programador — "Sign in to
confirm you're not a bot", "Video unavailable". Isso ia cru para a janela. No meio de um
evento, uma frase dessas não diz a ele nem o que aconteceu nem o que fazer.

O que este módulo NÃO faz: esconder informação de quem conserta. `traduzir()` só é
chamado na hora de escrever na tela. O texto técnico inteiro continua indo para
`registro.txt` e para o relatório automático (`core/ocorrencias.py`) — que é onde quem
mantém o app vai olhar. Trocar a mensagem antes de registrar seria apagar a pista.

Regra: o que não casar com nenhum padrão volta exatamente como veio. Uma tradução errada
é pior que o texto em inglês, porque manda ele para o lado errado.
"""

import re

# Cada par é (padrão, o que ele lê). A ORDEM IMPORTA: o primeiro que casar vence, então
# o mais específico vem antes do mais genérico.
#
# Os padrões de bloqueio e de vídeo indisponível são os mesmos que `core/youtube.py` usa
# em `_e_bloqueio_de_bot` e `e_bloqueio_definitivo` para decidir se vale repetir. As duas
# listas descrevem os mesmos erros com finalidades diferentes — ao descobrir uma forma
# nova de bloqueio, atualizar as duas, senão o app tenta de novo à toa (ou desiste calado)
# enquanto a tela mostra a frase errada.
_TRADUCOES: list[tuple[str, str]] = [
    # Já sai em português de `youtube.py`, quando ele esgotou clientes, cookies e
    # navegadores. Repassar inteiro: é a mensagem mais completa que existe para esse caso.
    (r"bloqueando os downloads", ""),

    (
        r"not a bot|sign in to confirm|confirm you.?re not|too many requests|429",
        "O YouTube bloqueou o download agora. Isso costuma passar sozinho: tente de novo "
        "daqui a alguns minutos. Se insistir, tente pelo 4G do celular.",
    ),
    (
        r"private video|video unavailable|removed by the uploader|members-only|"
        r"this video is not available|age.?restricted|inappropriate for some users",
        "Esse vídeo foi removido, é privado ou tem restrição de idade. Não dá para "
        "baixar. Procure outra versão da música.",
    ),
    (
        r"não achei no youtube|nenhum resultado|no results|unable to extract",
        "Não achei essa música no YouTube. Tente colar o link do vídeo direto, ou escreva "
        "o nome junto com o artista.",
    ),
    (
        r"formato da página|formato mudou|precisa atualizar core/spotify|"
        r"não consegui abrir a página do spotify|não encontrei os dados da playlist",
        "Não consegui ler essa lista do Spotify. Use o botão 📨 Relatar problema — esse "
        "aqui é para quem mantém o app resolver.",
    ),
    (
        r"timed out|timeout|connection reset|connection aborted|temporary failure|"
        r"name resolution|getaddrinfo|network is unreachable|ssl|urlopen error|"
        r"connectionerror|incomplete read",
        "A internet falhou no meio do download. Confira a conexão e tente de novo.",
    ),
    (
        r"no space left|disk full|errno 28",
        "O disco encheu. Libere espaço ou escolha outra pasta em 'Alterar pasta'.",
    ),
    (
        r"permission denied|access is denied|errno 13|being used by another process",
        "O Windows não deixou gravar o arquivo. Feche o programa que possa estar usando "
        "essa pasta, ou escolha outra em 'Alterar pasta'.",
    ),
    (
        r"ffmpeg|ffprobe",
        "Faltou uma peça do app para converter o arquivo. Use o botão 📨 Relatar problema.",
    ),
]

_COMPILADOS = [(re.compile(padrao, re.IGNORECASE), frase) for padrao, frase in _TRADUCOES]


def traduzir(erro) -> str:
    """Frase em português para mostrar na tela. Aceita exceção ou texto."""
    texto = str(erro).strip()
    if not texto:
        return "Não deu certo, e o app não soube dizer o motivo."

    for padrao, frase in _COMPILADOS:
        if padrao.search(texto):
            # Frase vazia = a mensagem original já está boa (foi escrita por nós, em
            # português). Devolver a nossa por cima só a deixaria mais pobre.
            return frase or _limpar(texto)

    return _limpar(texto)


def _limpar(texto: str) -> str:
    """Tira o ruído que o yt-dlp põe na frente e o caminho do arquivo do fim.

    Vale mesmo para o que não foi traduzido: "ERROR: [youtube] dQw4w9WgXcQ: ..." começa
    com três pedaços que não dizem nada a ele.
    """
    texto = re.sub(r"^ERROR:\s*", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"^\[[^\]]+\]\s*", "", texto)  # [youtube], [download]
    texto = re.sub(r"^[A-Za-z0-9_-]{11}:\s*", "", texto)  # o ID do vídeo
    texto = re.sub(r"\s*;\s*please report this issue.*$", "", texto, flags=re.IGNORECASE | re.DOTALL)
    return texto.strip() or "Não deu certo."
