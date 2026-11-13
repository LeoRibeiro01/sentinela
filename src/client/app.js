// app.js — Lógica do dashboard do SENTINELA (JavaScript puro, sem bibliotecas).
//
// Dois "clientes" independentes:
//  1. ESP32 (núcleo obrigatório): polling sequencial de /status e /sensor a cada
//     1 s, com timeout de 2 s (AbortController). Duas falhas seguidas = selo
//     "DESCONECTADO"; o laço continua tentando e reconecta sozinho.
//  2. Serviço de IA (diferencial, localhost:5000): /api/resultado a cada 1 s e
//     /api/diagnostico sob demanda. Se estiver offline, só o painel de IA é
//     desabilitado; o resto do dashboard continua funcionando.
// A cada 15 voltas (~15 s) o laço do ESP32 também busca /log (log persistente da placa).
// Dados vindos da rede só entram na página via textContent (nunca innerHTML).
'use strict';

const $ = (id) => document.getElementById(id);
const IP_PADRAO = '192.168.4.1';
const CHAVE_IP = 'sentinela-esp32';
const TIMEOUT_MS = 2000;
const PERIODO_MS = 1000;
const HISTORICO_PONTOS = 60; // 60 s de histórico, 1 ponto por segundo
// A página normalmente é servida PELO PRÓPRIO ESP32 (http://192.168.4.1/). Nesse caso
// o endereço da placa é o da própria página. Aberta do disco (file://), usa o campo de IP.
const SERVIDA_PELA_PLACA = location.protocol.startsWith('http') && location.port !== '5000';
// Serviço de IA: roda no notebook. Do celular ele fica offline e só o painel de IA é desabilitado.
const BASE_IA = location.port === '5000' ? '' : 'http://localhost:5000';

const estado = {
  ip: lerIpSalvo(),
  conectado: false,
  caiu: false, // já esteve conectado e perdeu a placa (ao voltar, recarrega a página)
  falhasSeguidas: 0,
  historico: [],
  atuador: null,
  iaOnline: false,
  diagnosticando: false,
  relogioEnviado: false, // já mandou a hora do navegador para a placa (quando ela não tem NTP)
  voltas: 0,             // contador do laço: o log é buscado a cada 5 voltas
  linhasLog: [],
  ipPrincipal: '--',
};
const NOMES_ESTADO = { normal: 'NORMAL', alerta: 'ALERTA', off: 'DESLIGADO', teste: 'TESTE' };
const FALHA_PADRAO = { normal: 'Motor normal', alerta: 'Falha detectada', off: 'Aguardando comando', teste: 'Testando atuadores' };

// Endereço do ESP32: ?esp32=... na URL (ex.: simulador) > salvo no navegador > padrão.
function lerIpSalvo() {
  if (SERVIDA_PELA_PLACA) return location.host;
  const daUrl = new URLSearchParams(location.search).get('esp32');
  if (daUrl && /^[\w.-]+(:\d{1,5})?$/.test(daUrl)) return daUrl;
  try { return localStorage.getItem(CHAVE_IP) || IP_PADRAO; } catch { return IP_PADRAO; }
}

function urlEsp32(caminho) {
  return `http://${estado.ip}${caminho}`;
}

// fetch com timeout: se a resposta não vier em `ms`, aborta e lança erro.
async function buscar(url, ms = TIMEOUT_MS) {
  const controle = new AbortController();
  const timer = setTimeout(() => controle.abort(), ms);
  try {
    const resposta = await fetch(url, { cache: 'no-store', signal: controle.signal });
    return resposta;
  } finally {
    clearTimeout(timer);
  }
}

async function buscarJson(url, ms) {
  const resposta = await buscar(url, ms);
  const dados = await resposta.json();
  if (!resposta.ok) throw new Error(dados.erro || `HTTP ${resposta.status}`);
  return dados;
}

const esperar = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------------- ESP32: conexão e polling ----------------

