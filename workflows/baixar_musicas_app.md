# Workflow: Baixador de Músicas e Vídeos (RE Play)

## Objetivo

App desktop para o usuário baixar músicas e vídeos (individuais ou playlists) do YouTube e Spotify sem sites cheios de propaganda. Interface de um campo único e **dois botões**: cola o link (ou o nome da música) e escolhe **♪ Música** (MP3) ou **▶ Vídeo** (MP4).

## Onde está

- Código: `app/` (`main.py`, `gui/`, `core/`)
- Repositório: **github.com/BigVirto/roger-eventos** (público) — também é de onde o app baixa suas próprias atualizações
- Downloads: `downloads/<nome da playlist/evento>/` (playlists e álbuns) ou direto em `downloads/` (faixa avulsa)
- Na máquina do usuário: programa em `%LOCALAPPDATA%\Programs\REPlay`, dados (config, log, atualizações) em `%LOCALAPPDATA%\RogerEventos` (nome antigo, mantido de propósito — ver `core/organizer.py`), músicas em `Músicas\RE Play` e **vídeos em `Vídeos\RE Play`**

## Como funciona (um campo, dois botões)

O app detecta sozinho **de onde** veio o link; quem decide **o que sai** é o botão:

| Colou | ♪ Música | ▶ Vídeo |
|---|---|---|
| Playlist/álbum do Spotify | Lê a lista pela página pública, busca cada faixa no YouTube e baixa em MP3 | Busca o **clipe** de cada faixa e baixa em MP4 |
| Faixa do Spotify | Mesma coisa, uma faixa só | O clipe daquela faixa |
| Playlist do YouTube | Baixa o áudio de todos | Baixa os vídeos completos |
| Vídeo do YouTube | Só o áudio | O vídeo inteiro |
| Nome de música (sem link) | Busca e baixa o áudio do primeiro resultado | Busca e baixa o vídeo |

**Por que dois botões e não um seletor de modo:** a escolha acontece no clique e não fica ligada. Um seletor esquecido em "vídeo" transformaria a próxima playlist de 500 MB numa de 7 GB sem ele perceber. O `<Enter>` no campo continua sendo música — é o uso do dia a dia.

Para tudo que vem do Spotify, a escolha do vídeo no YouTube usa a **duração da faixa original como critério** (`core/matcher.py`, tolerância ±5s) — é isso que evita baixar videoclipe, versão ao vivo ou remix no lugar do áudio de estúdio. Faixas cuja melhor correspondência ficou fora da tolerância aparecem no log como "ATENÇÃO (confira essa)" ao final, sem interromper o resto.

Música sai em **MP3 320kbps**, o padrão usado por DJs em festas (qualidade alta com arquivo pequeno). Vídeo sai em **MP4 1080p com H.264 + AAC** — ver a seção "Vídeo" para o porquê de *não* ser "a melhor qualidade disponível".

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
o usuário não recebe arquivo, não clica em nada, só abre o app e já está atualizado.

Funciona porque `core/` e `gui/` são Python puro (~26 KB zipados). O `.exe` continua o
mesmo; só os arquivos de texto são trocados. `core/atualizador_app.py` faz o trabalho,
usando o mesmo truque de `core/atualizador.py`, que já fazia isso com o yt-dlp.

**Onde fica:** repositório **público** `github.com/BigVirto/roger-eventos`, definido em
`REPOSITORIO` (`core/atualizador_app.py`). O app consulta o release mais recente de lá.
Apagar esse repositório, torná-lo privado ou renomeá-lo **para as atualizações em
silêncio** — o app segue funcionando e ninguém é avisado.

**Como publicar uma versão:**

```
1. subir o número em app/core/versao.py         (sem isso o app ignora o pacote)
2. python tools/publicar_atualizacao.py --publicar
```

### O que a máquina precisa ter para publicar

O `git` sozinho não basta: release é um recurso do GitHub, não do git.

```
winget install GitHub.cli
gh auth login          → GitHub.com / HTTPS / "Authenticate Git?" NÃO / navegador
```

Responder **não** a "Authenticate Git with your GitHub credentials?" é proposital: o
envio por git já funciona e essa opção mexeria na configuração de credencial.

