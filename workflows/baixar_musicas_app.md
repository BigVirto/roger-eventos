# Workflow: Baixador de Músicas (Roger Eventos)

## Objetivo

App desktop para o Rogério baixar músicas (individuais ou playlists) do YouTube e Spotify sem sites cheios de propaganda. Interface de um campo único: cola o link (ou o nome da música) e clica em Baixar.

## Onde está

- Código: `app/` (`main.py`, `gui/`, `core/`)
- Downloads: `downloads/<nome da playlist/evento>/` (playlists e álbuns) ou direto em `downloads/` (faixa avulsa)

## Como funciona (fluxo de um campo só)

O app detecta sozinho o que foi colado — não há abas nem modos a escolher:

| Colou | O que acontece |
|---|---|
| Playlist/álbum do Spotify | Lê a lista pela página pública, busca cada faixa no YouTube e baixa |
| Faixa do Spotify | Mesma coisa, uma faixa só |
| Playlist do YouTube | Baixa todos os vídeos direto |
| Vídeo do YouTube | Baixa só ele |
| Nome de música (sem link) | Busca no YouTube e baixa o primeiro resultado |

Para tudo que vem do Spotify, a escolha do vídeo no YouTube usa a **duração da faixa original como critério** (`core/matcher.py`, tolerância ±5s) — é isso que evita baixar videoclipe, versão ao vivo ou remix no lugar do áudio de estúdio. Faixas cuja melhor correspondência ficou fora da tolerância aparecem no log como "ATENÇÃO (confira essa)" ao final, sem interromper o resto.

Tudo sai em **MP3 320kbps**, o padrão usado por DJs em festas (qualidade alta com arquivo pequeno).

## Decisões técnicas importantes (e por quê)

**Não usamos a API oficial do Spotify.** Desde fevereiro/março de 2026 o Spotify exige que o dono da credencial tenha **assinatura Premium ativa** para usar a API em Development Mode, e desde novembro de 2024 a API **não devolve playlists editoriais** (Top Brasil, Sertanejo Hits e afins) — justamente as que mais interessam para eventos. Em vez disso, `core/spotify.py` lê a página pública de embed (`open.spotify.com/embed/...`), que é gratuita, não exige credencial nenhuma e **funciona inclusive com as editoriais** (testado e confirmado).