function mostrarConexao(conectado) {
  // A placa voltou depois de uma queda: recarrega a página PELA placa (prova que ela serve a interface).
  if (conectado && estado.caiu && SERVIDA_PELA_PLACA) { location.reload(); return; }
  if (!conectado && estado.conectado) estado.caiu = true;
  estado.conectado = conectado;
  // Sem ESP32, a interface inteira some atrás de um aviso: nada funciona sem a placa.
  document.body.classList.toggle('sem-esp32', !conectado);
  $('texto-sem-esp32').textContent = estado.caiu ? 'ESP32 DESCONECTADO' : 'Conectando ao ESP32...';
  $('selo-esp32').className = `selo ${conectado ? 'selo-on' : 'selo-off'}`;
  $('texto-esp32').textContent = conectado ? `ESP32: CONECTADO (${estado.ip})` : 'ESP32: DESCONECTADO';
  document.querySelectorAll('#cartao-atuador button, #botao-capturar').forEach((b) => { b.disabled = !conectado; });
}

async function lacoEsp32() {
  // Laço infinito e sequencial: nunca há duas requisições de polling ao mesmo tempo,
  // porque o WebServer do ESP32 atende um cliente por vez.
  for (;;) {
    const inicio = Date.now();
    try {
      const status = await buscarJson(urlEsp32('/status'));
      const sensor = await buscarJson(urlEsp32('/sensor'));
      estado.falhasSeguidas = 0;
      if (!estado.conectado) mostrarConexao(true);
      mostrarStatus(status);
      mostrarSensor(sensor);
      // Placa sem internet (sem NTP): manda a hora deste aparelho, uma vez, para o log ter data e hora.
      if (status.hora_ok === false && !estado.relogioEnviado) {
        estado.relogioEnviado = true;
        await buscar(urlEsp32(`/relogio?epoch=${Math.floor(Date.now() / 1000)}`));
      }
      // A cada 15 s: ler o log pausa a flash (e a captura de audio) por alguns ms; nao vale fazer toda hora.
      if (estado.voltas++ % 15 === 0) await atualizarLog();
    } catch {
      estado.falhasSeguidas += 1;
      if (estado.falhasSeguidas >= 2 && estado.conectado) mostrarConexao(false);
      if (estado.falhasSeguidas >= 2) adicionarHistorico(null);
    }
    await esperar(Math.max(100, PERIODO_MS - (Date.now() - inicio)));
  }
}

function formatarTempo(segundos) {
  const h = Math.floor(segundos / 3600);
  const m = Math.floor((segundos % 3600) / 60);
  const s = segundos % 60;
  return h ? `${h}h ${m}min` : `${m}min ${s}s`;
}

function mostrarStatus(s) {
  const r = s.rede || {};
  $('hora-esp').textContent = s.hora_ok ? s.hora : 'não ajustada';
  $('rede-sta').textContent = !r.sta_ssid ? 'não configurada'
    : r.sta_conectado ? `${r.sta_ssid} (${r.rssi} dBm)` : `${r.sta_ssid} — DESCONECTADA, tentando`;
  $('ip-sta').textContent = r.sta_conectado ? r.sta_ip : '--';
  $('mac-sta').textContent = r.sta_mac || '--';
  $('ip-ap').textContent = r.ap_ip ? `${r.ap_ssid} · ${r.ap_ip}` : '--';
  $('mac-ap').textContent = r.ap_mac || '--';
  $('boot').textContent = s.boot ?? '--';
  estado.ipPrincipal = r.sta_conectado ? `IP ${r.sta_ip}` : `AP ${r.ap_ip || '--'}`;
  estado.horaEsp = s.hora_ok ? s.hora.slice(11, 16) : '--:--';
  $('uptime').textContent = formatarTempo(s.uptime_s);
  $('taxa').textContent = `${s.fs_real_hz} Hz`;
  $('heap').textContent = `${Math.round(s.heap_livre / 1024)} KB`;
  $('perdidas').textContent = s.amostras_perdidas ?? '--';
  $('clientes').textContent = s.clientes_wifi ?? '--';
  $('ultima-resposta').textContent = new Date().toLocaleTimeString('pt-BR');
  mostrarAtuador(s.atuador);
  // Só atualiza os campos de modo se o usuário não estiver editando.
  if (document.activeElement !== $('campo-modo')) $('campo-modo').value = s.modo;
  if (document.activeElement !== $('campo-limiar') && s.limiar !== undefined) $('campo-limiar').value = s.limiar;
}