> **Cuidado com a conta errada — já aconteceu.** Esta máquina tem duas contas do GitHub
> guardadas no Windows: `VitorV4` (antiga) e `BigVirto` (dona do repositório). O primeiro
> `git push` foi tentado com a antiga e voltou `Permission denied ... 403`, sem deixar
> claro que o problema era a conta. Resolvido fixando a conta **neste repositório**, sem
> tocar na outra:
>
> ```
> git config credential.https://github.com.username BigVirto
> git config credential.useHttpPath true
> ```
>
> Ao clonar em outra máquina, repetir isso se houver mais de uma conta salva. No
> `gh auth login`, conferir também que o navegador está logado como `BigVirto`.

### A primeira entrega ainda é manual

Uma máquina só entra no caminho automático depois de ter a **1.2.0 ou mais nova**
instalada — é o instalador que traz a capacidade de se atualizar, e o app não tem como
aprendê-la sozinho. Quem ficar numa versão anterior nunca recebe nada e não avisa.

Vale instalar também numa máquina de quem mantém o app: assim toda atualização passa por
ele antes de chegar no usuário, de graça.

O app do usuário verifica a cada 6 horas. **A troca vale na abertura seguinte** — quem
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

**Saída manual:** `REPlay-BaixadorDeMusicas.exe --reverter` apaga a atualização e
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

### Atualiza sem pedir, mas não sem contar

**Não perguntamos "deseja atualizar?".** O usuário não teria como decidir: ele não sabe
o que mudou nem o que perde ao recusar. Uma pergunta dessas vira "sim" automático (não
serviu para nada) ou "não" (ele fica com o app quebrado sem saber que escolheu isso). A
maioria das atualizações conserta justamente o YouTube ter mudado — recusar é escolher
continuar quebrado.

**Mas ele é avisado depois**, de duas formas discretas:

- **Versão no rodapé da janela.** Diante de um "parou de funcionar", é só perguntar o
  número que aparece ali. Antes isso só existia no `registro.txt`, que ele nunca abriria.
- **Uma linha no log quando a versão mudou**: *"O app foi atualizado para a versão X"*.
  Sem botão e sem interromper — uma caixa com OK só treinaria o reflexo de fechar sem ler.

O motivo mais forte é prático: sem isso, uma mudança de comportamento vira um chamado de
suporte em que ninguém sabe que o código trocou no meio.

> **`versao_embutida()` lê de variável de ambiente, não da constante.** `main.py` grava
> `RE_PLAY_VERSAO_EXE` antes de trocar o código. Sem isso, depois de uma
> atualização o próprio `atualizador_app` passaria a ser o baixado e sua constante
> devolveria a versão da atualização — fazendo `core/atualizador.py` concluir que o
> `.exe` foi reinstalado e rebaixar o yt-dlp a cada atualização do app.

## Entregar ao usuário: o instalador

O que se manda para ele é **`instalador/Saida/Instalar-REPlay-BaixadorDeMusicas.exe`** (~142 MB). Ele executa, clica em Avançar e ganha atalho na Área de Trabalho e no Menu Iniciar.

```
cd app
pyinstaller build.spec                                    (1. gera o .exe)
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" ..\instalador\RogerEventos.iss   (2. empacota)
```

Inno Setup é gratuito (`winget install JRSoftware.InnoSetup`). O winget instala **por usuário**, em `%LOCALAPPDATA%\Programs\Inno Setup 6` — não em Arquivos de Programas, onde é natural procurar.

A versão do instalador é **lida de `app/core/versao.py`** pelo pré-processador do Inno —
não há número duplicado para esquecer de subir. Sem isso, o instalador dizia sempre
1.0.0 e era impossível saber o que o usuário tinha instalado.

**Decisões do instalador (`instalador/RogerEventos.iss`) e o porquê:**

- **`PrivilegesRequired=lowest`** → instala em `%LOCALAPPDATA%\Programs\REPlay`. Instalar em "Arquivos de Programas" exigiria administrador **e o Windows bloquearia a escrita do app**. É o mesmo modelo do Chrome e do VS Code.
- **As músicas vão para `Músicas\RE Play`** (lido do registro do Windows, não `~/Music` chutado — muita gente tem essa pasta movida pelo OneDrive).
- **Config, log e atualizações vão para `%LOCALAPPDATA%\RogerEventos`** (`organizer.pasta_dados()`), separados do local de instalação. Sem isso, uma instalação em pasta protegida faria o app abrir mas não gravar nada.
- **Desinstalar NÃO apaga as músicas** — só a config e o log. As músicas são o trabalho do usuário. *Testado: criei um MP3, desinstalei, o arquivo sobreviveu e a config foi removida.*

