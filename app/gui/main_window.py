"""Janela principal: um campo de link, dois botões e acesso às pastas de destino.

A GUI não contém lógica de download/busca — só orquestração visual. Todo o trabalho
acontece em core/pipeline.py, numa thread separada para a janela nunca travar.

Música e vídeo são dois BOTÕES, não um seletor de modo. A escolha acontece no clique e
não fica ligada: um seletor esquecido em "vídeo" transformaria a próxima playlist de
500 MB numa de 7 GB sem ele perceber.
"""

import queue
import subprocess
import threading
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import mensagens, ocorrencias, registro
from core.atualizador_app import versao_mudou_desde_a_ultima_vez
from core.organizer import (
    abrir_pasta,
    definir_config,
    definir_pasta_downloads,
    definir_pasta_videos,
    obter_config,
    obter_pasta_downloads,
    obter_pasta_videos,
)
from core.pipeline import (
    MUSICA,
    VIDEO,
    CancelamentoSolicitado,
    EspacoInsuficiente,
    processar_link,
)
from core.versao import VERSAO

COR_ERRO = "#ff6b6b"
COR_ATENCAO = "#ffd166"
COR_SUCESSO = "#7bd88f"
COR_NEUTRA = "#9aa0a6"

CHAVE_EXPLICACAO = "explicacao_envio_de_erros_mostrada"


