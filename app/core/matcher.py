"""Escolhe, entre candidatos do YouTube, o melhor para uma faixa do Spotify.

Para música o critério é duração (o áudio de estúdio dura o mesmo que no Spotify).
Para vídeo o critério muda: o que se quer é o clipe, e clipe tem vinheta, intro e
créditos — quase sempre dura mais que a faixa. Ver `escolher_melhor_clipe`.
"""

TOLERANCIA_PADRAO_S = 5

# Clipe oficial costuma passar da faixa por causa de intro/créditos. Com ±5s quase todo
# clipe seria descartado; com ±30s ainda se separa o clipe da versão ao vivo ou estendida.
TOLERANCIA_CLIPE_S = 30

# Marcas de upload que é áudio com imagem parada — serve como música, é inútil no telão.
_SINAIS_DE_AUDIO = ("- topic", "auto-generated", "lyric", "letra", "audio only",
                    "áudio oficial", "audio oficial", "(audio)", "(áudio)")

# Marcas de clipe de verdade.
_SINAIS_DE_CLIPE = ("official video", "official music video", "videoclipe", "video clipe",
                    "clipe oficial", "vídeo oficial", "video oficial", "official clip")


def escolher_melhor_candidato(
    candidatos: list[dict], duracao_alvo_ms: int, tolerancia_s: int = TOLERANCIA_PADRAO_S
) -> dict | None:
    """Retorna o candidato com duração mais próxima da faixa alvo.

    Retorna None se nenhum candidato tiver duração conhecida dentro da tolerância
    (sinal de que só sobraram clipes/ao vivo/remixes, não o áudio de estúdio).
    """
    duracao_alvo_s = duracao_alvo_ms / 1000

    validos = [c for c in candidatos if c.get("duracao_s") is not None]
    if not validos:
        return None

    melhor = min(validos, key=lambda c: abs(c["duracao_s"] - duracao_alvo_s))
    diferenca = abs(melhor["duracao_s"] - duracao_alvo_s)

    melhor = dict(melhor)
    melhor["diferenca_s"] = diferenca
    melhor["incerto"] = diferenca > tolerancia_s
    return melhor


def _parece_audio_parado(candidato: dict) -> bool:
    texto = f"{candidato.get('titulo') or ''} {candidato.get('canal') or ''}".lower()
    return any(sinal in texto for sinal in _SINAIS_DE_AUDIO)


def _parece_clipe(candidato: dict) -> bool:
    return any(sinal in (candidato.get("titulo") or "").lower() for sinal in _SINAIS_DE_CLIPE)


def escolher_melhor_clipe(
    candidatos: list[dict], duracao_alvo_ms: int, tolerancia_s: int = TOLERANCIA_CLIPE_S
) -> dict | None:
    """Retorna o melhor candidato para baixar como VÍDEO.

    Duração continua sendo o filtro (evita cair num show inteiro de 1h), mas dentro da
    tolerância a escolha passa a ser pelo tipo de upload: clipe na frente, áudio com capa
    estática no fim. Buscar só por duração traria justamente os canais "- Topic", que são
    a melhor escolha possível para música e a pior possível para o telão.

    Sem nenhum candidato dentro da tolerância, devolve o mais próximo marcado como
    `incerto` — mesmo contrato de `escolher_melhor_candidato`, que a GUI já sabe exibir.
    """
    duracao_alvo_s = duracao_alvo_ms / 1000

    validos = [c for c in candidatos if c.get("duracao_s") is not None]
    if not validos:
        return None

    dentro = [c for c in validos if abs(c["duracao_s"] - duracao_alvo_s) <= tolerancia_s]
    if dentro:
        # Menor pontuação ganha: clipe declarado (-1), comum (0), áudio parado (+1).
        # Empate desempata por duração, como antes.
        def pontuar(c: dict) -> tuple[int, float]:
            tipo = -1 if _parece_clipe(c) else (1 if _parece_audio_parado(c) else 0)
            return (tipo, abs(c["duracao_s"] - duracao_alvo_s))

        melhor = min(dentro, key=pontuar)
    else:
        melhor = min(validos, key=lambda c: abs(c["duracao_s"] - duracao_alvo_s))

    diferenca = abs(melhor["duracao_s"] - duracao_alvo_s)
    melhor = dict(melhor)
    melhor["diferenca_s"] = diferenca
    # "Incerto" para vídeo é achar só áudio com imagem parada: baixa e funciona, mas não
    # é o que ele espera ver no telão — vale a linha de atenção no final.
    melhor["incerto"] = diferenca > tolerancia_s or _parece_audio_parado(melhor)
    return melhor