**O aviso azul do Windows (SmartScreen) vai aparecer** no primeiro uso, com ou sem instalador: o executável não tem assinatura digital paga (~US$200/ano, não compensa para uso interno). Orientar: "Mais informações" → "Executar assim mesmo".

## Gerar o .exe para o usuário

```
cd app
pyinstaller build.spec
```

Saída: `app\dist\REPlay-BaixadorDeMusicas.exe`.

> **Fechar o app antes de regerar.** Com o `.exe` aberto, o PyInstaller falha com
> `PermissionError: [WinError 5] Acesso negado` e **mantém o executável antigo no lugar**.
> Em 2026-08-07 isso me custou uma rodada inteira de testes contra um binário velho, com
> resultados que pareciam um bug no código.
>
> Pior: `pyinstaller ... | tail -3` devolve o código de saída do `tail`, não do
> PyInstaller — a build falhada aparecia como sucesso. **Conferir o código de saída sem
> cano no meio, e conferir a data do `.exe` gerado.**

**Esse `.exe` é o único arquivo a distribuir.** Ele leva Python, bibliotecas e o ffmpeg embutidos. Na máquina do usuário é só copiar e dar duplo-clique — sem instalar Python, sem instalar ffmpeg, sem configurar credencial, sem arquivo do lado.

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
2. `_executar_com_fallback()` tenta o download normalmente e, ao detectar bloqueio de bot, repete usando cookies do navegador do usuário (Chrome → Edge → Firefox → Brave → Opera → Vivaldi), memorizando qual funcionou. Zero configuração para o usuário.
3. **Deno empacotado** (`tools/baixar_deno.py` → `app/bin/deno.exe`): o yt-dlp precisa de um runtime JavaScript para resolver os desafios do YouTube; sem ele cai em caminhos lentos/frágeis.
4. `eh_playlist()` passou a decidir pela URL, sem consultar a rede — **sozinho economizou 322s por download avulso**, porque a consulta era feita e logo repetida pelo download.

**Se voltar a falhar:** primeiro `pip install -U yt-dlp` e regerar o `.exe` — a maioria dos bloqueios novos é corrigida upstream rapidamente. Depois disso, verificar se o Deno continua sendo baixado corretamente e se algum navegador do usuário tem sessão válida no YouTube.

**Cuidado ao testar:** rodar muitos downloads seguidos do mesmo IP ativa o 429 e contamina qualquer medição de velocidade. Se os tempos parecerem absurdos, verifique o bloqueio antes de otimizar o código.

## Vídeo (MP4) — adicionado em 1.3.0

Evento tem telão: clipe, vídeo de abertura, retrospectiva. O botão **▶ Vídeo** cobre isso. Baixar em si é fácil (o yt-dlp já faz); o que decide se presta são quatro detalhes.

**1. Formato: NÃO usar "melhor qualidade".** Sem pedir nada, o YouTube entrega VP9 ou AV1 dentro de WebM — e VirtualDJ, Serato Video e Resolume **não abrem isso**. O arquivo baixa, tem o tamanho certo, o nome certo, e só falha na hora do evento. `core/youtube.py` pede **H.264 + AAC em MP4, até 1080p**, com um `FFmpegVideoRemuxer` como rede de segurança.

O autoteste confere isso com **ffprobe** (já empacotado): exige `h264` **e** `aac` no arquivo final. Sem essa checagem, um WebM passaria como sucesso.

### O cliente decide a resolução, não o seletor (defeito da 1.3.0)

**A 1.3.0 saiu entregando 360p** e o autoteste dizia "TUDO OK". Vale entender inteiro, porque é o tipo de erro que volta.

O YouTube oferece **listas de formatos diferentes conforme o aparelho** que se conecta. Medido em 2026-08-08: `android` e `mweb` — justamente os únicos que passavam no bloqueio anti-bot — oferecem **só 360p**. `web_embedded` oferece H.264 até 1080p. Nenhum seletor de formato conserta isso: não dá para escolher o que não foi oferecido.

