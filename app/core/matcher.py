"""Escolhe, entre candidatos do YouTube, o que mais se aproxima da duração de uma faixa do Spotify."""

TOLERANCIA_PADRAO_S = 5


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
