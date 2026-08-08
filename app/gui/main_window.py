"""Janela principal: um campo de link, progresso claro e acesso à pasta de destino.

A GUI não contém lógica de download/busca — só orquestração visual. Todo o trabalho
acontece em core/pipeline.py, numa thread separada para a janela nunca travar.
"""

import queue
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from core import registro
from core.atualizador_app import versao_mudou_desde_a_ultima_vez
from core.organizer import abrir_pasta, definir_pasta_downloads, obter_pasta_downloads
from core.pipeline import CancelamentoSolicitado, processar_link
from core.versao import VERSAO

COR_ERRO = "#ff6b6b"
COR_ATENCAO = "#ffd166"
COR_SUCESSO = "#7bd88f"
COR_NEUTRA = "#9aa0a6"


class JanelaPrincipal(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Roger Eventos - Baixador de Músicas")
        self.geometry("720x560")
        self.minsize(640, 480)
        ctk.set_appearance_mode("dark")

        self._fila: queue.Queue[tuple[str, object]] = queue.Queue()
        self._baixando = False
        self._cancelar = threading.Event()

        self._montar_widgets()
        self._avisar_se_atualizou()
        self.after(100, self._consumir_fila)

    # ------------------------------------------------------------------ layout

    def _montar_widgets(self) -> None:
        ctk.CTkLabel(
            self,
            text="Cole o link da música ou playlist",
            font=("Segoe UI", 18, "bold"),
        ).pack(pady=(22, 2), padx=24, anchor="w")

        ctk.CTkLabel(
            self,
            text="Funciona com YouTube e Spotify. Também aceita o nome da música.",
            font=("Segoe UI", 12),
            text_color=COR_NEUTRA,
        ).pack(pady=(0, 12), padx=24, anchor="w")

        linha = ctk.CTkFrame(self, fg_color="transparent")
        linha.pack(fill="x", padx=24)

        self.campo_link = ctk.CTkEntry(
            linha, placeholder_text="https://...", font=("Segoe UI", 13)
        )
        self.campo_link.pack(side="left", fill="x", expand=True, ipady=8)
        self.campo_link.bind("<Return>", lambda _e: self._iniciar())
        self.campo_link.focus()

        self.botao = ctk.CTkButton(
            linha, text="Baixar", width=120, height=40, font=("Segoe UI", 13, "bold"),
            command=self._iniciar,
        )
        self.botao.pack(side="left", padx=(10, 0))

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
            command=lambda: abrir_pasta(obter_pasta_downloads()),
        ).pack(side="left")

        ctk.CTkButton(
            rodape, text="Alterar pasta", height=34, width=110,
            fg_color="transparent", border_width=1,
            command=self._escolher_pasta,
        ).pack(side="left", padx=(8, 0))

        # Se der problema na máquina do Rogério, ele abre isto e manda o arquivo.
        ctk.CTkButton(
            rodape, text="🛟 Erros", height=34, width=80,
            fg_color="transparent", border_width=1,
            command=self._abrir_log,
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

        # Versão à vista: se o Rogério relatar um problema, o Vitor pergunta o número
        # daqui e já sabe qual código está rodando. Antes isso só existia no registro.txt,
        # que ele nunca vai abrir por conta própria.
        ctk.CTkLabel(
            rodape_texto,
            text=f"versão {VERSAO}",
            font=("Segoe UI", 10),
            text_color=COR_NEUTRA,
            anchor="e",
        ).pack(side="right", padx=(12, 0))

    def _texto_pasta(self) -> str:
        return f"Salvando em: {obter_pasta_downloads()}"

    def _avisar_se_atualizou(self) -> None:
        """Conta que o app mudou de versão, sem interromper nada.

        Uma linha no log em vez de uma janela de aviso: ele lê se quiser e o app segue
        utilizável no mesmo clique. Uma caixa com OK só treinaria o reflexo de fechar
        sem ler.
        """
        nova = versao_mudou_desde_a_ultima_vez()
        if nova:
            self._escrever(f"  O app foi atualizado para a versão {nova}.", "sucesso")

    def _escolher_pasta(self) -> None:
        escolhida = filedialog.askdirectory(
            title="Escolha onde salvar as músicas",
            initialdir=str(obter_pasta_downloads().parent),
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

        definir_pasta_downloads(destino)
        self.rotulo_pasta.configure(text=self._texto_pasta())
        self._escrever(f"  Pasta alterada para: {destino}")
        registro.info(f"pasta de downloads alterada para: {destino}")

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

    def _iniciar(self) -> None:
        if self._baixando:
            return
        texto = self.campo_link.get().strip()
        if not texto:
            self.rotulo_status.configure(text="Cole um link ou o nome de uma música primeiro.")
            return

        self._baixando = True
        self._cancelar.clear()
        self.botao.configure(state="disabled", text="Baixando...")
        self.botao_cancelar.pack(side="left", padx=(8, 0))
        self.barra.set(0)
        self.rotulo_status.configure(text="Consultando... isso pode levar alguns segundos.")
        self._escrever(f"\n▶ {texto}")

        threading.Thread(target=self._trabalhar, args=(texto,), daemon=True).start()

    def _cancelar_download(self) -> None:
        self._cancelar.set()
        self.botao_cancelar.configure(state="disabled", text="Parando...")
        self.rotulo_status.configure(text="Parando após a etapa atual...")

    def _trabalhar(self, texto: str) -> None:
        """Roda fora da thread da UI: só publica eventos na fila."""
        try:
            resultado = processar_link(
                texto,
                progresso_callback=lambda m: self._fila.put(("status", m)),
                percentual_callback=lambda p: self._fila.put(("percentual", p)),
                cancelar=self._cancelar,
            )
            self._fila.put(("fim", resultado))
        except CancelamentoSolicitado:
            self._fila.put(("cancelado", None))
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

                elif tipo == "erro_geral":
                    self._escrever(f"  ERRO: {dado}", "erro")
                    self.rotulo_status.configure(
                        text="Não deu certo. Veja o relatório de erros para detalhes."
                    )
                    self._destravar()
        except queue.Empty:
            pass
        self.after(100, self._consumir_fila)

    def _finalizar(self, resultado) -> None:
        total = len(resultado.faixas)
        falhas = resultado.falhas
        incertas = resultado.incertas
        pulados = resultado.pulados
        baixados = resultado.baixados

        self.barra.set(1)
        partes = [f"{len(baixados)} baixada(s)"]
        if pulados:
            partes.append(f"{len(pulados)} já tinha")
        if falhas:
            partes.append(f"{len(falhas)} falhou")
        self._escrever(f"  Concluído: {', '.join(partes)} (de {total}).", "sucesso")

        for f in falhas:
            self._escrever(f"  ✗ {f.nome} — {f.erro}", "erro")
        for i in incertas:
            self._escrever(f"  ⚠ confira esta: {i.nome}", "atencao")

        resumo = f"Pronto! {', '.join(partes)}."
        if incertas:
            resumo += f" {len(incertas)} para conferir."
        self.rotulo_status.configure(text=resumo)
        self._destravar()

    def _destravar(self) -> None:
        self.botao.configure(state="normal", text="Baixar")
        self.botao_cancelar.pack_forget()
        self.botao_cancelar.configure(state="normal", text="Cancelar")
        self.campo_link.delete(0, "end")
        self._cancelar.clear()
        self._baixando = False


def iniciar() -> None:
    JanelaPrincipal().mainloop()