Daí `CLIENTES_VIDEO` ser uma lista separada, com `web_embedded` na frente, e a memória do cliente que funcionou ser **separada por tipo de mídia** (`_memoria_cliente`). Com uma memória só, baixar uma música memorizava `android` e o vídeo seguinte saía em 360p — silenciosamente.

> **`tv_embedded` não existia mais** e estava na lista desde antes, sem fazer nada. O yt-dlp renomeia/remove clientes entre versões, e um nome inválido falha em silêncio. Ao mexer aqui, conferir contra `yt_dlp.extractor.youtube._base.INNERTUBE_CLIENTS`.

Duas armadilhas do seletor, ambas pegas por teste e não a olho nu:

- **Pedir H.264 acima de tudo escolhia 360p em H.264 no lugar de 1080p em VP9.** Por isso `format_sort` começa por `res:` — resolução manda, codec desempata dentro dela.
- **Sem `acodec:aac` explícito, o yt-dlp juntava imagem H.264 com som `opus`**, que a maioria dos programas de DJ não toca. O arquivo parecia perfeito.

**O autoteste ganhou uma checagem que não baixa nada** (`_testar_resolucao_disponivel`): pergunta ao YouTube que resoluções o cliente de vídeo enxerga num clipe sabidamente 1080p, e reprova se só houver coisa abaixo de 720p. É o que teria pego o defeito na origem — o teste antigo baixava um vídeo de 2005 que é **240p nativo**, com teto de 480p, então aprovava qualquer coisa. **Testar resolução exige um vídeo que tenha resolução.**

Toda entrega de vídeo grava no `registro.txt` a resolução obtida e o cliente usado. Sem isso, "baixou ruim" não tem como ser diagnosticado à distância.

**2. Pasta separada** (`Vídeos\RE Play`, chave `pasta_videos`). Serato e Rekordbox varrem a pasta de músicas para montar a biblioteca — um MP4 de 200 MB no meio dos MP3 entra como faixa e bagunça o acervo de trabalho dele. Os botões "Abrir pasta"/"Alterar pasta" agem sobre a mídia do último download, e o rodapé diz qual é.

**3. Clipe, não áudio com imagem parada** (`matcher.escolher_melhor_clipe`). Buscar por duração pura — o que serve perfeitamente para música — traz os canais "- Topic", que são **capa estática**: ótimos como MP3, inúteis no telão. Para vídeo a tolerância sobe para ±30s (clipe tem intro e créditos, quase sempre dura mais que a faixa) e, dentro dela, clipe declarado ganha de upload comum, que ganha de áudio parado. Só sobrou áudio parado? Baixa e marca como "confira" — não falha.

**4. Tamanho.** MP3 tem ~10 MB, clipe em 1080p tem ~150 MB; uma playlist de 50 vira ~7 GB. Antes de começar uma playlist de vídeo o app estima (~25 MB/minuto), mostra o total e o espaço livre, e **se não couber, falha antes** em vez de encher o disco no meio.

> **Duas armadilhas que o vídeo trouxe** — as duas foram corrigidas, mas ambas são fáceis de reintroduzir:
>
> **`_limpar_parciais` apagava o arquivo pronto.** Ela preserva o arquivo final e apaga todo o resto; com `.mp3` cravado, um MP4 completo caía no "resto" e sumia — justamente ao cancelar ou ao repetir um download. Agora recebe a extensão da mídia em curso. **Nunca voltar a fixar a extensão nessa função.**
>
> **A barra de progresso andava para trás.** Vídeo baixa dois fluxos (imagem e som) e cada um dispara o hook de 0 a 100%. `_Progresso` guarda a fração **por arquivo** e divide pelo número de partes (`partes_por_item`: 1 para música, 2 para vídeo). Juntar imagem e som depois leva segundos com a barra em 100% — daí o `postprocessor_hooks` avisando "juntando imagem e som...".

**Link avulso de vídeo consulta o título antes de baixar** (`youtube.obter_titulo`, ~2s). Sem saber o nome do arquivo antes, o app não tem como responder duas perguntas: *já está na pasta?* e *o que apagar se ele cancelar?* Descoberto testando: sem essa consulta, colar o mesmo link duas vezes rebaixava os 200 MB, e cancelar no meio deixava `.part` e `.webp` para trás.

