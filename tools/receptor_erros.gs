/**
 * A "caixa de correio" dos erros do baixador de músicas.
 *
 * POR QUE ISTO EXISTE
 * Abrir uma Issue no GitHub exige uma chave. Colocar essa chave dentro do .exe que está
 * na casa do Rogério seria dar cópia da chave da loja para o cliente: o executável é
 * extraível e o repositório do app é público. Pior que o vazamento seria o vencimento —
 * quando a chave expirasse, o envio morreria em silêncio, e quem avisaria disso é
 * justamente o sistema de erros.
 *
 * Então o app não fala com o GitHub. Ele deposita a carta aqui, num endereço que só
 * recebe. A chave mora deste lado, na conta Google do Vitor, e nunca sai daqui.
 *
 * COMO INSTALAR (uma vez só)
 *   1. script.google.com  >  Novo projeto  >  colar este arquivo inteiro
 *   2. Engrenagem (Configurações do projeto)  >  Propriedades do script  >  adicionar:
 *        GITHUB_TOKEN = o token fine-grained com permissão de Issues (leitura e escrita)
 *                       APENAS no repositório de erros
 *        GITHUB_REPO  = BigVirto/roger-eventos-erros
 *   3. Implantar  >  Nova implantação  >  tipo "App da Web"
 *        Executar como: eu
 *        Quem pode acessar: qualquer pessoa
 *   4. Copiar a URL gerada para URL_RECEPTOR em app/core/ocorrencias.py
 *
 * TROCAR A URL é o conserto caso este endereço comece a receber lixo: basta reimplantar
 * (gera URL nova), atualizar ocorrencias.py e publicar — chega sozinho na máquina dele.
 */

// Vem em toda carta; o que não trouxer é descartado. NÃO é segredo (está no repositório
// público do app) — serve contra tráfego acidental, não contra alguém determinado.
var PALAVRA_COMBINADA = 'roger-eventos-baixador';

var TAMANHO_MAXIMO = 200 * 1024;
var LIMITE_DIARIO = 60; // teto de segurança: um defeito em laço não vira enxurrada
var API = 'https://api.github.com';

function doPost(e) {
  try {
    if (!e || !e.postData || e.postData.contents.length > TAMANHO_MAXIMO) {
      return responder({ ok: false, motivo: 'corpo ausente ou grande demais' });
    }

    var ficha = JSON.parse(e.postData.contents);
    if (ficha.palavra !== PALAVRA_COMBINADA) {
      return responder({ ok: false, motivo: 'palavra combinada não confere' });
    }
    if (estourouOTetoDoDia()) {
      return responder({ ok: false, motivo: 'teto diário atingido' });
    }

    var resultado = ficha.teste ? registrarTeste(ficha) : registrarErro(ficha);
    somarAoTeto();
    return responder({ ok: true, issue: resultado });
  } catch (erro) {
    // Devolver ok:false faz o app manter o relatório na fila e tentar de novo depois —
    // melhor do que dar tudo certo e perder o erro para sempre.
    return responder({ ok: false, motivo: String(erro) });
  }
}

/** Um erro de verdade: agrupa no chamado aberto, se já houver um para o mesmo defeito. */
function registrarErro(ficha) {
  var rotuloDigital = 'fp:' + (ficha.impressao_digital || 'sem-digital');
  var existente = acharIssueAberta(rotuloDigital);

  if (existente) {
    // É o mesmo defeito de novo: vira comentário com a contagem, não chamado novo.
    // Sem isto, uma playlist de 50 faixas com o YouTube bloqueando abriria 50 chamados
    // e a lista viraria ruído que ninguém lê.
    comentar(existente, corpoDaRepeticao(ficha));
    return existente;
  }

  return criarIssue(
    titulo(ficha),
    corpoCompleto(ficha),
    ['erro-automatico', rotuloDigital, 'v' + (ficha.versao_app || '?')]
  );
}

/** O envio de teste do --autoteste: abre e fecha na hora, para não poluir a lista. */
function registrarTeste(ficha) {
  var numero = criarIssue(
    '[teste] envio de erros funcionando — ' + (ficha.versao_app || '?'),
    corpoCompleto(ficha),
    ['teste']
  );
  chamarGitHub('PATCH', '/repos/' + repo() + '/issues/' + numero, { state: 'closed' });
  return numero;
}

// ------------------------------------------------------------------ montagem do texto

function titulo(ficha) {
  var texto =
    '[' + (ficha.versao_app || '?') + '] ' +
    (ficha.tipo || 'Erro') + ' — ' + (ficha.mensagem || '').split('\n')[0];
  return texto.length > 120 ? texto.substring(0, 117) + '...' : texto;
}

function corpoCompleto(ficha) {
  return [
    '**O que ele estava tentando:** ' + (ficha.pedido || '(não informado)'),
    '',
    tabela(ficha),
    '',
    '### Detalhe técnico',
    bloco(ficha.detalhe),
    '',
    '### Últimas linhas do registro',
    bloco(ficha.registro),
    '',
    '<sub>Relatório automático do app. Caminhos com o nome do usuário foram mascarados' +
      ' na origem.</sub>'
  ].join('\n');
}