**Não usamos o spotDL.** O [spotDL](https://github.com/spotDL/spotify-downloader) faz exatamente isso e seria a escolha óbvia, mas a credencial do Spotify que ele traz embutida é compartilhada por todos os usuários do mundo e está **permanentemente estourada (HTTP 429)** — testado e confirmado. Usá-lo exigiria credencial própria, caindo de volta no problema do Premium.

**Consequência boa:** o app não tem credencial, não tem `.env`, não tem configuração. Nada para preencher.

**Risco assumido:** por depender do formato da página do Spotify, se eles mudarem o layout a leitura de playlist quebra e é preciso ajustar `core/spotify.py`. O código detecta isso e devolve uma mensagem clara (`SpotifyIndisponivel`) em vez de falhar de forma silenciosa. O YouTube não é afetado por isso.

## Rodar em modo desenvolvimento

```
cd "Roger Eventos"
python -m venv .venv
.venv\Scripts\activate
pip install -r app\requirements.txt
python tools\baixar_ffmpeg.py     (só se app\bin\ffmpeg.exe não existir)
python tools\baixar_deno.py       (só se app\bin\deno.exe não existir)
python app\main.py
```

Os dois scripts baixam binários oficiais para `app/bin/`. Essa pasta é ignorada pelo git (são ~300 MB), então rode os dois ao clonar o projeto num ambiente novo.

Onde as músicas são salvas:
- **Modo desenvolvimento**: `downloads/` na raiz do projeto
- **No .exe**: pasta `Músicas Baixadas`, criada **ao lado do executável**

Isso é decidido em `core/organizer.py`. **Nunca usar `__file__` para essa pasta no modo empacotado** — ele aponta para o diretório temporário do PyInstaller, e foi exatamente esse o bug que fez os downloads sumirem em `AppData\Local\Temp\downloads`.

## Atualizar o app sem mandar instalador (caminho normal)

Desde 2026-08-07 o app se atualiza sozinho. **9 de cada 10 entregas seguem por aqui** —
o Rogério não recebe arquivo, não clica em nada, só abre o app e já está atualizado.

Funciona porque `core/` e `gui/` são Python puro (~26 KB zipados). O `.exe` continua o
mesmo; só os arquivos de texto são trocados. `core/atualizador_app.py` faz o trabalho,
usando o mesmo truque de `core/atualizador.py`, que já fazia isso com o yt-dlp.

**Como publicar uma versão:**

```
1. subir o número em app/core/versao.py         (sem isso o app ignora o pacote)
2. python tools/publicar_atualizacao.py --publicar
```

O app do Rogério verifica a cada 6 horas. **A troca vale na abertura seguinte** — quem
estiver com o app aberto na hora só vê a mudança quando fechar e abrir de novo.

**O que este caminho NÃO atualiza** (aí sim precisa de instalador novo): Python, ffmpeg,
deno, ícone, nome do programa, e o próprio `app/main.py`.

> **`app/main.py` é o único arquivo congelado no `.exe`.** Ele carrega o código
> atualizado antes de importar qualquer coisa de `core/` ou `gui/`, então não pode ser
> corrigido por atualização automática. Manter o mínimo possível lá dentro — bug em
> `main.py` só se conserta com instalador.

**Três camadas para nunca deixar o app pior que estava** (todas testadas em 2026-08-07):

1. só aceita pacote com versão **maior** que a embutida — evita voltar no tempo;
2. na abertura, importa os módulos essenciais; se algum falhar, descarta e volta ao
   embutido;
3. se o app estourar erro ao abrir a janela, `main.py` descarta e pede para reabrir.

**Saída manual:** `RogerEventos-BaixadorDeMusicas.exe --reverter` apaga a atualização e
volta ao embutido. É a única saída para o caso em que o código novo abre normalmente mas
funciona mal — nenhuma checagem automática pega isso.

> **Todo descarte por problema marca a versão como recusada** (`recusada.txt` em
> `%LOCALAPPDATA%\RogerEventos\app_atualizado`). Descoberto testando o `.exe` de verdade
> em 2026-08-07: sem isso, descartar só durava até a verificação seguinte — o app
> rebaixava a mesma versão em até 6 horas e o problema voltava sozinho. A saída de
> emergência não segurava nada.
>
> A recusa vale **só para aquela versão exata**. Publicar uma mais nova continua
> chegando normalmente — é assim que o conserto alcança a máquina depois de uma
> atualização ruim.

**Para consertar uma versão ruim que já foi publicada:** subir o número em
`core/versao.py` e publicar de novo. Não adianta republicar a mesma versão corrigida —
o número já está recusado naquela máquina, e o release seria ignorado.

## Entregar ao Rogério: o instalador

O que se manda para ele é **`instalador/Saida/Instalar-RogerEventos-BaixadorDeMusicas.exe`** (~142 MB). Ele executa, clica em Avançar e ganha atalho na Área de Trabalho e no Menu Iniciar.

```
cd app
pyinstaller build.spec                                    (1. gera o .exe)
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" ..\instalador\RogerEventos.iss   (2. empacota)
```

Inno Setup é gratuito (`winget install JRSoftware.InnoSetup`). O winget instala **por usuário**, em `%LOCALAPPDATA%\Programs\Inno Setup 6` — não em Arquivos de Programas, onde é natural procurar.

A versão do instalador é **lida de `app/core/versao.py`** pelo pré-processador do Inno —
não há número duplicado para esquecer de subir. Sem isso, o instalador dizia sempre
1.0.0 e era impossível saber o que o Rogério tinha instalado.

**Decisões do instalador (`instalador/RogerEventos.iss`) e o porquê:**

- **`PrivilegesRequired=lowest`** → instala em `%LOCALAPPDATA%\Programs\RogerEventos`. Instalar em "Arquivos de Programas" exigiria administrador **e o Windows bloquearia a escrita do app**. É o mesmo modelo do Chrome e do VS Code.
- **As músicas vão para `Músicas\Roger Eventos`** (lido do registro do Windows, não `~/Music` chutado — muita gente tem essa pasta movida pelo OneDrive).
- **Config, log e atualizações vão para `%LOCALAPPDATA%\RogerEventos`** (`organizer.pasta_dados()`), separados do local de instalação. Sem isso, uma instalação em pasta protegida faria o app abrir mas não gravar nada.
- **Desinstalar NÃO apaga as músicas** — só a config e o log. As músicas são o trabalho do Rogério. *Testado: criei um MP3, desinstalei, o arquivo sobreviveu e a config foi removida.*

**O aviso azul do Windows (SmartScreen) vai aparecer** no primeiro uso, com ou sem instalador: o executável não tem assinatura digital paga (~US$200/ano, não compensa para uso interno). Orientar: "Mais informações" → "Executar assim mesmo".

## Gerar o .exe para o Rogério

```
cd app
pyinstaller build.spec
```

Saída: `app\dist\RogerEventos-BaixadorDeMusicas.exe`.

**Esse `.exe` é o único arquivo a distribuir.** Ele leva Python, bibliotecas e o ffmpeg embutidos. Na máquina do Rogério é só copiar e dar duplo-clique — sem instalar Python, sem instalar ffmpeg, sem configurar credencial, sem arquivo do lado.

## O YouTube bloqueia downloads automatizados (importante)

Este é o problema mais sério do projeto e provavelmente o que mais vai dar trabalho ao longo do tempo.

**Sintomas observados em 2026-08-06:**
- `Sign in to confirm you're not a bot` — bloqueio explícito
- `HTTP Error 429: Too Many Requests` — bloqueio por volume, ativado após ~algumas dezenas de requisições do mesmo IP
- Lentidão extrema (300s+) que na verdade era o yt-dlp **repetindo em silêncio** contra um 429

**A lentidão NÃO era o bloqueio — era IPv6.** Medido em 2026-08-07: a mesma busca levou **161,5s** no modo padrão e **1,9s** forçando IPv4 (`source_address: "0.0.0.0"`). A rota IPv6 para o YouTube fica pendurada até estourar o timeout antes de cair para IPv4. Isso explicava todos os tempos suspeitos e constantes (~162s, ~322s: múltiplos do mesmo timeout) e por que todos os clientes "falhavam" no mesmo tempo. **Se aparecerem tempos constantes e absurdos de novo, suspeite de rede antes de suspeitar do código.**

**A solução do bloqueio anti-bot é trocar de player client, não usar cookies.** O YouTube aplica regras diferentes conforme o aparelho que se conecta. Com o IP já marcado, `android` baixou normalmente em 13s enquanto `tv_embedded`/`android_vr` levavam "not a bot". `_executar_com_fallback()` percorre `CLIENTES` em ordem e memoriza o que funcionou.

**Por que não dependemos de cookies:** no Windows moderno o yt-dlp quase nunca consegue lê-los — Chrome aberto trava o banco (issue #7271) e Chrome/Edge 127+ usam App-Bound Encryption que quebra a descriptografia (issue #10927). Testado nesta máquina: os 6 navegadores falharam. Cookies ficaram só como último recurso (`cookies.txt` ao lado do .exe).

**Números depois das correções (com o IP marcado, pior caso):** 1 música em ~10s; 50 músicas em ~8 min. Antes: ~490s por música (~6,8h para 50).

**Defesas implementadas:**
1. `OPCOES_REDE` em `core/youtube.py` limita retentativas — falha em segundos com mensagem clara em vez de travar 5 minutos sem retorno.
2. `_executar_com_fallback()` tenta o download normalmente e, ao detectar bloqueio de bot, repete usando cookies do navegador do usuário (Chrome → Edge → Firefox → Brave → Opera → Vivaldi), memorizando qual funcionou. Zero configuração para o Rogério.
3. **Deno empacotado** (`tools/baixar_deno.py` → `app/bin/deno.exe`): o yt-dlp precisa de um runtime JavaScript para resolver os desafios do YouTube; sem ele cai em caminhos lentos/frágeis.
4. `eh_playlist()` passou a decidir pela URL, sem consultar a rede — **sozinho economizou 322s por download avulso**, porque a consulta era feita e logo repetida pelo download.

**Se voltar a falhar:** primeiro `pip install -U yt-dlp` e regerar o `.exe` — a maioria dos bloqueios novos é corrigida upstream rapidamente. Depois disso, verificar se o Deno continua sendo baixado corretamente e se algum navegador do usuário tem sessão válida no YouTube.

**Cuidado ao testar:** rodar muitos downloads seguidos do mesmo IP ativa o 429 e contamina qualquer medição de velocidade. Se os tempos parecerem absurdos, verifique o bloqueio antes de otimizar o código.

## Robustez (fase 2)

**Metadados ID3 + capa** (`core/metadata.py`): sem tags, Serato/Rekordbox/VirtualDJ mostram a biblioteca desorganizada — eles leem as tags, não o nome do arquivo. Faixas do YouTube recebem tags via pós-processadores do yt-dlp (`FFmpegMetadata` + `EmbedThumbnail`). Faixas do Spotify são **sobrescritas depois** com `mutagen` usando os dados exatos do Spotify, porque o título do vídeo do YouTube vem sujo ("... (Official Video) [HD] 4K"). O campo `album` recebe o nome da playlist/evento, agrupando o set no software de DJ. `mutagen` já vem junto por ser dependência do yt-dlp.

**Não rebaixa o que já existe** (`_ja_existe` em `core/pipeline.py`): antes de baixar, verifica se o `.mp3` já está lá com tamanho > 100 KB. Repetir uma playlist de 50 faixas passa a levar segundos. O limite de tamanho evita confundir arquivo truncado com download completo.

**Retentativa por faixa** (`_com_retentativa`): até 3 tentativas com espera de 2s e 5s. **Não repete** quando `youtube.e_bloqueio_definitivo()` diz que é inútil (vídeo privado/removido, ou bloqueio que já esgotou todos os clientes e cookies) — insistir aí só faria o usuário esperar sem chance de sucesso. Parciais são limpos antes de cada nova tentativa.

**Atualização automática do yt-dlp** (`core/atualizador.py`): o yt-dlp vai congelado no `.exe` e quebra quando o YouTube muda algo — e o Rogério não tem como regerar o executável. Uma vez por semana, em segundo plano, o app consulta o GitHub; se houver versão nova, baixa o sdist e extrai só o pacote `yt_dlp/` para `atualizacoes/` ao lado do `.exe` (yt-dlp é Python puro: `tarfile`+`urllib`, sem pip). No arranque seguinte, `main.py` chama `atualizador.preparar_sys_path()` **antes de qualquer import de yt_dlp**.

> **Regra de ouro do atualizador:** uma atualização ruim nunca pode deixar o app pior que estava. Se o `yt_dlp` atualizado não importar, `preparar_sys_path()` apaga a pasta e volta ao embutido. Isso foi testado com um pacote propositalmente corrompido.
>
> **Não publicam wheel (.whl)** — por isso usamos o sdist. Se um dia isso mudar, o wheel seria mais simples (dá para importar direto do zip).
>
> **Bug corrigido em 2026-08-07:** a pasta baixada entrava na frente do embutido **sem
> comparar versões**. Ao instalar um `.exe` novo (que já traz yt-dlp recente), o app
> continuava usando o pacote velho do AppData por até uma semana — exatamente o caso de
> "publiquei a correção e não adiantou". Agora um carimbo guarda sob qual versão do app
> o pacote foi baixado; se o `.exe` mudou, descarta e zera a marca semanal para rebaixar
> no mesmo dia. Comparar as versões de verdade custaria ~1s de import em toda abertura.

**Cancelar** (`CancelamentoSolicitado` em `core/pipeline.py`): a GUI passa um `threading.Event`; a checagem fica **dentro do `hook_ytdlp`**, não só entre faixas — sem isso, cancelar no meio de um arquivo de 20 MB só teria efeito quando ele terminasse. Ao cancelar, os parciais da faixa em curso são apagados e o que já concluiu permanece.

**Relatório de erros** (`core/registro.py`): `registro.txt` ao lado do `.exe`, com rotação (2 MB, 2 cópias). Botão no rodapé abre no Bloco de Notas. Registra o pedido, cada falha com traceback, as faixas marcadas como duvidosas (com a diferença de duração) e o resumo. É o que permite diagnosticar um problema na máquina do Rogério sem estar lá.

Toda abertura grava também a **versão em uso e se ela é a embutida ou a atualizada** —
sem isso, diante de um relato de erro não haveria como saber qual código ele está
rodando, já que o `.exe` e o código podem estar em versões diferentes.

> **Cuidado com `_limpar_parciais`:** ela lista o que sobrou e apaga tudo que não seja um MP3 completo, em vez de enumerar extensões. Uma versão anterior listava só `.part`/`.ytdl`/`.mp3` e deixava a miniatura `.webp` para trás. O yt-dlp deixa também `.m4a`/`.webm`. O nome é escapado antes do glob porque música com `[`, `]` ou `?` no título quebraria o padrão.

**Pasta de destino escolhida pelo usuário** (`core/organizer.py`): botão "Alterar pasta" abre o seletor do Windows e a escolha fica em `configuracao.json` ao lado do `.exe`. Antes de aceitar, o app **testa se consegue gravar** (pendrive travado / pasta protegida falhariam só no meio de um download). Se a pasta salva sumir depois, `obter_pasta_downloads()` volta à padrão em vez de estourar erro.

> **Nunca voltar a usar uma constante de módulo para essa pasta.** Ela precisa ser lida por função (`obter_pasta_downloads()`), senão a escolha do usuário só valeria depois de reiniciar o app.

**Nome do arquivo: música primeiro** — `{música} - {artista}.mp3`. Mudou em 2026-08-07 a pedido do Vitor: numa festa se procura pelo nome da música, não pelo artista. `nome_arquivo_faixa_legado()` guarda o formato antigo (`{artista} - {música}`) **só** para `_ja_existe` reconhecer downloads anteriores e não baixar tudo de novo — não remover sem antes considerar quem já tem biblioteca no formato antigo.

### O que conta como "já baixado"

`_ja_existe()` exige as três condições: **mesma pasta**, **nome de arquivo idêntico** (novo ou legado) e **tamanho > 100 KB**. É comparação de nome, não da música. Consequências assumidas:

- a mesma música em duas playlists baixa duas vezes (proposital: cada evento tem sua pasta completa);
- grafias diferentes de artista ("Anitta" vs "Anitta, KBrum") geram arquivos distintos;
- a mesma música vinda do Spotify e de um link do YouTube gera dois arquivos, porque o caminho do YouTube nomeia pelo título do vídeo.

Resolve bem o caso real (repetir uma playlist não rebaixa nada). Uma detecção de duplicatas de verdade exigiria normalizar acentos/maiúsculas ou usar o ID do vídeo como identidade — só fazer se incomodar na prática.

## Limitações conhecidas

- **Playlists do Spotify acima de ~50 faixas**: a página pública devolve a lista em blocos e pode não trazer tudo. O app avisa no log quando o total cai num tamanho suspeito. Não validado com playlist grande de verdade — o Rogério trabalha com playlists menores que isso.
- **Formato da página do Spotify pode mudar**: ver "Decisões técnicas" acima.
- **yt-dlp precisa ser atualizado periodicamente** (`pip install -U yt-dlp`) quando o YouTube muda algo — o projeto costuma lançar correção rápido. Depois de atualizar, gerar o `.exe` de novo.
- **Uso comercial**: baixar do YouTube para tocar em eventos pagos pode esbarrar em direitos autorais e nos Termos de Uso do YouTube. O app resolve o lado técnico; licenciamento musical para eventos (ECAD etc.) é responsabilidade do Rogério.

## Aprendizados / ajustes futuros

- 2026-08-06: avaliado spotDL e a API oficial do Spotify; ambos descartados pelos motivos acima. Caminho escolhido: leitura da página pública, sem credencial.
- 2026-08-07: atualização automática do app. Avaliado baixar o `.exe` inteiro (~142 MB) e descartado: pesado e, no Windows, um programa não consegue se sobrescrever enquanto está aberto — exigiria um processo auxiliar, mais peça para quebrar. Trocar só `core/` e `gui/` resolve a grande maioria dos casos com 26 KB.
- 2026-08-07: repositório **público** por decisão do Vitor. Privado exigiria uma chave dentro do `.exe`, que é extraível (ou seja, protege pouco) e **vence com o tempo** — quando vencesse, as atualizações parariam em silêncio. O app não guarda credencial nem dado do Rogério, então não havia o que proteger.
- Ajustar a tolerância de duração em `core/matcher.py` (hoje ±5s) se aparecerem muitos falsos "incerto" ou muitas versões erradas na prática.