> **Isso vale só para vídeo.** Para música o download inteiro leva ~10s e os 2s não se pagariam; além disso, o caminho da música nomeia pelo `%(title)s` do yt-dlp desde sempre, e trocar o esquema de nome faria o usuário rebaixar a biblioteca que já tem. **Não estender essa consulta à música sem resolver o nome legado.**

**Onde tudo isso vive:** `PerfilMidia` em `core/pipeline.py` concentra o que muda entre música e vídeo (extensão, pasta, função de download, critério de escolha, número de fluxos). Preferir estender o perfil a espalhar `if é vídeo` pelo arquivo.

## Robustez (fase 2)

**Metadados ID3 + capa** (`core/metadata.py`): sem tags, Serato/Rekordbox/VirtualDJ mostram a biblioteca desorganizada — eles leem as tags, não o nome do arquivo. Faixas do YouTube recebem tags via pós-processadores do yt-dlp (`FFmpegMetadata` + `EmbedThumbnail`). Faixas do Spotify são **sobrescritas depois** com `mutagen` usando os dados exatos do Spotify, porque o título do vídeo do YouTube vem sujo ("... (Official Video) [HD] 4K"). O campo `album` recebe o nome da playlist/evento, agrupando o set no software de DJ. `mutagen` já vem junto por ser dependência do yt-dlp.

**Não rebaixa o que já existe** (`_ja_existe` em `core/pipeline.py`): antes de baixar, verifica se o `.mp3` já está lá com tamanho > 100 KB. Repetir uma playlist de 50 faixas passa a levar segundos. O limite de tamanho evita confundir arquivo truncado com download completo.

**Retentativa por faixa** (`_com_retentativa`): até 3 tentativas com espera de 2s e 5s. **Não repete** quando `youtube.e_bloqueio_definitivo()` diz que é inútil (vídeo privado/removido, ou bloqueio que já esgotou todos os clientes e cookies) — insistir aí só faria o usuário esperar sem chance de sucesso. Parciais são limpos antes de cada nova tentativa.

**Atualização automática do yt-dlp** (`core/atualizador.py`): o yt-dlp vai congelado no `.exe` e quebra quando o YouTube muda algo — e o usuário não tem como regerar o executável. Uma vez por semana, em segundo plano, o app consulta o GitHub; se houver versão nova, baixa o sdist e extrai só o pacote `yt_dlp/` para `atualizacoes/` ao lado do `.exe` (yt-dlp é Python puro: `tarfile`+`urllib`, sem pip). No arranque seguinte, `main.py` chama `atualizador.preparar_sys_path()` **antes de qualquer import de yt_dlp**.

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

**Relatório de erros** (`core/registro.py`): `registro.txt` ao lado do `.exe`, com rotação (2 MB, 2 cópias). Botão no rodapé abre no Bloco de Notas. Registra o pedido, cada falha com traceback, as faixas marcadas como duvidosas (com a diferença de duração) e o resumo. É o que permite diagnosticar um problema na máquina do usuário sem estar lá.

Toda abertura grava também a **versão em uso e se ela é a embutida ou a atualizada** —
sem isso, diante de um relato de erro não haveria como saber qual código ele está
rodando, já que o `.exe` e o código podem estar em versões diferentes.

> **Cuidado com `_limpar_parciais`:** ela lista o que sobrou e apaga tudo que não seja um MP3 completo, em vez de enumerar extensões. Uma versão anterior listava só `.part`/`.ytdl`/`.mp3` e deixava a miniatura `.webp` para trás. O yt-dlp deixa também `.m4a`/`.webm`. O nome é escapado antes do glob porque música com `[`, `]` ou `?` no título quebraria o padrão.

**Pasta de destino escolhida pelo usuário** (`core/organizer.py`): botão "Alterar pasta" abre o seletor do Windows e a escolha fica em `configuracao.json` ao lado do `.exe`. Antes de aceitar, o app **testa se consegue gravar** (pendrive travado / pasta protegida falhariam só no meio de um download). Se a pasta salva sumir depois, `obter_pasta_downloads()` volta à padrão em vez de estourar erro.

> **Nunca voltar a usar uma constante de módulo para essa pasta.** Ela precisa ser lida por função (`obter_pasta_downloads()`), senão a escolha do usuário só valeria depois de reiniciar o app.

