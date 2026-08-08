; Instalador do Baixador de Músicas do Roger Eventos (Inno Setup 6, gratuito).
;
; Gerar: iscc instalador\RogerEventos.iss   (após compilar o .exe com PyInstaller)
; Saída: instalador\Saida\Instalar-RogerEventos-BaixadorDeMusicas.exe
;
; PrivilegesRequired=lowest é essencial: instala em %LOCALAPPDATA%\Programs, que o
; usuário pode escrever. Instalar em "Arquivos de Programas" exigiria administrador e
; o Windows bloquearia a escrita do app. Também evita o aviso de UAC.

#define MeuApp "Baixador de Músicas - Roger Eventos"
#define MeuAppPublisher "Roger Eventos"
#define MeuExe "RogerEventos-BaixadorDeMusicas.exe"

; A versão é lida de app\core\versao.py, a mesma fonte que o app e o atualizador usam.
; Duplicar o número aqui já causou instalador dizendo 1.0.0 com o app em outra versão —
; e sem versão confiável não dá para saber o que o Rogério tem instalado.
#define ArquivoVersao "..\app\core\versao.py"
#define Handle
#define Linha
#define MeuAppVersao

#sub LerLinha
  #expr Linha = FileRead(Handle)
  #if Pos("VERSAO = ", Linha) == 1
    #expr MeuAppVersao = Copy(Linha, Pos("""", Linha) + 1)
    #expr MeuAppVersao = Copy(MeuAppVersao, 1, Pos("""", MeuAppVersao) - 1)
  #endif
#endsub

#expr Handle = FileOpen(ArquivoVersao)
#for {0; !FileEof(Handle); 1} LerLinha
#expr FileClose(Handle)

#if !defined(MeuAppVersao) || MeuAppVersao == ""
  #error Nao consegui ler VERSAO de app\core\versao.py
#endif

[Setup]
AppId={{8E3A1C74-5B2F-4D89-9A6E-2C7F1B4D8E30}
AppName={#MeuApp}
AppVersion={#MeuAppVersao}
AppPublisher={#MeuAppPublisher}
DefaultDirName={autopf}\RogerEventos
DefaultGroupName=Roger Eventos
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=Saida
OutputBaseFilename=Instalar-RogerEventos-BaixadorDeMusicas
; Faz a versão aparecer nas propriedades do arquivo — dá para conferir sem instalar.
VersionInfoVersion={#MeuAppVersao}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; O .exe já vem comprimido pelo PyInstaller; sem isto a compressão demora à toa.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MeuApp}
UninstallDisplayIcon={app}\{#MeuExe}

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: checkedonce

[Files]
Source: "..\app\dist\{#MeuExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MeuApp}"; Filename: "{app}\{#MeuExe}"
Name: "{group}\Desinstalar {#MeuApp}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MeuApp}"; Filename: "{app}\{#MeuExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MeuExe}"; Description: "Abrir o app agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove só o que o app gerou em AppData (config, log, atualizações do yt-dlp).
; As MÚSICAS ficam em "Músicas\Roger Eventos" e NÃO são apagadas de propósito —
; são o trabalho do Rogério, não arquivo de programa.
Type: filesandordirs; Name: "{localappdata}\RogerEventos"