class JanelaPrincipal(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("RE Play - Baixador de Músicas e Vídeos")
        self.geometry("820x580")
        self.minsize(720, 500)
        ctk.set_appearance_mode("dark")

        self._fila: queue.Queue[tuple[str, object]] = queue.Queue()
        self._baixando = False
        self._cancelar = threading.Event()
        # Sobre qual pasta o rodapé age. Acompanha o último download, para "Abrir pasta"
        # e "Alterar pasta" fazerem o que ele espera sem precisar de botões duplicados
        # num rodapé que já tem quatro.
        self._midia_atual = MUSICA
        # Onde o último download REALMENTE gravou (playlist cria subpasta). Ver
        # `_pasta_atual` para a diferença entre esta e a pasta configurada.
        self._ultima_pasta: Path | None = None
        # Guardada para conseguir esperá-la ao fechar a janela no meio de um download.
        self._thread_trabalho: threading.Thread | None = None
        self._inicio: float = 0.0

        self._montar_widgets()
        # Fechar no meio de uma playlist matava o download e deixava pedaços de arquivo
        # na pasta, porque a limpeza de parciais nunca chegava a rodar.
        self.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self._avisar_se_atualizou()

        # Relatório de erros. Fica aqui, e não em main.py, de propósito: main.py é o
        # único arquivo congelado no .exe, e o que passa por ele só muda com instalador
        # novo. Daqui, todo este sistema chega ao usuário por atualização automática.
        ocorrencias.instalar_capturadores()
        ocorrencias.iniciar_envio_em_segundo_plano()
        self._explicar_envio_uma_vez()

        self.after(100, self._consumir_fila)

    # ------------------------------------------------------------------ layout

    def _montar_widgets(self) -> None:
        ctk.CTkLabel(
            self,
            text="Cole o link da música ou do vídeo",
            font=("Segoe UI", 18, "bold"),
        ).pack(pady=(22, 2), padx=24, anchor="w")

        ctk.CTkLabel(
            self,
            text="Funciona com YouTube e Spotify. Também aceita o nome da música. "
                 "Escolha no botão: só a música (MP3) ou o vídeo inteiro (MP4).",
            font=("Segoe UI", 12),
            text_color=COR_NEUTRA,
        ).pack(pady=(0, 12), padx=24, anchor="w")

        linha = ctk.CTkFrame(self, fg_color="transparent")
        linha.pack(fill="x", padx=24)

        self.campo_link = ctk.CTkEntry(
            linha, placeholder_text="https://...", font=("Segoe UI", 13)
        )
        self.campo_link.pack(side="left", fill="x", expand=True, ipady=8)
        # Enter continua baixando música: é o uso do dia a dia dele, vídeo é a exceção.
        self.campo_link.bind("<Return>", lambda _e: self._iniciar(MUSICA))
        self.campo_link.focus()

        self.botao = ctk.CTkButton(
            linha, text="♪ Música", width=120, height=40, font=("Segoe UI", 13, "bold"),
            command=lambda: self._iniciar(MUSICA),
        )
        self.botao.pack(side="left", padx=(10, 0))

        # Cor diferente para não clicar num pensando no outro: um erro aqui custa
        # 200 MB e alguns minutos, não um arquivo de 8 MB.
        self.botao_video = ctk.CTkButton(
            linha, text="▶ Vídeo", width=110, height=40, font=("Segoe UI", 13, "bold"),
            fg_color="#3a6ea5", hover_color="#4880bd",
            command=lambda: self._iniciar(VIDEO),
        )
        self.botao_video.pack(side="left", padx=(8, 0))

        # Só aparece durante o download: sem isso, fechar a janela no meio de uma
        # playlist era a única saída, e deixava arquivos pela metade.
        self.botao_cancelar = ctk.CTkButton(
            linha, text="Cancelar", width=100, height=40, font=("Segoe UI", 13),
            fg_color="#8b2f2f", hover_color="#a53c3c", command=self._cancelar_download,
        )

        # Status textual + barra: o usuário precisa saber que algo está acontecendo.
        self.rotulo_status = ctk.CTkLabel(
            self, text="Pronto para baixar.", font=("Segoe UI", 12), text_color=COR_NEUTRA
        )
        self.rotulo_status.pack(pady=(16, 4), padx=24, anchor="w")

        self.barra = ctk.CTkProgressBar(self, height=12)
        self.barra.set(0)
        self.barra.pack(fill="x", padx=24)

        self.log = ctk.CTkTextbox(self, state="disabled", font=("Consolas", 11))
        self.log.pack(fill="both", expand=True, padx=24, pady=(14, 8))
        self.log.tag_config("erro", foreground=COR_ERRO)
        self.log.tag_config("atencao", foreground=COR_ATENCAO)
        self.log.tag_config("sucesso", foreground=COR_SUCESSO)

        # Rodapé: onde os arquivos vão parar + atalho para abrir a pasta.
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.pack(fill="x", padx=24, pady=(0, 18))

        ctk.CTkButton(
            rodape, text="📂 Abrir pasta", height=34, width=120,
            command=lambda: abrir_pasta(self._pasta_atual()),
        ).pack(side="left")

        ctk.CTkButton(
            rodape, text="Alterar pasta", height=34, width=110,
            fg_color="transparent", border_width=1,
            command=self._escolher_pasta,
        ).pack(side="left", padx=(8, 0))

        # O relatório completo, para quem quiser ver o que aconteceu.
        ctk.CTkButton(
            rodape, text="🛟 Erros", height=34, width=80,
            fg_color="transparent", border_width=1,
            command=self._abrir_log,
        ).pack(side="left", padx=(8, 0))

        # Saída manual para o caso que nenhuma checagem automática pega: o app não
        # acusou falha, mas o resultado saiu errado (versão ao vivo, playlist pela
        # metade). Só o usuário percebe isso, e sem este botão ele não teria como contar.
        ctk.CTkButton(
            rodape, text="📨 Relatar problema", height=34, width=140,
            fg_color="transparent", border_width=1,
            command=self._relatar_problema,
        ).pack(side="left", padx=(8, 0))

        rodape_texto = ctk.CTkFrame(self, fg_color="transparent")
        rodape_texto.pack(fill="x", padx=24, pady=(0, 14))

        self.rotulo_pasta = ctk.CTkLabel(
            rodape_texto,
            text=self._texto_pasta(),
            font=("Segoe UI", 10),
            text_color=COR_NEUTRA,
            anchor="w",
        )
        self.rotulo_pasta.pack(side="left", fill="x", expand=True)

        # Versão à vista: se o usuário relatar um problema, quem cuida do app pergunta o
        # número daqui e já sabe qual código está rodando. Antes isso só existia no
        # registro.txt, que ele nunca vai abrir por conta própria.
        ctk.CTkLabel(
            rodape_texto,
            text=f"versão {VERSAO}",
            font=("Segoe UI", 10),
            text_color=COR_NEUTRA,
            anchor="e",
        ).pack(side="right", padx=(12, 0))

    def _pasta_base(self) -> Path:
        """A pasta CONFIGURADA da mídia atual. É sobre ela que "Alterar pasta" age.

        Nunca pode virar a subpasta de uma playlist: ele acabaria configurando "Top Brasil"
        como destino de tudo sem perceber.
        """
        return obter_pasta_videos() if self._midia_atual == VIDEO else obter_pasta_downloads()

    def _pasta_atual(self) -> Path:
        """Onde os arquivos do último download realmente estão.

        Playlist e álbum criam uma subpasta com o nome da lista, então a pasta configurada
        não responde "onde estão minhas músicas". Antes disto, "📂 Abrir pasta" abria a
        pasta de cima e ele não via as 40 faixas que tinha acabado de baixar.
        """
        return self._ultima_pasta or self._pasta_base()

    def _texto_pasta(self) -> str:
        # Diz qual é a mídia, senão o rodapé mudaria de pasta sozinho sem explicação.
        tipo = "vídeos" if self._midia_atual == VIDEO else "músicas"
        # O verbo acompanha o que o botão ao lado faz: enquanto não há download nesta
        # sessão, ele aponta para onde VAI salvar; depois, para onde os arquivos ESTÃO.
        verbo = "Últim" + ("os vídeos" if self._midia_atual == VIDEO else "as músicas") + " em"
        if self._ultima_pasta is None:
            verbo = f"Salvando {tipo} em"
        return f"{verbo}: {self._pasta_atual()}"

    def _definir_midia_atual(self, midia: str) -> None:
        self._midia_atual = midia
        self.rotulo_pasta.configure(text=self._texto_pasta())

    def _avisar_se_atualizou(self) -> None:
        """Conta que o app mudou de versão, sem interromper nada.

        Uma linha no log em vez de uma janela de aviso: ele lê se quiser e o app segue
        utilizável no mesmo clique. Uma caixa com OK só treinaria o reflexo de fechar
        sem ler.
        """
        nova = versao_mudou_desde_a_ultima_vez()
        if nova:
            self._escrever(f"  O app foi atualizado para a versão {nova}.", "sucesso")

    def _explicar_envio_uma_vez(self) -> None:
        """Conta uma vez só que os erros são enviados automaticamente.

        Uma linha no log, não uma caixa com OK — mesma razão do aviso de atualização:
        caixa com OK treina o reflexo de fechar sem ler. Mas contar é obrigatório: o
        app manda coisas da máquina dele, e ele tem que saber disso e como desligar.
        """
        if not ocorrencias.vai_avisar() or obter_config(CHAVE_EXPLICACAO):
            return
        definir_config(CHAVE_EXPLICACAO, True)
        self._escrever(
            "  Quando algo dá errado, o app manda um relatório sozinho para quem cuida "
            "dele poder corrigir. Vai só o erro e o que você colou — nada de arquivos ou "
            "dados pessoais."
        )

    def _relatar_problema(self) -> None:
        """Manda o que estiver na fila e, se não houver nada, abre um relato do zero."""
        if not ocorrencias.vai_avisar():
            messagebox.showinfo(
                "Envio desligado",
                "O envio automático de erros está desligado neste app. "
                "Use o botão 🛟 Erros e mande o arquivo pelo relatório manual.",
            )
            return

        codigo = None
        if not ocorrencias.ha_pendentes():
            codigo = ocorrencias.relatar_manualmente()

        # Rede na thread da janela travaria a interface; o retorno vem pela fila.
        def trabalhar() -> None:
            enviados = ocorrencias.enviar_agora()
            self._fila.put(("avisado", (enviados, codigo)))

        threading.Thread(target=trabalhar, daemon=True).start()
        self.rotulo_status.configure(text="Enviando relatório...")

    def _escolher_pasta(self) -> None:
        e_video = self._midia_atual == VIDEO
        tipo = "os vídeos" if e_video else "as músicas"
        escolhida = filedialog.askdirectory(
            title=f"Escolha onde salvar {tipo}",
            # Base, não `_pasta_atual()`: o seletor tem de abrir perto da pasta que ele
            # está trocando, não dentro da subpasta da última playlist.
            initialdir=str(self._pasta_base().parent),
        )
        if not escolhida:  # usuário fechou o seletor
            return

        destino = Path(escolhida)
        try:
            destino.mkdir(parents=True, exist_ok=True)
            # Confirma que dá para escrever antes de salvar a escolha: pendrive travado
            # ou pasta protegida só apareceria como erro no meio de um download.
            teste = destino / ".teste_escrita"
            teste.touch()
            teste.unlink()
        except OSError:
            messagebox.showerror(
                "Pasta sem permissão",
                "Não consigo gravar nessa pasta. Escolha outra, por exemplo dentro de "
                "Documentos ou Música.",
            )
            return

        if e_video:
            definir_pasta_videos(destino)
        else:
            definir_pasta_downloads(destino)
        # A pasta do último download deixou de valer: o rodapé passaria a mostrar um
        # caminho antigo logo depois de ele escolher um novo.
        self._ultima_pasta = None
        self.rotulo_pasta.configure(text=self._texto_pasta())
        self._escrever(f"  Pasta de {'vídeos' if e_video else 'músicas'} alterada para: {destino}")
        registro.info(f"pasta de {'vídeos' if e_video else 'músicas'} alterada para: {destino}")

    def _abrir_log(self) -> None:
        caminho = registro.caminho_log()
        if not caminho.exists():
            caminho.write_text(
                "Ainda não há nada registrado. Este arquivo guarda o que aconteceu "
                "nos downloads e ajuda a descobrir a causa de qualquer problema.\n",
                encoding="utf-8",
            )
        subprocess.Popen(["notepad.exe", str(caminho)])

    # ------------------------------------------------------------------- ações

    def _escrever(self, texto: str, tag: str | None = None) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n", tag or "")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _iniciar(self, midia: str = MUSICA) -> None:
        if self._baixando:
            # Sair calado fazia ele clicar de novo, mais forte, achando que travou.
            self.rotulo_status.configure(
                text="Já estou baixando. Espere terminar ou clique em Cancelar."
            )
            return
        texto = self.campo_link.get().strip()
        if not texto:
            self.rotulo_status.configure(text="Cole um link ou o nome de uma música primeiro.")
            return

        e_video = midia == VIDEO
        self._baixando = True
        self._cancelar.clear()
        self._inicio = time.monotonic()
        # Enquanto baixa, o rodapé volta a apontar para a pasta configurada: a do download
        # anterior deixou de ser a resposta e a nova ainda não se sabe.
        self._ultima_pasta = None
        self._definir_midia_atual(midia)
        # Os dois travam: o que foi clicado explica o que está acontecendo, o outro só
        # não pode aceitar clique no meio de um download.
        self.botao.configure(
            state="disabled", text="Aguarde..." if e_video else "Baixando..."
        )
        self.botao_video.configure(
            state="disabled", text="Baixando..." if e_video else "Aguarde..."
        )
        self.botao_cancelar.pack(side="left", padx=(8, 0))
        self.barra.set(0)
        self.rotulo_status.configure(text="Consultando... isso pode levar alguns segundos.")
        self._escrever(f"\n▶ {texto}   [{'vídeo' if e_video else 'música'}]")

        # Se der erro, o relatório precisa dizer o que ele estava tentando baixar —
        # "falhou ao baixar" sem saber se era playlist do Spotify ou vídeo solto
        # rende pouco na hora de corrigir.
        ocorrencias.definir_pedido_atual(f"[{midia}] {texto}")

        self._thread_trabalho = threading.Thread(
            target=self._trabalhar, args=(texto, midia), daemon=True
        )
        self._thread_trabalho.start()

    def _cancelar_download(self) -> None:
        self._cancelar.set()
        self.botao_cancelar.configure(state="disabled", text="Parando...")
        self.rotulo_status.configure(text="Parando após a etapa atual...")

    def _trabalhar(self, texto: str, midia: str = MUSICA) -> None:
        """Roda fora da thread da UI: só publica eventos na fila."""
        try:
            resultado = processar_link(
                texto,
                progresso_callback=lambda m: self._fila.put(("status", m)),
                percentual_callback=lambda p: self._fila.put(("percentual", p)),
                cancelar=self._cancelar,
                midia=midia,
            )
            self._fila.put(("fim", resultado))
        except CancelamentoSolicitado:
            self._fila.put(("cancelado", None))
        except EspacoInsuficiente as exc:
            # Condição da máquina, não defeito do app: não passa por registro.erro para
            # não virar chamado automático sobre algo que só ele pode resolver.
            registro.aviso(f"espaço insuficiente: {exc}")
            self._fila.put(("sem_espaco", exc))
        except Exception as exc:  # noqa: BLE001 - vira mensagem na tela, nunca crash
            registro.erro("erro inesperado ao processar o pedido", exc)
            self._fila.put(("erro_geral", exc))

    def _consumir_fila(self) -> None:
        try:
            while True:
                tipo, dado = self._fila.get_nowait()

                if tipo == "status":
                    self.rotulo_status.configure(text=str(dado))
                    self._escrever(f"  {dado}")

                elif tipo == "percentual":
                    self.barra.set(float(dado))

                elif tipo == "fim":
                    self._finalizar(dado)

                elif tipo == "cancelado":
                    self._escrever("  Cancelado. Downloads incompletos foram apagados.", "atencao")
                    self.rotulo_status.configure(text="Cancelado. O que já baixou está na pasta.")
                    self.barra.set(0)
                    self._destravar()

                elif tipo == "sem_espaco":
                    self._escrever(f"  {dado}", "atencao")
                    self.rotulo_status.configure(text="Sem espaço no disco. Nada foi baixado.")
                    self.barra.set(0)
                    self._destravar()

                elif tipo == "erro_geral":
                    # Traduzido só aqui, na tela. O texto técnico inteiro já foi para o
                    # registro e para o relatório automático em `_trabalhar`.
                    self._escrever(f"  ERRO: {mensagens.traduzir(dado)}", "erro")
                    self._contar_que_avisou(dado)
                    self.rotulo_status.configure(
                        text="Não deu certo. Veja o relatório de erros para detalhes."
                    )
                    self._destravar()

                elif tipo == "avisado":
                    enviados, codigo = dado
                    if enviados:
                        marca = f" (relatório #{codigo})" if codigo else ""
                        self._escrever(f"  Problema relatado{marca}.", "sucesso")
                        self.rotulo_status.configure(text="Pronto, relatório enviado.")
                    else:
                        # Sem internet o relatório não se perde: fica na fila e sai
                        # sozinho na próxima abertura.
                        self._escrever(
                            "  Não consegui avisar agora (sem internet?). "
                            "Vou tentar de novo sozinho.", "atencao"
                        )
                        self.rotulo_status.configure(text="Aviso guardado para tentar de novo.")
        except queue.Empty:
            pass
        self.after(100, self._consumir_fila)

    def _contar_que_avisou(self, excecao) -> None:
        """Diz que o erro já foi enviado, com o código do relatório.

        O código é o que amarra as duas pontas: se o usuário mandar mensagem dizendo
        "deu erro", quem mantém o app pede o código e acha o chamado exato, sem
        adivinhação.
        """
        if not ocorrencias.vai_avisar() or not isinstance(excecao, BaseException):
            return
        self._escrever(
            f"  Problema já relatado (relatório #{ocorrencias.codigo_do_erro(excecao)})."
        )

    def _finalizar(self, resultado) -> None:
        total = len(resultado.faixas)
        falhas = resultado.falhas
        incertas = resultado.incertas
        pulados = resultado.pulados
        baixados = resultado.baixados

        # A pasta de verdade, que no caso de playlist é uma subpasta. `getattr` porque uma
        # atualização pode trocar gui/ e core/ em pares diferentes: sem o campo, o rodapé
        # volta ao comportamento antigo em vez de estourar.
        self._ultima_pasta = getattr(resultado, "pasta", None) or self._pasta_base()
        self.rotulo_pasta.configure(text=self._texto_pasta())

        e_video = self._midia_atual == VIDEO
        self.barra.set(1)
        partes = [f"{len(baixados)} {'vídeo(s)' if e_video else 'baixada(s)'}"]
        if pulados:
            partes.append(f"{len(pulados)} já tinha")
        if falhas:
            partes.append(f"{len(falhas)} falhou")
        self._escrever(f"  Concluído: {', '.join(partes)} (de {total}).", "sucesso")

        for f in falhas:
            self._escrever(f"  ✗ {f.nome} — {mensagens.traduzir(f.erro)}", "erro")
        for i in incertas:
            aviso = "pode ser só o áudio, sem imagem" if e_video else "confira esta"
            self._escrever(f"  ⚠ {aviso}: {i.nome}", "atencao")

        if falhas and ocorrencias.vai_avisar():
            # Sem código aqui: uma playlist com várias falhas vira um relatório só, e
            # anunciar um código por faixa daria a impressão errada de vários chamados.
            self._escrever("  Essas falhas já foram relatadas.")

        if falhas:
            # Repetir o mesmo pedido já baixa só o que falta — `_ja_existe` pula o que
            # está na pasta. Funcionava desde sempre, mas ninguém tinha contado a ele.
            self._escrever(
                "  Clique de novo no mesmo botão para tentar só as que faltaram.", "atencao"
            )

        resumo = f"Pronto! {', '.join(partes)}."
        if incertas:
            resumo += f" {len(incertas)} para conferir."
        self.rotulo_status.configure(text=resumo)
        # Deu tudo certo, campo limpo para o próximo link. Sobrou falha, o link fica lá
        # para ele repetir com um clique.
        self._destravar(limpar=not falhas)
        self._chamar_atencao()

    def _destravar(self, limpar: bool = False) -> None:
        """Devolve os botões. `limpar` só quando o pedido terminou sem pendência.

        Antes o campo era limpo sempre, inclusive no erro — e aí, para tentar de novo, ele
        tinha que voltar ao navegador e copiar o link outra vez, justamente no momento em
        que mais queria repetir.
        """
        self.botao.configure(state="normal", text="♪ Música")
        self.botao_video.configure(state="normal", text="▶ Vídeo")
        self.botao_cancelar.pack_forget()
        self.botao_cancelar.configure(state="normal", text="Cancelar")
        if limpar:
            self.campo_link.delete(0, "end")
        else:
            # Selecionado: um Ctrl+V substitui de uma vez, sem ele precisar apagar antes.
            self.campo_link.select_range(0, "end")
            self.campo_link.focus()
        self._cancelar.clear()
        self._baixando = False

    # -------------------------------------------------------------- fim do trabalho

    def _chamar_atencao(self) -> None:
        """Avisa que terminou quando ele não está olhando.

        Playlist grande leva meia hora; ele sai de perto e ficava voltando na janela para
        conferir. Só dispara em trabalho longo e com a janela fora de foco — apitar ao fim
        de uma música solta de 10 segundos, com ele olhando, seria só barulho.
        """
        if time.monotonic() - self._inicio < 30:
            return
        if self.focus_displayof() is not None:  # ele está com a janela na frente
            return

        try:
            self.bell()
        except Exception:  # noqa: BLE001 - sem som configurado não é motivo de erro
            pass

        # Piscar o botão na barra de tarefas é o aviso que o Windows já tem para isto, e
        # sai por `ctypes` — sem biblioteca nova, o que importa porque o pacote de
        # atualização automática só troca arquivos .py e não instala dependência nenhuma.
        try:
            import ctypes
            from ctypes import wintypes

            class _FLASHWINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", wintypes.UINT),
                    ("hwnd", wintypes.HWND),
                    ("dwFlags", wintypes.DWORD),
                    ("uCount", wintypes.UINT),
                    ("dwTimeout", wintypes.DWORD),
                ]

            # FLASHW_ALL (3) | FLASHW_TIMERNOFG (12): pisca até ele olhar a janela.
            info = _FLASHWINFO(
                ctypes.sizeof(_FLASHWINFO), wintypes.HWND(self.winfo_id()), 3 | 12, 5, 0
            )
            ctypes.windll.user32.FlashWindowEx(ctypes.byref(info))
        except Exception:  # noqa: BLE001 - enfeite; nunca pode derrubar o fim de um download
            pass

    def _ao_fechar(self) -> None:
        """Confirma antes de abandonar um download em andamento.

        Fechar no meio matava o processo com o arquivo pela metade, e a limpeza de
        parciais (`_limpar_parciais`, em core/pipeline.py) nunca chegava a rodar — sobrava
        `.part`, `.webp` e `.m4a` na pasta, que ele veria como música quebrada.
        """
        if not self._baixando:
            self.destroy()
            return

        if not messagebox.askyesno(
            "Download em andamento",
            "Ainda estou baixando. Fechar mesmo assim?\n\n"
            "O que já baixou continua na pasta; o arquivo atual é descartado.",
            icon="warning",
        ):
            return

        # Cancelar antes de sair é o que dá ao pipeline a chance de apagar os parciais. A
        # checagem mora dentro do hook do yt-dlp, então a saída vem em menos de um segundo;
        # os 3s são teto para nunca deixar a janela presa se algo travar.
        self._cancelar.set()
        self.rotulo_status.configure(text="Parando e limpando...")
        self.update_idletasks()
        if self._thread_trabalho is not None:
            self._thread_trabalho.join(timeout=3)
        registro.info("app fechado durante um download, a pedido do usuário")
        self.destroy()


def iniciar() -> None:
    JanelaPrincipal().mainloop()