**Nome do arquivo: música primeiro** — `{música} - {artista}.mp3`. Mudou em 2026-08-07: numa festa se procura pelo nome da música, não pelo artista. `nome_arquivo_faixa_legado()` guarda o formato antigo (`{artista} - {música}`) **só** para `_ja_existe` reconhecer downloads anteriores e não baixar tudo de novo — não remover sem antes considerar quem já tem biblioteca no formato antigo.

### O que conta como "já baixado"

`_ja_existe()` exige as três condições: **mesma pasta**, **nome de arquivo idêntico** (novo ou legado) e **tamanho > 100 KB**. É comparação de nome, não da música. Consequências assumidas:

- a mesma música em duas playlists baixa duas vezes (proposital: cada evento tem sua pasta completa);
- grafias diferentes de artista ("Anitta" vs "Anitta, KBrum") geram arquivos distintos;
- a mesma música vinda do Spotify e de um link do YouTube gera dois arquivos, porque o caminho do YouTube nomeia pelo título do vídeo.

Resolve bem o caso real (repetir uma playlist não rebaixa nada). Uma detecção de duplicatas de verdade exigiria normalizar acentos/maiúsculas ou usar o ID do vídeo como identidade — só fazer se incomodar na prática.

## Relatório automático de erros (chega no GitHub sozinho)

Desde 2026-08-08, um erro na máquina do usuário não fica mais preso lá. O caminho:

```
app (core/ocorrencias.py)  ──▶  Apps Script (Google, a "caixa de correio")  ──▶  Issue no GitHub
```

**Como o erro é capturado**: `core/ocorrencias.py` pendura um `logging.Handler` no
mesmo logger que `core/registro.py` já usa (`_pendurar_relator` em `registro.py`). Todo
`registro.erro()` que já existe em `pipeline.py`/`youtube.py`/`main_window.py` — e
qualquer um escrito no futuro — vira ocorrência **sem precisar alterar esses arquivos**.
`sys.excepthook` e `threading.excepthook` cobrem o que estoura fora de qualquer `try`.

**Por que não fala direto com o GitHub**: criar Issue exige uma chave, e chave dentro do
`.exe` é extraível (repositório público) e **vence com o tempo** — quando vencesse, o
envio morreria em silêncio, exatamente o que este sistema existe para evitar. Por isso o
app só deposita a ficha num endereço que **só recebe** (`URL_RECEPTOR` em
`ocorrencias.py`, vazio até ser configurado); a chave mora do lado de quem mantém o app,
nunca no app. Ver o cabeçalho de `tools/receptor_erros.gs` para instalar o Apps Script (uma vez
só: colar o script, guardar `GITHUB_TOKEN`/`GITHUB_REPO` em Script Properties, implantar
como Web App, colar a URL gerada em `ocorrencias.py` e publicar uma atualização).

**Agrupamento**: cada ficha carrega uma impressão digital (tipo do erro + últimos passos
do traceback por arquivo/função, sem número de linha). O receptor procura Issue aberta
com esse rótulo antes de criar uma nova — é o que faz uma playlist com 50 falhas iguais
virar **um** chamado dizendo "50x", em vez de 50 chamados que ninguém vai ler.
`tools/ver_erros.py` lista ordenado por quantas vezes aconteceu.

**Mascaramento**: `_mascarar()` troca `C:\Users\<nome>\...` por `~` em tudo que sai —
é a única informação pessoal que passaria pelo traceback ou pelo caminho de download.

**Nunca atrasa nem derruba o app**: o envio roda em thread daemon (mesmo padrão das
duas threads de atualização) e toda função de `ocorrencias.py` engole exceção. Sem
internet, a ficha fica em `pasta_dados()/ocorrencias/*.json` e sai na próxima abertura.
Teto de 20 envios/dia e 50 arquivos na fila, para um defeito em laço não virar enxurrada.

**O que o usuário vê**: uma linha explicando o envio na primeira abertura, e depois
*"Problema já relatado (relatório #a3f9c1)"* quando algo falha. O botão
"📨 Relatar problema" manda a fila na hora ou abre um relato manual — a saída para quando
o app não acusou erro nenhum mas o resultado saiu errado (ninguém automatiza isso).
Desligar: `enviar_erros: false` em `configuracao.json`.

**Testar sem gerar `.exe`**: `python tools/testar_envio_erros.py` provoca erros de
mentira pelo caminho real e confere agrupamento/mascaramento localmente;
`--enviar` manda de verdade (exige `URL_RECEPTOR` preenchido);
`--autoteste` valida só o caminho de ponta a ponta com uma Issue que abre e fecha na
hora. `python tools/ver_erros.py` lê os chamados pelo terminal (precisa do `gh`
autenticado).