function mostrarSensor(s) {
  $('nivel').textContent = s.nivel;
  $('rms').textContent = s.rms;
  $('pico').textContent = s.pico;
  $('clipping').textContent = s.clipping ? 'SIM' : 'não';
  const barra = $('nivel-preenchimento');
  barra.style.width = `${s.nivel}%`;
  barra.style.background = s.nivel > 70 ? 'var(--vermelho)' : s.nivel > 40 ? 'var(--amarelo)' : 'var(--verde)';
  adicionarHistorico(s.nivel);
}

function mostrarAtuador(a) {
  if (!a) return;
  estado.atuador = a;
  $('led-verde').classList.toggle('acesa', a.verde === 1);
  $('led-vermelho').classList.toggle('acesa', a.vermelho === 1);
  $('led-buzzer').classList.toggle('acesa', a.buzzer === 1);
  $('estado-atuador').textContent = NOMES_ESTADO[a.estado] || a.estado;
  // Espelho da tela OLED: mesmas informações que a placa desenha no display.
  $('oled-estado').textContent = NOMES_ESTADO[a.estado] || a.estado;
  $('oled-estado').classList.toggle('oled-alerta', a.estado === 'alerta');
  $('oled-falha').textContent = a.falha || FALHA_PADRAO[a.estado] || '';
  $('oled-hora').textContent = estado.horaEsp || '--:--';
  $('oled-rodape').textContent = estado.ipPrincipal;
  $('oled-presente').textContent = a.tela === undefined ? '--' : a.tela ? 'conectada' : 'não detectada (o resto funciona sem ela)';
}

// ---------------- Log do sistema (memória flash do ESP32) ----------------

async function atualizarLog() {
  try {
    const resposta = await buscar(urlEsp32('/log?linhas=50'), 3000);
    if (!resposta.ok) return;
    estado.linhasLog = (await resposta.text()).split('\n').filter((l) => l.trim());
    mostrarLog();
  } catch { /* sem resposta: tenta de novo na próxima volta */ }
}

function mostrarLog() {
  const filtro = $('filtro-log').value;
  const linhas = estado.linhasLog.filter((l) => !filtro || l.includes(`[${filtro}`)).reverse(); // mais recente no topo
  $('lista-log').replaceChildren(...linhas.map((linha) => {
    const item = document.createElement('li');
    const nivel = (linha.match(/\[(ERRO|AVISO|INFO)/) || [])[1] || 'INFO';
    item.className = `log-${nivel.toLowerCase()}`;
    item.textContent = linha; // textContent: o texto do log nunca vira HTML
    return item;
  }));
  $('info-log').textContent = `${linhas.length} de ${estado.linhasLog.length} linhas · ${new Date().toLocaleTimeString('pt-BR')}`;
}

// ---------------- Gráfico de histórico (60 s) ----------------

function adicionarHistorico(valor) {
  estado.historico.push(valor);
  if (estado.historico.length > HISTORICO_PONTOS) estado.historico.shift();
  desenharHistorico();
}

// Ajusta a resolução interna do canvas ao tamanho na tela (fica nítido no projetor).
function prepararCanvas(canvas) {
  const largura = canvas.clientWidth;
  const altura = canvas.clientHeight || Number(canvas.getAttribute('height'));
  if (canvas.width !== largura) canvas.width = largura;
  canvas.height = altura;
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, largura, altura);
  return { ctx, largura, altura };
}

function desenharHistorico() {
  const { ctx, largura, altura } = prepararCanvas($('grafico-historico'));
  ctx.strokeStyle = '#2a3854';
  ctx.lineWidth = 1;
  for (const nivel of [25, 50, 75]) {
    const y = altura - (nivel / 100) * altura;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(largura, y); ctx.stroke();
  }
  ctx.strokeStyle = '#38bdf8';
  ctx.lineWidth = 3;
  ctx.beginPath();
  let desenhando = false;
  estado.historico.forEach((valor, i) => {
    const x = (i / (HISTORICO_PONTOS - 1)) * largura;
    if (valor === null) { desenhando = false; return; } // lacuna = ESP32 desconectado
    const y = altura - (valor / 100) * altura;
    if (desenhando) ctx.lineTo(x, y); else ctx.moveTo(x, y);
    desenhando = true;
  });
  ctx.stroke();
}

