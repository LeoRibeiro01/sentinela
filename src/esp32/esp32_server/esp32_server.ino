// esp32_server.ino — Firmware principal do SENTINELA (ESP32 DevKit v1).
//
// Cria o ponto de acesso Wi-Fi "SENTINELA" (192.168.4.1) e roda um servidor HTTP
// na porta 80 com as rotas do contrato (somente GET):
//   /status  /sensor  /audio.wav?ms=  /atuador?estado=  /config?modo=&limiar=
// A captura de áudio fica em captura_audio.cpp e os atuadores em atuadores.cpp;
// este arquivo só faz rede: recebe pedidos, valida parâmetros e monta respostas.
// O WebServer do Arduino atende um cliente por vez, então os handlers são curtos.
#include <WiFi.h>
#include <WebServer.h>
#include "captura_audio.h"
#include "atuadores.h"

static const char* SSID_AP = "SENTINELA";
static const char* SENHA_AP = "sentinela123";
static const IPAddress IP_AP(192, 168, 4, 1);
static const IPAddress MASCARA_AP(255, 255, 255, 0);
static const char* VERSAO = "1.0";
static constexpr uint32_t INTERVALO_LOG_MS = 10000;  // log de saúde na Serial

WebServer servidor(80);
static uint32_t ultimaJanelaAvaliada = 0;
static uint32_t ultimoLogMs = 0;

// ---------- Utilidades de resposta ----------

// Todas as respostas liberam CORS (o dashboard roda em outra origem) e proíbem cache.
static void adicionarCabecalhos() {
  servidor.sendHeader("Access-Control-Allow-Origin", "*");
  servidor.sendHeader("Cache-Control", "no-store");
}

static void responderJson(int codigo, const char* json) {
  adicionarCabecalhos();
  servidor.send(codigo, "application/json; charset=utf-8", json);
}

// Aceita só dígitos (no máximo 5) dentro de [minimo, maximo]. Evita "12abc" e estouro.
static bool lerInteiro(const String& texto, long minimo, long maximo, long& valor) {
  if (texto.length() == 0 || texto.length() > 5) return false;
  for (size_t i = 0; i < texto.length(); i++) {
    if (!isDigit(texto[i])) return false;
  }
  valor = texto.toInt();
  return valor >= minimo && valor <= maximo;
}

// JSON do atuador, reaproveitado por /status e /atuador.
static void escreverJsonAtuador(char* destino, size_t tamanho) {
  snprintf(destino, tamanho, "{\"estado\":\"%s\",\"verde\":%d,\"vermelho\":%d,\"buzzer\":%d}",
           nomeEstado(estadoAtual()), verdeLigado(), vermelhoLigado(), buzzerLigado());
}

// ---------- Rotas ----------

static void rotaRaiz() {
  responderJson(200, "{\"nome\":\"SENTINELA\",\"versao\":\"1.0\",\"rotas\":"
                     "[\"/status\",\"/sensor\",\"/audio.wav?ms=1000\",\"/atuador?estado=normal\",\"/config?modo=manual\"]}");
}