**Onde ficam os chamados**: repositório **privado** separado do app (ex.:
`roger-eventos-erros`). O repositório do app continua público — a atualização
automática depende disso — mas os relatórios carregam o link que o usuário colou e
trechos do registro, e não precisam ficar visíveis à internet inteira.

## Limitações conhecidas

- **Playlists do Spotify acima de ~50 faixas**: a página pública devolve a lista em blocos e pode não trazer tudo. O app avisa no log quando o total cai num tamanho suspeito. Não validado com playlist grande de verdade — o usuário trabalha com playlists menores que isso.
- **Formato da página do Spotify pode mudar**: ver "Decisões técnicas" acima.
- **yt-dlp precisa ser atualizado periodicamente** (`pip install -U yt-dlp`) quando o YouTube muda algo — o projeto costuma lançar correção rápido. Depois de atualizar, gerar o `.exe` de novo.
- **Uso comercial**: baixar do YouTube para tocar em eventos pagos pode esbarrar em direitos autorais e nos Termos de Uso do YouTube. O app resolve o lado técnico; licenciamento musical para eventos (ECAD etc.) é responsabilidade do usuário. Com vídeo isso fica mais visível: exibir clipe em telão é execução pública de obra audiovisual.
- **Vídeo não tem escolha de resolução na janela**: é sempre até 1080p. Existe a chave `ALTURA_MAXIMA_VIDEO` em `core/youtube.py` para mudar isso no código; só virar botão se ele pedir.
- **Cancelar durante a junção de imagem e som não interrompe**: essa etapa (ffmpeg) leva alguns segundos e não é cancelável no meio. O cancelamento vale durante o download, que é a parte longa.
- **Vídeo do Spotify depende de existir clipe no YouTube**: se a faixa só tiver upload de áudio com capa estática, é isso que vem — marcado como "pode ser só o áudio, sem imagem" no final.

## Aprendizados / ajustes futuros

- 2026-08-06: avaliado spotDL e a API oficial do Spotify; ambos descartados pelos motivos acima. Caminho escolhido: leitura da página pública, sem credencial.
- 2026-08-07: atualização automática do app. Avaliado baixar o `.exe` inteiro (~142 MB) e descartado: pesado e, no Windows, um programa não consegue se sobrescrever enquanto está aberto — exigiria um processo auxiliar, mais peça para quebrar. Trocar só `core/` e `gui/` resolve a grande maioria dos casos com 26 KB.
- 2026-08-07: avaliada uma trava que seguraria atualizações de sexta a domingo, para não trocar o código do app em dia de evento. **Descartada:** o usuário baixa as músicas com antecedência e deixa tudo programado antes da festa, então não há app rodando durante o evento para proteger. A trava só atrasaria correção. *Registrado aqui porque a ideia parece boa até se saber como o uso real funciona.*
- 2026-08-07: repositório **público** por decisão de quem mantém o app. Privado exigiria uma chave dentro do `.exe`, que é extraível (ou seja, protege pouco) e **vence com o tempo** — quando vencesse, as atualizações parariam em silêncio. O app não guarda credencial nem dado do usuário, então não havia o que proteger.
- 2026-08-08: relatório automático de erros. Avaliado o app criar a Issue direto no GitHub e descartado pela mesma razão do ponto acima — chave extraível do `.exe` e que vence em silêncio. Escolhido um intermediário (Apps Script) que guarda a chave do lado de quem mantém o app. Avaliado também mandar cada erro sem agrupar; descartado porque uma playlist com o YouTube bloqueado gera dezenas de falhas idênticas, e isso viraria ruído que ninguém lê — daí a impressão digital que agrupa repetições no mesmo chamado. **Pendente de ativação:** `URL_RECEPTOR` em `core/ocorrencias.py` está vazio até o Apps Script ser instalado (ver seção acima) e o repositório privado de erros ser criado; até lá o sistema fica pronto mas inerte (`enviar_pendentes` devolve 0 sem erro).
- Ajustar a tolerância de duração em `core/matcher.py` (hoje ±5s) se aparecerem muitos falsos "incerto" ou muitas versões erradas na prática.