// ---------------- Comandos ----------------

async function enviarComando(caminho) {
  $('msg-comando').textContent = 'Enviando...';
  try {
    const r = await buscarJson(urlEsp32(caminho));
    if (r.atuador) mostrarAtuador(r.atuador);
    // A senha do Wi-Fi não aparece na mensagem.
    $('msg-comando').textContent = r.mensagem ? `OK: ${r.mensagem}` : `OK: ${caminho.replace(/senha=[^&]*/, 'senha=***')}`;
    setTimeout(atualizarLog, 300); // o comando aparece no log da placa
  } catch (erro) {
    $('msg-comando').textContent = `Falhou (${erro.message || 'sem resposta'}). O ESP32 está conectado?`;
  }
}

function configurarComandos() {
  document.querySelectorAll('[data-comando]').forEach((botao) => {
    botao.addEventListener('click', () => {
      // Normal e Alerta levam o texto opcional da falha, que aparece na tela OLED.
      const falha = $('campo-falha').value.trim().replace(/["\\]/g, '');
      const comFalha = /estado=(normal|alerta)/.test(botao.dataset.comando) && falha;
      enviarComando(`/atuador?${botao.dataset.comando}${comFalha ? `&falha=${encodeURIComponent(falha)}` : ''}`);
    });
  });
  $('form-wifi').addEventListener('submit', (e) => {
    e.preventDefault();
    const ssid = $('campo-ssid').value.trim();
    if (!ssid) { $('msg-comando').textContent = 'Informe o nome da rede.'; return; }
    enviarComando(`/wifi?ssid=${encodeURIComponent(ssid)}&senha=${encodeURIComponent($('campo-senha').value)}`);
  });
  $('botao-esquecer').addEventListener('click', () => enviarComando('/wifi?ssid='));
  $('filtro-log').addEventListener('change', mostrarLog);
  $('botao-log').addEventListener('click', atualizarLog);
  // O buzzer só dá bipes curtos (o alerta não apita): este botão testa o bipe.
  $('botao-buzzer').addEventListener('click', () => enviarComando('/atuador?bip=1'));
  $('form-modo').addEventListener('submit', (e) => {
    e.preventDefault();
    const limiar = Math.max(0, Math.min(100, Math.round(Number($('campo-limiar').value) || 0)));
    enviarComando(`/config?modo=${$('campo-modo').value}&limiar=${limiar}`);
  });
  $('form-endereco').addEventListener('submit', (e) => {
    e.preventDefault();
    const ip = $('campo-ip').value.trim().replace(/^https?:\/\//i, '').replace(/\/.*$/, '');
    if (!/^[\w.-]+(:\d{1,5})?$/.test(ip)) { $('msg-comando').textContent = 'Endereço inválido.'; return; }
    estado.ip = ip;
    $('link-log').href = urlEsp32('/log?completo=1');
    try { localStorage.setItem(CHAVE_IP, ip); } catch { /* navegador sem armazenamento: ignora */ }
    estado.falhasSeguidas = 2;
    mostrarConexao(false);
    configurarIa(`esp32=${encodeURIComponent(ip)}`); // avisa o serviço de IA do novo endereço
  });
}

// ---------------- Áudio: forma de onda e espectro ----------------

// Lê um WAV PCM 16-bit mono: procura o bloco "data" e devolve as amostras.
function lerWav(buffer) {
  const v = new DataView(buffer);
  const taxa = v.getUint32(24, true);
  let pos = 12;
  while (pos + 8 <= v.byteLength) {
    const id = String.fromCharCode(v.getUint8(pos), v.getUint8(pos + 1), v.getUint8(pos + 2), v.getUint8(pos + 3));
    const tamanho = v.getUint32(pos + 4, true);
    if (id === 'data') {
      const n = Math.min(tamanho, v.byteLength - pos - 8) >> 1;
      return { taxa, amostras: new Int16Array(buffer.slice(pos + 8, pos + 8 + n * 2)) };
    }
    pos += 8 + tamanho;
  }
  throw new Error('WAV sem bloco de dados');
}

// FFT radix-2 iterativa (in-place) para o espectro. n precisa ser potência de 2.
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) { [re[i], re[j]] = [re[j], re[i]]; [im[i], im[j]] = [im[j], im[i]]; }
  }
  for (let tam = 2; tam <= n; tam <<= 1) {
    const ang = (-2 * Math.PI) / tam;
    for (let i = 0; i < n; i += tam) {
      for (let k = 0; k < tam / 2; k++) {
        const c = Math.cos(ang * k), s = Math.sin(ang * k);
        const a = i + k, b = i + k + tam / 2;
        const tr = re[b] * c - im[b] * s, ti = re[b] * s + im[b] * c;
        re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
      }
    }
  }
}