static void rotaStatus() {
  char atuador[96];
  escreverJsonAtuador(atuador, sizeof(atuador));
  char json[400];
  snprintf(json, sizeof(json),
           "{\"ok\":true,\"versao\":\"%s\",\"uptime_s\":%lu,\"fs_real_hz\":%lu,\"heap_livre\":%lu,"
           "\"heap_minimo\":%lu,\"modo\":\"%s\",\"limiar\":%u,\"atuador\":%s,"
           "\"amostras_perdidas\":%lu,\"intervalo_max_us\":%lu,\"clientes_wifi\":%u}",
           VERSAO, (unsigned long)(millis() / 1000), (unsigned long)taxaRealHz(),
           (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getMinFreeHeap(),
           modoAutoAtivo() ? "auto" : "manual", limiarAuto(), atuador,
           (unsigned long)amostrasPerdidas(), (unsigned long)intervaloMaximoUs(),
           WiFi.softAPgetStationNum());
  responderJson(200, json);
}

static void rotaSensor() {
  LeituraSensor l = lerSensor();
  char json[200];
  snprintf(json, sizeof(json),
           "{\"rms\":%u,\"pico\":%u,\"nivel\":%u,\"clipping\":%s,\"ts_ms\":%lu,\"adc_min\":%u,\"adc_max\":%u}",
           l.rms, l.pico, l.nivel, l.clipping ? "true" : "false", (unsigned long)l.tsMs, l.adcMin, l.adcMax);
  responderJson(200, json);
}

static void rotaAtuador() {
  if (!servidor.hasArg("estado")) {
    responderJson(400, "{\"erro\":\"informe estado=normal|alerta|off|teste\"}");
    return;
  }
  bool temBuzzer = servidor.hasArg("buzzer");
  bool buzzer = false;
  if (temBuzzer) {
    String valor = servidor.arg("buzzer");
    if (valor != "0" && valor != "1") {
      responderJson(400, "{\"erro\":\"buzzer deve ser 0 ou 1\"}");
      return;
    }
    buzzer = (valor == "1");
  }

  String estado = servidor.arg("estado");
  if (estado == "normal") definirEstado(ATUADOR_NORMAL, temBuzzer, buzzer);
  else if (estado == "alerta") definirEstado(ATUADOR_ALERTA, temBuzzer, buzzer);
  else if (estado == "off") definirEstado(ATUADOR_OFF);
  else if (estado == "teste") definirEstado(ATUADOR_TESTE);
  else {
    responderJson(400, "{\"erro\":\"estado invalido; use normal, alerta, off ou teste\"}");
    return;
  }
  char atuador[96];
  escreverJsonAtuador(atuador, sizeof(atuador));
  char json[128];
  snprintf(json, sizeof(json), "{\"ok\":true,\"atuador\":%s}", atuador);
  responderJson(200, json);
}

static void rotaConfig() {
  // Valida tudo antes de aplicar: um parâmetro inválido não altera nada.
  bool novoAuto = modoAutoAtivo();
  long novoLimiar = limiarAuto();
  if (servidor.hasArg("modo")) {
    String modo = servidor.arg("modo");
    if (modo == "auto") novoAuto = true;
    else if (modo == "manual") novoAuto = false;
    else { responderJson(400, "{\"erro\":\"modo deve ser auto ou manual\"}"); return; }
  }
  if (servidor.hasArg("limiar") && !lerInteiro(servidor.arg("limiar"), 0, 100, novoLimiar)) {
    responderJson(400, "{\"erro\":\"limiar deve ser inteiro de 0 a 100\"}");
    return;
  }
  configurarModoAuto(novoAuto, (uint8_t)novoLimiar);
  char json[80];
  snprintf(json, sizeof(json), "{\"ok\":true,\"modo\":\"%s\",\"limiar\":%u}",
           modoAutoAtivo() ? "auto" : "manual", limiarAuto());
  responderJson(200, json);
}

// Escreve um inteiro little-endian (formato exigido pelo WAV) em `destino`.
static void escreverLE(uint8_t* destino, uint32_t valor, uint8_t bytes) {
  for (uint8_t i = 0; i < bytes; i++) destino[i] = (valor >> (8 * i)) & 0xFF;
}

// Envia o trecho mais recente do buffer como WAV PCM 16-bit mono.
// O arquivo é enviado em blocos de 512 bytes: nunca há uma cópia inteira na RAM.
static void rotaAudio() {
  long duracaoMs = 1000;
  if (servidor.hasArg("ms") && !lerInteiro(servidor.arg("ms"), 200, 2000, duracaoMs)) {
    responderJson(400, "{\"erro\":\"ms deve ser inteiro de 200 a 2000\"}");
    return;
  }
  uint32_t taxa = taxaRealHz() ? taxaRealHz() : TAXA_ALVO_HZ;
  uint32_t quantidade = (uint32_t)duracaoMs * taxa / 1000;
  if (quantidade > CAPACIDADE_AUDIO || totalAmostras() < quantidade) {
    responderJson(503, "{\"erro\":\"buffer de audio ainda nao tem amostras suficientes\"}");
    return;
  }
  // Fixa o início do trecho agora; a captura continua gravando à frente dele.
  uint32_t inicio = inicioTrechoRecente(quantidade);
  uint32_t bytesAudio = quantidade * 2;

  // Cabeçalho WAV padrão de 44 bytes (RIFF / fmt / data).
  uint8_t cab[44];
  memcpy(cab, "RIFF", 4);       escreverLE(cab + 4, 36 + bytesAudio, 4);
  memcpy(cab + 8, "WAVEfmt ", 8); escreverLE(cab + 16, 16, 4);  // tamanho do bloco fmt
  escreverLE(cab + 20, 1, 2);     // formato 1 = PCM
  escreverLE(cab + 22, 1, 2);     // 1 canal (mono)
  escreverLE(cab + 24, taxa, 4);  // amostras por segundo
  escreverLE(cab + 28, taxa * 2, 4);  // bytes por segundo
  escreverLE(cab + 32, 2, 2);     // bytes por quadro
  escreverLE(cab + 34, 16, 2);    // bits por amostra
  memcpy(cab + 36, "data", 4);    escreverLE(cab + 40, bytesAudio, 4);

  adicionarCabecalhos();
  servidor.setContentLength(sizeof(cab) + bytesAudio);  // Content-Length exato
  servidor.send(200, "audio/wav", "");
  servidor.sendContent((const char*)cab, sizeof(cab));

  // O ESP32 é little-endian: os bytes do int16_t já estão na ordem do WAV.
  int16_t bloco[256];
  uint32_t enviadas = 0;
  while (enviadas < quantidade && servidor.client().connected()) {
    uint32_t n = min((uint32_t)256, quantidade - enviadas);
    copiarAmostras((inicio + enviadas) % CAPACIDADE_AUDIO, bloco, n);
    servidor.sendContent((const char*)bloco, n * 2);
    enviadas += n;
  }
}

static void rotaNaoEncontrada() {
  responderJson(404, "{\"erro\":\"rota nao encontrada\"}");
}

// ---------- Inicialização e laço principal ----------

static void iniciarPontoDeAcesso() {
  WiFi.persistent(false);  // não grava config na flash a cada boot
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(IP_AP, IP_AP, MASCARA_AP);
  // Canal 6, rede visível, até 4 clientes (notebook + reserva).
  if (!WiFi.softAP(SSID_AP, SENHA_AP, 6, false, 4)) {
    Serial.println("ERRO: falha ao iniciar o ponto de acesso");
  }
  WiFi.setSleep(false);  // sem economia de energia: menor latência e menos quedas
  Serial.printf("AP %s ativo em http://%s/\n", SSID_AP, WiFi.softAPIP().toString().c_str());
}

// Log de saúde a cada 10 s: base para o teste de 30 min (heap estável, sem reinício).
static void registrarSaude() {
  if (millis() - ultimoLogMs < INTERVALO_LOG_MS) return;
  ultimoLogMs = millis();
  LeituraSensor l = lerSensor();
  Serial.printf("[saude] uptime=%lus heap=%lu heap_min=%lu fs=%luHz perdidas=%lu int_max=%luus "
                "rms=%u adc=[%u..%u] clientes=%u estado=%s\n",
                (unsigned long)(millis() / 1000), (unsigned long)ESP.getFreeHeap(),
                (unsigned long)ESP.getMinFreeHeap(), (unsigned long)taxaRealHz(),
                (unsigned long)amostrasPerdidas(), (unsigned long)intervaloMaximoUs(),
                l.rms, l.adcMin, l.adcMax, WiFi.softAPgetStationNum(), nomeEstado(estadoAtual()));
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nSENTINELA iniciando...");
  iniciarAtuadores();
  iniciarPontoDeAcesso();

  servidor.on("/", HTTP_GET, rotaRaiz);
  servidor.on("/status", HTTP_GET, rotaStatus);
  servidor.on("/sensor", HTTP_GET, rotaSensor);
  servidor.on("/audio.wav", HTTP_GET, rotaAudio);
  servidor.on("/atuador", HTTP_GET, rotaAtuador);
  servidor.on("/config", HTTP_GET, rotaConfig);
  servidor.onNotFound(rotaNaoEncontrada);
  servidor.begin();

  if (!iniciarCaptura()) Serial.println("ERRO: falha ao criar a tarefa de captura");
  Serial.printf("Servidor HTTP pronto. Heap livre: %lu bytes\n", (unsigned long)ESP.getFreeHeap());
}

void loop() {
  servidor.handleClient();

  // O modo auto é avaliado aqui (e não na tarefa de áudio) para que só esta
  // tarefa mexa nos atuadores, evitando conflito com os comandos HTTP.
  LeituraSensor l = lerSensor();
  if (l.numeroJanela != ultimaJanelaAvaliada) {
    ultimaJanelaAvaliada = l.numeroJanela;
    processarJanelaAuto(l.nivel);
  }
  atualizarAtuadores();
  registrarSaude();
  delay(1);  // cede CPU às tarefas de menor prioridade do núcleo 1
}
