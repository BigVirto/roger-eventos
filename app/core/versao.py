"""Versão do app. Fonte única — o instalador e o atualizador leem daqui.

Subir a cada entrega. O formato é `maior.menor.correcao`, comparado como números
(não como texto), para que 1.10.0 seja corretamente maior que 1.9.0.

Onde isso aparece:
- `tools/publicar_atualizacao.py` grava este número no pacote de atualização
- `core/atualizador_app.py` só aceita um pacote com versão MAIOR que esta
- `instalador/RogerEventos.iss` mostra este número em "Aplicativos instalados"
"""

VERSAO = "1.1.0"


def como_tupla(versao: str) -> tuple[int, ...]:
    """Converte "1.10.0" em (1, 10, 0) para comparar como número.

    Comparar versão como texto é armadilha clássica: "1.9.0" > "1.10.0" em ordem
    alfabética. Partes não numéricas viram 0 em vez de estourar erro — versão
    ilegível deve ser tratada como antiga, nunca derrubar o app.
    """
    partes = []
    for parte in versao.strip().split("."):
        try:
            partes.append(int(parte))
        except ValueError:
            partes.append(0)
    return tuple(partes)