function desenharOnda(amostras) {
  const { ctx, largura, altura } = prepararCanvas($('grafico-onda'));
  ctx.strokeStyle = '#22c55e';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  const passo = Math.max(1, Math.floor(amostras.length / largura));
  for (let x = 0; x < largura; x++) {
    // Para cada coluna desenha do mínimo ao máximo do trecho (envelope fiel).
    let min = 0, max = 0;
    for (let i = x * passo; i < Math.min(amostras.length, (x + 1) * passo); i++) {
      if (amostras[i] < min) min = amostras[i];
      if (amostras[i] > max) max = amostras[i];
    }
    ctx.moveTo(x, altura / 2 - (max / 32768) * (altura / 2));
    ctx.lineTo(x, altura / 2 - (min / 32768) * (altura / 2));
  }
  ctx.stroke();
}

function desenharEspectro(amostras, taxa) {
  const n = 2048;
  const re = new Float64Array(n), im = new Float64Array(n);
  const inicio = Math.max(0, amostras.length - n);
  for (let i = 0; i < n && inicio + i < amostras.length; i++) {
    const hann = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (n - 1)); // janela de Hann
    re[i] = (amostras[inicio + i] / 32768) * hann;
  }
  fft(re, im);
  const fMax = 4000;
  const bins = Math.floor((fMax / taxa) * n);
  const db = [];
  let maior = -Infinity, binPico = 1;
  for (let k = 1; k < bins; k++) {
    const valor = 20 * Math.log10(Math.hypot(re[k], im[k]) + 1e-9);
    db.push(valor);
    if (valor > maior) { maior = valor; binPico = k; }
  }
  const { ctx, largura, altura } = prepararCanvas($('grafico-espectro'));
  ctx.fillStyle = '#38bdf8';
  const piso = maior - 60; // mostra 60 dB de faixa dinâmica abaixo do pico
  db.forEach((valor, i) => {
    const h = Math.max(0, ((valor - piso) / 60) * altura);
    const x = (i / db.length) * largura;
    ctx.fillRect(x, altura - h, Math.max(1, largura / db.length), h);
  });
  $('freq-pico').textContent = `${Math.round((binPico * taxa) / n)} Hz`;
}

let urlAudioAnterior = null;
async function capturarAudio() {
  if (!estado.conectado) return;
  $('botao-capturar').disabled = true;
  try {
    const resposta = await buscar(urlEsp32('/audio.wav?ms=1000'), 4000);
    if (!resposta.ok) throw new Error(`HTTP ${resposta.status}`);
    const buffer = await resposta.arrayBuffer();
    const { taxa, amostras } = lerWav(buffer);
    desenharOnda(amostras);
    desenharEspectro(amostras, taxa);
    if (urlAudioAnterior) URL.revokeObjectURL(urlAudioAnterior);
    urlAudioAnterior = URL.createObjectURL(new Blob([buffer], { type: 'audio/wav' }));
    $('player').src = urlAudioAnterior;
  } catch (erro) {
    $('msg-comando').textContent = `Captura de áudio falhou: ${erro.message}`;
  } finally {
    $('botao-capturar').disabled = !estado.conectado;
  }
}

// ---------------- Serviço de IA ----------------