function corpoDaRepeticao(ficha) {
  return [
    'Aconteceu de novo: **' + (ficha.ocorrencias || 1) + 'x** em ' + (ficha.quando || '?') + '.',
    '',
    tabela(ficha),
    '',
    '<details><summary>Detalhe técnico desta vez</summary>',
    '',
    bloco(ficha.detalhe),
    '',
    '</details>'
  ].join('\n');
}

function tabela(ficha) {
  return [
    '| | |',
    '|---|---|',
    '| Vezes | ' + (ficha.ocorrencias || 1) + ' |',
    '| App | ' + (ficha.versao_app || '?') + ' (' + (ficha.origem_codigo || '?') + ', ' +
      '.exe ' + (ficha.versao_exe || '?') + ') |',
    '| yt-dlp | ' + (ficha.versao_ytdlp || '?') + ' (' + (ficha.origem_ytdlp || '?') + ') |',
    '| Sistema | ' + (ficha.sistema || '?') + ' |',
    '| Máquina | ' + (ficha.maquina || '?') + ' |',
    '| Quando | ' + (ficha.quando || '?') + ' |'
  ].join('\n');
}

/** Cerca de código. Neutraliza crases do conteúdo para não quebrar a formatação. */
function bloco(texto) {
  if (!texto) return '_(vazio)_';
  return '```\n' + String(texto).replace(/```/g, "'''") + '\n```';
}

// ----------------------------------------------------------------------- GitHub

function repo() {
  var valor = PropertiesService.getScriptProperties().getProperty('GITHUB_REPO');
  if (!valor) throw new Error('falta a propriedade GITHUB_REPO');
  return valor;
}

/**
 * Procura chamado ABERTO com este rótulo.
 *
 * Lista por rótulo em vez de usar a busca do GitHub de propósito: a busca leva até um
 * minuto para indexar, e nesse intervalo repetições viriam como chamados novos —
 * justamente o que o agrupamento existe para evitar.
 */
function acharIssueAberta(rotulo) {
  var achados = chamarGitHub(
    'GET',
    '/repos/' + repo() + '/issues?state=open&per_page=1&labels=' + encodeURIComponent(rotulo)
  );
  return achados && achados.length ? achados[0].number : null;
}

function criarIssue(titulo, corpo, rotulos) {
  var criada = chamarGitHub('POST', '/repos/' + repo() + '/issues', {
    title: titulo,
    body: corpo,
    labels: rotulos
  });
  return criada.number;
}

function comentar(numero, corpo) {
  chamarGitHub('POST', '/repos/' + repo() + '/issues/' + numero + '/comments', { body: corpo });
}

function chamarGitHub(metodo, caminho, corpo) {
  var token = PropertiesService.getScriptProperties().getProperty('GITHUB_TOKEN');
  if (!token) throw new Error('falta a propriedade GITHUB_TOKEN');

  var opcoes = {
    method: metodo,
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    muteHttpExceptions: true
  };
  if (corpo) {
    opcoes.contentType = 'application/json';
    opcoes.payload = JSON.stringify(corpo);
  }

  var resposta = UrlFetchApp.fetch(API + caminho, opcoes);
  var codigo = resposta.getResponseCode();
  if (codigo < 200 || codigo >= 300) {
    throw new Error('GitHub respondeu ' + codigo + ': ' + resposta.getContentText().slice(0, 300));
  }
  return JSON.parse(resposta.getContentText());
}

// ------------------------------------------------------------------------ teto do dia

function estourouOTetoDoDia() {
  return contadorDeHoje() >= LIMITE_DIARIO;
}

function somarAoTeto() {
  PropertiesService.getScriptProperties().setProperty(
    'CONTADOR',
    JSON.stringify({ dia: hoje(), quantidade: contadorDeHoje() + 1 })
  );
}

function contadorDeHoje() {
  try {
    var dados = JSON.parse(PropertiesService.getScriptProperties().getProperty('CONTADOR'));
    return dados && dados.dia === hoje() ? dados.quantidade : 0;
  } catch (erro) {
    return 0;
  }
}

function hoje() {
  return Utilities.formatDate(new Date(), 'America/Sao_Paulo', 'yyyy-MM-dd');
}

function responder(objeto) {
  return ContentService.createTextOutput(JSON.stringify(objeto)).setMimeType(
    ContentService.MimeType.JSON
  );
}

/**
 * Rodar uma vez pelo editor do Apps Script para conferir que a chave e o repositório
 * estão certos ANTES de sair publicando o app. Falha aqui é bem mais barata de achar.
 */
function testarConexao() {
  var dados = chamarGitHub('GET', '/repos/' + repo());
  Logger.log('OK: ' + dados.full_name + ' (privado: ' + dados.private + ')');
}
