// app.js — Lógica do dashboard do SENTINELA (JavaScript puro, sem bibliotecas).
//
// Dois "clientes" independentes:
//  1. ESP32 (núcleo obrigatório): polling sequencial de /status e /sensor a cada
//     1 s, com timeout de 2 s (AbortController). Duas falhas seguidas = selo
//     "DESCONECTADO"; o laço continua tentando e reconecta sozinho.
//  2. Serviço de IA (diferencial, localhost:5000): /api/resultado a cada 1 s e
//     /api/diagnostico sob demanda. Se estiver offline, só o painel de IA é
//     desabilitado; o resto do dashboard continua funcionando.
// Dados vindos da rede só entram na página via textContent (nunca innerHTML).
'use strict';

const $ = (id) => document.getElementById(id);
const IP_PADRAO = '192.168.4.1';
const CHAVE_IP = 'sentinela-esp32';
const TIMEOUT_MS = 2000;
const PERIODO_MS = 1000;
const HISTORICO_PONTOS = 60; // 60 s de histórico, 1 ponto por segundo
// Se a página veio do próprio serviço de IA (porta 5000), usa a mesma origem.
const BASE_IA = location.port === '5000' ? '' : 'http://localhost:5000';

const estado = {
  ip: lerIpSalvo(),
  conectado: false,
  falhasSeguidas: 0,
  historico: [],
  atuador: null,
  iaOnline: false,
  diagnosticando: false,
};

// Endereço do ESP32: ?esp32=... na URL (ex.: simulador) > salvo no navegador > padrão.
function lerIpSalvo() {
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
  estado.conectado = conectado;
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
  const nomes = { normal: 'NORMAL', alerta: 'ALERTA', off: 'DESLIGADO', teste: 'TESTE' };
  $('estado-atuador').textContent = nomes[a.estado] || a.estado;
  $('botao-buzzer').classList.toggle('btn-ativo', a.buzzer === 1);
  $('botao-buzzer').textContent = a.buzzer === 1 ? 'Buzzer: LIGADO' : 'Buzzer';
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
    $('msg-comando').textContent = `OK: ${caminho}`;
  } catch (erro) {
    $('msg-comando').textContent = `Falhou (${erro.message || 'sem resposta'}). O ESP32 está conectado?`;
  }
}

function configurarComandos() {
  document.querySelectorAll('[data-comando]').forEach((botao) => {
    botao.addEventListener('click', () => enviarComando(`/atuador?${botao.dataset.comando}`));
  });
  // O buzzer alterna: mantém o estado atual dos LEDs e só liga/desliga o buzzer.
  $('botao-buzzer').addEventListener('click', () => {
    const a = estado.atuador || { estado: 'off', buzzer: 0 };
    const base = a.estado === 'alerta' ? 'alerta' : 'normal';
    enviarComando(`/atuador?estado=${base}&buzzer=${a.buzzer === 1 ? 0 : 1}`);
  });
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