function mostrarIaOnline(online, texto) {
  estado.iaOnline = online;
  $('selo-ia').className = `selo ${online ? 'selo-on' : 'selo-off'}`;
  $('texto-ia').textContent = texto || (online ? 'IA: ONLINE' : 'IA: OFFLINE');
  $('aviso-ia').hidden = online;
  $('botao-diagnosticar').disabled = !online || estado.diagnosticando;
  $('opcao-demo').disabled = !online;
  $('opcao-ia-atuador').disabled = !online;
  $('botao-calibrar').disabled = !online;
}

// Mede o ruído de fundo do microfone (3 s em silêncio) e ajusta o limiar de "sinal fraco" da IA.
async function calibrarSilencio() {
  $('botao-calibrar').disabled = true;
  $('info-calibracao').textContent = 'Faça silêncio... medindo 3 s';
  try {
    const r = await buscarJson(`${BASE_IA}/api/calibrar`, 10000);
    $('info-calibracao').textContent = `Limiar ajustado para ${r.limiar_silencio} (ruído medido: ${r.rms_medidos.join(', ')})`;
  } catch (erro) {
    $('info-calibracao').textContent = `Calibração falhou: ${erro.message}`;
  } finally {
    $('botao-calibrar').disabled = !estado.iaOnline;
  }
}

async function configurarIa(parametros) {
  try {
    const r = await buscarJson(`${BASE_IA}/api/config?${parametros}`);
    $('opcao-demo').checked = r.demo;
    $('opcao-ia-atuador').checked = r.ia_atuador;
  } catch { /* IA offline: o próximo polling mostra o estado */ }
}

function mostrarResultadoVivo(r) {
  if (document.activeElement !== $('opcao-demo')) $('opcao-demo').checked = r.demo;
  if (document.activeElement !== $('opcao-ia-atuador')) $('opcao-ia-atuador').checked = r.ia_atuador;
  const v = r.ao_vivo || {};
  if (!r.modelo) mostrarIaOnline(true, 'IA: ONLINE (sem modelo treinado)');
  $('vivo-rotulo').textContent = v.texto || '--';
  $('vivo-confianca').textContent = v.confianca !== undefined && v.confianca !== null ? `(${v.confianca}%)` : '';
  $('vivo-top3').textContent = (v.top3 || []).map((c) => `${c.nome}: ${c.prob}%`).join(' · ');
  const suave = { alerta: 'FALHA (alerta)', normal: 'NORMAL' };
  $('vivo-suave').textContent = suave[r.estado_suave] || 'aguardando sons de motor confiáveis';
  $('vivo-suave').style.color = r.estado_suave === 'alerta' ? 'var(--vermelho)' : r.estado_suave === 'normal' ? 'var(--verde)' : '';
  const lista = $('vivo-historico');
  lista.replaceChildren(...(r.historico || []).slice(-12).reverse().map((h) => {
    const li = document.createElement('li');
    li.textContent = `${h.hora} ${h.texto}`;
    return li;
  }));
}

async function lacoIa() {
  for (;;) {
    try {
      const r = await buscarJson(`${BASE_IA}/api/resultado`);
      if (!estado.iaOnline) mostrarIaOnline(true);
      mostrarResultadoVivo(r);
    } catch {
      if (estado.iaOnline || $('texto-ia').textContent !== 'IA: OFFLINE') mostrarIaOnline(false);
    }
    await esperar(PERIODO_MS);
  }
}

function mostrarDiagnostico(r) {
  const textos = {
    ok: 'Diagnóstico concluído',
    inconclusivo: 'Inconclusivo — o modelo não teve confiança suficiente. Repita mais perto do motor.',
    sinal_fraco: 'Sinal fraco — aproxime o microfone do motor e repita.',
    nao_carro: 'O som captado não parece ser de um motor de carro.',
    erro: 'Erro na captura',
  };
  let texto = textos[r.status] || r.status;
  if (r.status === 'ok' && r.top_nome) texto = `${r.top_nome} (${r.confianca}%)`;
  if (r.erro) texto += ` — ${r.erro}`;
  $('diag-status').textContent = texto;

  const ranking = $('diag-ranking');
  ranking.replaceChildren(...(r.classes || []).map((c, i) => {
    const linha = document.createElement('div');
    linha.className = `linha${i === 0 && r.status === 'ok' ? ' top' : ''}`;
    const nome = document.createElement('span'); nome.textContent = c.nome || c.classe;
    const barra = document.createElement('div'); barra.className = 'barra';
    const preenchimento = document.createElement('div'); preenchimento.style.width = `${c.prob}%`;
    barra.append(preenchimento);
    const valor = document.createElement('span'); valor.className = 'valor'; valor.textContent = `${c.prob}%`;
    linha.append(nome, barra, valor);
    return linha;
  }));

  const d = r.diagnostico;
  $('diag-cartao').hidden = !d;
  if (!d) return;
  $('diag-titulo').textContent = d.titulo;
  const urgencia = $('diag-urgencia');
  const nomesUrgencia = { baixa: 'BAIXA', media: 'MÉDIA', alta: 'ALTA' };
  urgencia.textContent = `Urgência ${nomesUrgencia[d.urgencia] || d.urgencia}`;
  urgencia.className = `urgencia urgencia-${d.urgencia}`;
  const preencher = (id, itens) => $(id).replaceChildren(...(itens || []).map((t) => {
    const li = document.createElement('li'); li.textContent = t; return li;
  }));
  preencher('diag-causas', d.causas_provaveis);
  preencher('diag-verificar', d.o_que_verificar);
  $('diag-aviso').textContent = d.aviso;
}

async function diagnosticar() {
  const segundos = 5;
  estado.diagnosticando = true;
  $('botao-diagnosticar').disabled = true;
  $('progresso').hidden = false;
  $('diag-cartao').hidden = true;
  $('diag-ranking').replaceChildren();
  $('diag-status').textContent = 'Capturando áudio... mantenha o microfone perto do motor.';
  // A barra avança pelo tempo esperado (captura + ~2 s de processamento).
  const total = (segundos + 2) * 1000;
  const inicio = Date.now();
  const timer = setInterval(() => {
    const fracao = Math.min(0.97, (Date.now() - inicio) / total);
    $('progresso-barra').style.width = `${fracao * 100}%`;
    $('progresso-texto').textContent = fracao < segundos / (segundos + 2) ? 'Capturando...' : 'Analisando...';
  }, 200);
  try {
    const r = await buscarJson(`${BASE_IA}/api/diagnostico?segundos=${segundos}`, (segundos + 20) * 1000);
    mostrarDiagnostico(r);
  } catch (erro) {
    mostrarDiagnostico({ status: 'erro', erro: erro.message || 'serviço de IA não respondeu' });
  } finally {
    clearInterval(timer);
    $('progresso-barra').style.width = '100%';
    setTimeout(() => { $('progresso').hidden = true; $('progresso-barra').style.width = '0'; }, 800);
    estado.diagnosticando = false;
    $('botao-diagnosticar').disabled = !estado.iaOnline;
  }
}

// ---------------- Inicialização ----------------

function iniciar() {
  $('campo-ip').value = estado.ip;
  $('form-endereco').hidden = SERVIDA_PELA_PLACA; // o endereço é o da própria página
  $('link-log').href = urlEsp32('/log?completo=1');
  configurarComandos();
  mostrarConexao(false);
  mostrarIaOnline(false);
  $('botao-capturar').addEventListener('click', capturarAudio);
  $('botao-diagnosticar').addEventListener('click', diagnosticar);
  $('botao-calibrar').addEventListener('click', calibrarSilencio);
  $('opcao-demo').addEventListener('change', (e) => configurarIa(`demo=${e.target.checked ? 1 : 0}`));
  $('opcao-ia-atuador').addEventListener('change', (e) => configurarIa(`ia_atuador=${e.target.checked ? 1 : 0}`));
  setInterval(() => { if ($('opcao-auto-captura').checked && estado.conectado) capturarAudio(); }, 5000);
  window.addEventListener('resize', desenharHistorico);
  // Ao abrir, informa o serviço de IA de qual ESP32 usar (o mesmo do campo de endereço).
  configurarIa(`esp32=${encodeURIComponent(estado.ip)}`);
  lacoEsp32();
  lacoIa();
}

iniciar();
