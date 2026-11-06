// Sentinela: ponto de acesso, API HTTP e captura de áudio do MAX9814.
// O timer marca a amostragem; uma tarefa no núcleo 1 lê o ADC sem bloquear o Wi-Fi.
#include <WiFi.h>
#include <WebServer.h>
#include <driver/adc.h>
#include <math.h>
#include <string.h>

// Ponto de acesso local: o notebook conecta diretamente ao ESP32, sem internet.
static const char* SSID_AP = "SENTINELA";
static const char* SENHA_AP = "sentinela123";
static const IPAddress IP_AP(192, 168, 4, 1);
static const IPAddress MASCARA_AP(255, 255, 255, 0);

static constexpr uint8_t PINO_MICROFONE = 34; // ADC1_CH6; entrada analógica
static constexpr uint8_t PINO_VERDE = 16;
static constexpr uint8_t PINO_VERMELHO = 17;
static constexpr uint8_t PINO_BUZZER = 18;
static constexpr uint8_t PINO_ALERTA_ONBOARD = 2;
static constexpr uint32_t TAXA_ALVO_HZ = 16000;
static constexpr uint32_t INTERVALO_TIMER_US = 62; // 16.129 Hz; taxa real é medida
static constexpr uint32_t AMOSTRAS_JANELA = TAXA_ALVO_HZ / 4; // aproximadamente 250 ms
static constexpr uint32_t CAPACIDADE_AUDIO = 32768; // 64 KiB; cobre 2 s a ~16,1 kHz
static constexpr uint32_t TAMANHO_MAXIMO_BLOCO = 512;

WebServer servidor(80);
hw_timer_t* timerAmostragem = nullptr;
TaskHandle_t tarefaAmostragem = nullptr;
portMUX_TYPE travaEstado = portMUX_INITIALIZER_UNLOCKED;

// Buffer circular de PCM mono. O ESP32 não tem PSRAM; este limite ocupa 64 KB.
int16_t bufferAudio[CAPACIDADE_AUDIO];
volatile uint32_t indiceAudio = 0;
volatile uint32_t totalAmostras = 0;
volatile uint32_t taxaRealHz = 0;
volatile uint16_t rmsAtual = 0;
volatile uint16_t picoAtual = 0;
volatile uint8_t nivelAtual = 0;
volatile bool clippingAtual = false;
volatile uint32_t instanteSensor = 0;

enum EstadoAtuador : uint8_t { ATUADOR_OFF, ATUADOR_NORMAL, ATUADOR_ALERTA, ATUADOR_TESTE };
enum ModoOperacao : uint8_t { MODO_MANUAL, MODO_AUTO };
EstadoAtuador estadoAtuador = ATUADOR_OFF;
ModoOperacao modoOperacao = MODO_MANUAL;
bool buzzerTemOverride = false;
bool buzzerOverride = false;
uint8_t limiarAuto = 45;
uint8_t janelasAcimaLimiar = 0;
uint32_t inicioTesteMs = 0;

void IRAM_ATTR marcarAmostra() {
  BaseType_t tarefaAcordada = pdFALSE;
  vTaskNotifyGiveFromISR(tarefaAmostragem, &tarefaAcordada);
  if (tarefaAcordada) portYIELD_FROM_ISR();
}

// Mantém CORS e impede que o navegador reutilize leituras antigas.
void adicionarCabecalhos() {
  servidor.sendHeader("Access-Control-Allow-Origin", "*");
  servidor.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  servidor.sendHeader("Access-Control-Allow-Headers", "Content-Type");
  servidor.sendHeader("Cache-Control", "no-store");
}

void responderJson(int codigo, const String& json) {
  adicionarCabecalhos();
  servidor.send(codigo, "application/json; charset=utf-8", json);
}

String textoEstadoAtuador() {
  switch (estadoAtuador) {
    case ATUADOR_NORMAL: return "normal";
    case ATUADOR_ALERTA: return "alerta";
    case ATUADOR_TESTE: return "teste";
    default: return "off";
  }
}

void aplicarSaidas() {
  bool verde = (estadoAtuador == ATUADOR_NORMAL);
  bool alerta = (estadoAtuador == ATUADOR_ALERTA);
  bool buzzer = buzzerTemOverride ? buzzerOverride : alerta;

  if (estadoAtuador == ATUADOR_TESTE) {
    // Três etapas curtas permitem conferir as saídas mesmo sem som ou IA.
    uint32_t etapa = ((millis() - inicioTesteMs) / 250) % 4;
    verde = etapa == 0;
    alerta = etapa == 1;
    buzzer = etapa == 2;
  }

  digitalWrite(PINO_VERDE, verde ? HIGH : LOW);
  digitalWrite(PINO_VERMELHO, alerta ? HIGH : LOW);
  digitalWrite(PINO_BUZZER, buzzer ? HIGH : LOW);
  digitalWrite(PINO_ALERTA_ONBOARD, alerta ? HIGH : LOW);
}

void definirEstado(EstadoAtuador novoEstado, bool temOverride = false, bool valorOverride = false) {
  estadoAtuador = novoEstado;
  buzzerTemOverride = temOverride;
  buzzerOverride = valorOverride;
  if (novoEstado == ATUADOR_TESTE) inicioTesteMs = millis();
  aplicarSaidas();
}

// Calcula RMS e remove o nível contínuo do MAX9814 com filtro passa-altas simples.
void tarefaCaptura(void*) {
  int32_t mediaDc = 2048;
  uint64_t somaQuadrados = 0;
  uint16_t picoJanela = 0;
  bool clipJanela = false;
  uint32_t contagemJanela = 0;
  uint32_t contagemTaxa = 0;
  uint32_t inicioTaxaUs = micros();

  for (;;) {
    ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    int leitura = adc1_get_raw(ADC1_CHANNEL_6);
    if (leitura < 0) continue;

    mediaDc += (leitura - mediaDc) >> 8;
    int32_t semDc = leitura - mediaDc;
    uint16_t pico = (uint16_t)abs(semDc);
    int32_t valorPcm = semDc * 16;
    if (valorPcm > 32767) valorPcm = 32767;
    if (valorPcm < -32768) valorPcm = -32768;
    int16_t pcm = (int16_t)valorPcm; // converte a faixa do ADC para PCM 16-bit

    bufferAudio[indiceAudio] = pcm;
    indiceAudio = (indiceAudio + 1) % CAPACIDADE_AUDIO;
    totalAmostras++;
    contagemTaxa++;

    somaQuadrados += (int64_t)semDc * semDc;
    if (pico > picoJanela) picoJanela = pico;
    if (leitura <= 5 || leitura >= 4090) clipJanela = true;
    if (++contagemJanela < AMOSTRAS_JANELA) continue;

    uint16_t rms = (uint16_t)sqrt((double)somaQuadrados / contagemJanela);
    uint8_t nivel = (uint8_t)min((uint32_t)100, ((uint32_t)rms * 100) / 600);
    uint32_t agora = micros();
    if ((uint32_t)(agora - inicioTaxaUs) >= 1000000) {
      taxaRealHz = (uint32_t)(((uint64_t)contagemTaxa * 1000000) / (agora - inicioTaxaUs));
      contagemTaxa = 0;
      inicioTaxaUs = agora;
    }

    portENTER_CRITICAL(&travaEstado);
    rmsAtual = rms;
    picoAtual = picoJanela;
    nivelAtual = nivel;
    clippingAtual = clipJanela;
    instanteSensor = millis();
    portEXIT_CRITICAL(&travaEstado);

    // O fallback automático é local ao ESP32 e não depende do servidor de IA.
    if (modoOperacao == MODO_AUTO) {
      if (nivel > limiarAuto) {
        if (janelasAcimaLimiar < 3) janelasAcimaLimiar++;
      } else {
        janelasAcimaLimiar = 0;
      }
      if (janelasAcimaLimiar >= 3 && estadoAtuador != ATUADOR_ALERTA) definirEstado(ATUADOR_ALERTA);
      if (janelasAcimaLimiar == 0 && estadoAtuador == ATUADOR_ALERTA) definirEstado(ATUADOR_NORMAL);
    }

    somaQuadrados = 0;
    picoJanela = 0;
    clipJanela = false;
    contagemJanela = 0;
  }
}

void rotaRaiz() {
  responderJson(200, "{\"nome\":\"Sentinela\",\"versao\":\"1.0\",\"ip\":\"192.168.4.1\"}");
}

void rotaStatus() {
  char json[256];
  snprintf(json, sizeof(json),
    "{\"ok\":true,\"versao\":\"1.0\",\"uptime_s\":%lu,\"fs_real_hz\":%lu,\"heap_livre\":%lu,\"modo\":\"%s\",\"atuador\":{\"estado\":\"%s\",\"verde\":%d,\"vermelho\":%d,\"buzzer\":%d}}",
    (unsigned long)(millis() / 1000), (unsigned long)taxaRealHz,
    (unsigned long)ESP.getFreeHeap(), modoOperacao == MODO_AUTO ? "auto" : "manual",
    textoEstadoAtuador().c_str(), digitalRead(PINO_VERDE), digitalRead(PINO_VERMELHO), digitalRead(PINO_BUZZER));
  responderJson(200, String(json));
}

void rotaSensor() {
  uint16_t rms, pico;
  uint8_t nivel;
  bool clipping;
  uint32_t instante;
  portENTER_CRITICAL(&travaEstado);
  rms = rmsAtual; pico = picoAtual; nivel = nivelAtual;
  clipping = clippingAtual; instante = instanteSensor;
  portEXIT_CRITICAL(&travaEstado);

  char json[150];
  snprintf(json, sizeof(json), "{\"rms\":%u,\"pico\":%u,\"nivel\":%u,\"clipping\":%s,\"ts_ms\":%lu}",
    rms, pico, nivel, clipping ? "true" : "false", (unsigned long)instante);
  responderJson(200, String(json));
}

bool parametroInteiro(const String& texto, long minimo, long maximo, long& valor) {
  if (texto.length() == 0) return false;
  for (size_t i = 0; i < texto.length(); i++) if (!isDigit(texto[i])) return false;
  valor = texto.toInt();
  return valor >= minimo && valor <= maximo;
}

void rotaAtuador() {
  if (!servidor.hasArg("estado")) {
    responderJson(400, "{\"erro\":\"Informe estado=normal, alerta, off ou teste\"}");
    return;
  }
  String estado = servidor.arg("estado");
  estado.toLowerCase();
  bool buzzer = false;
  if (servidor.hasArg("buzzer")) {
    String valor = servidor.arg("buzzer");
    if (valor != "0" && valor != "1") {
      responderJson(400, "{\"erro\":\"buzzer deve ser 0 ou 1\"}");
      return;
    }
    buzzer = valor == "1";
  }

  if (estado == "normal") definirEstado(ATUADOR_NORMAL, servidor.hasArg("buzzer"), buzzer);
  else if (estado == "alerta") definirEstado(ATUADOR_ALERTA, servidor.hasArg("buzzer"), buzzer);
  else if (estado == "off") definirEstado(ATUADOR_OFF);
  else if (estado == "teste") definirEstado(ATUADOR_TESTE);
  else {
    responderJson(400, "{\"erro\":\"Estado inválido; use normal, alerta, off ou teste\"}");
    return;
  }
  String json = "{\"ok\":true,\"estado\":\"" + textoEstadoAtuador() + "\",\"verde\":" +
    String(digitalRead(PINO_VERDE)) + ",\"vermelho\":" + String(digitalRead(PINO_VERMELHO)) +
    ",\"buzzer\":" + String(digitalRead(PINO_BUZZER)) + "}";
  responderJson(200, json);
}

void rotaConfig() {
  ModoOperacao novoModo = modoOperacao;
  uint8_t novoLimiar = limiarAuto;
  if (servidor.hasArg("modo")) {
    String modo = servidor.arg("modo");
    modo.toLowerCase();
    if (modo == "auto") novoModo = MODO_AUTO;
    else if (modo == "manual") novoModo = MODO_MANUAL;
    else { responderJson(400, "{\"erro\":\"modo deve ser auto ou manual\"}"); return; }
  }
  if (servidor.hasArg("limiar")) {
    long valor;
    if (!parametroInteiro(servidor.arg("limiar"), 0, 100, valor)) {
      responderJson(400, "{\"erro\":\"limiar deve ser inteiro entre 0 e 100\"}");
      return;
    }
    novoLimiar = (uint8_t)valor;
  }
  modoOperacao = novoModo;
  limiarAuto = novoLimiar;
  janelasAcimaLimiar = 0;
  String json = String("{\"ok\":true,\"modo\":\"") + (modoOperacao == MODO_AUTO ? "auto" : "manual") +
    "\",\"limiar\":" + String(limiarAuto) + "}";
  responderJson(200, json);
}

void gravarU16(uint8_t* destino, uint16_t valor) {
  destino[0] = valor & 0xff; destino[1] = (valor >> 8) & 0xff;
}

void gravarU32(uint8_t* destino, uint32_t valor) {
  destino[0] = valor & 0xff; destino[1] = (valor >> 8) & 0xff;
  destino[2] = (valor >> 16) & 0xff; destino[3] = (valor >> 24) & 0xff;
}

void rotaAudio() {
  long duracaoMs = 1000;
  if (servidor.hasArg("ms") && !parametroInteiro(servidor.arg("ms"), 200, 2000, duracaoMs)) {
    responderJson(400, "{\"erro\":\"ms deve ser inteiro entre 200 e 2000\"}");
    return;
  }
  uint32_t quantidade = (uint32_t)duracaoMs * (taxaRealHz ? taxaRealHz : TAXA_ALVO_HZ) / 1000;
  if (totalAmostras < quantidade) {
    responderJson(503, "{\"erro\":\"Ainda não há áudio suficiente no buffer\"}");
    return;
  }

  // Copia uma visão consistente do trecho recente antes de iniciar a resposta.
  uint32_t fim, disponiveis;
  fim = indiceAudio;
  disponiveis = totalAmostras;
  if (disponiveis > CAPACIDADE_AUDIO) disponiveis = CAPACIDADE_AUDIO;
  uint32_t inicio = (fim + CAPACIDADE_AUDIO - quantidade) % CAPACIDADE_AUDIO;
  if (disponiveis < quantidade) {
    responderJson(503, "{\"erro\":\"Ainda não há áudio suficiente no buffer\"}");
    return;
  }

  uint32_t taxa = taxaRealHz ? taxaRealHz : TAXA_ALVO_HZ;
  uint32_t bytesAudio = quantidade * sizeof(int16_t);
  uint8_t cabecalho[44] = {0};
  memcpy(cabecalho, "RIFF", 4); gravarU32(cabecalho + 4, 36 + bytesAudio);
  memcpy(cabecalho + 8, "WAVEfmt ", 8); gravarU32(cabecalho + 16, 16);
  gravarU16(cabecalho + 20, 1); gravarU16(cabecalho + 22, 1);
  gravarU32(cabecalho + 24, taxa); gravarU32(cabecalho + 28, taxa * 2);
  gravarU16(cabecalho + 32, 2); gravarU16(cabecalho + 34, 16);
  memcpy(cabecalho + 36, "data", 4); gravarU32(cabecalho + 40, bytesAudio);

  WiFiClient cliente = servidor.client();
  cliente.printf("HTTP/1.1 200 OK\r\nContent-Type: audio/wav\r\nContent-Length: %lu\r\nAccess-Control-Allow-Origin: *\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n",
    (unsigned long)(44 + bytesAudio));
  cliente.write(cabecalho, sizeof(cabecalho));
  uint8_t bloco[TAMANHO_MAXIMO_BLOCO];
  uint32_t amostrasEnviadas = 0;
  while (amostrasEnviadas < quantidade && cliente.connected()) {
    uint32_t quantidadeBloco = min((uint32_t)(TAMANHO_MAXIMO_BLOCO / 2), quantidade - amostrasEnviadas);
    for (uint32_t i = 0; i < quantidadeBloco; i++) {
      int16_t amostra = bufferAudio[(inicio + amostrasEnviadas + i) % CAPACIDADE_AUDIO];
      uint16_t semSinal = (uint16_t)amostra;
      bloco[i * 2] = semSinal & 0xff;
      bloco[i * 2 + 1] = (semSinal >> 8) & 0xff;
    }
    cliente.write(bloco, quantidadeBloco * 2);
    amostrasEnviadas += quantidadeBloco;
    delay(0); // cede tempo ao Wi-Fi durante o envio do WAV
  }
}

void rotaNaoEncontrada() {
  if (servidor.method() == HTTP_OPTIONS) {
    adicionarCabecalhos(); servidor.send(204); return;
  }
  responderJson(404, "{\"erro\":\"Rota não encontrada\"}");
}

void atualizarTeste() {
  if (estadoAtuador == ATUADOR_TESTE) {
    if (millis() - inicioTesteMs >= 1000) definirEstado(ATUADOR_NORMAL);
    else aplicarSaidas();
  }
}

void setup() {
  Serial.begin(115200);
  pinMode(PINO_VERDE, OUTPUT); pinMode(PINO_VERMELHO, OUTPUT);
  pinMode(PINO_BUZZER, OUTPUT); pinMode(PINO_ALERTA_ONBOARD, OUTPUT);
  definirEstado(ATUADOR_OFF);

  analogReadResolution(12);
  adc1_config_width(ADC_WIDTH_BIT_12);
  adc1_config_channel_atten(ADC1_CHANNEL_6, ADC_ATTEN_DB_11);

  WiFi.mode(WIFI_AP);
  WiFi.setSleep(false);
  WiFi.softAPConfig(IP_AP, IP_AP, MASCARA_AP);
  if (!WiFi.softAP(SSID_AP, SENHA_AP, 6, false, 4)) {
    Serial.println("ERRO: não foi possível iniciar o ponto de acesso.");
  }
  delay(100);
  Serial.print("Ponto de acesso: "); Serial.println(SSID_AP);
  Serial.print("IP: "); Serial.println(WiFi.softAPIP());

  servidor.on("/", HTTP_GET, rotaRaiz);
  servidor.on("/status", HTTP_GET, rotaStatus);
  servidor.on("/sensor", HTTP_GET, rotaSensor);
  servidor.on("/audio.wav", HTTP_GET, rotaAudio);
  servidor.on("/atuador", HTTP_GET, rotaAtuador);
  servidor.on("/config", HTTP_GET, rotaConfig);
  servidor.onNotFound(rotaNaoEncontrada);
  servidor.begin();

  BaseType_t capturaCriada = xTaskCreatePinnedToCore(tarefaCaptura, "captura_audio", 4096, nullptr, 3, &tarefaAmostragem, 1);
  if (capturaCriada != pdPASS) {
    tarefaAmostragem = nullptr;
    Serial.println("ERRO: não foi possível criar a tarefa de áudio.");
    return;
  }
  timerAmostragem = timerBegin(0, 80, true); // timer a 1 MHz no core ESP32 Arduino 2.x
  timerAttachInterrupt(timerAmostragem, &marcarAmostra, true);
  timerAlarmWrite(timerAmostragem, INTERVALO_TIMER_US, true);
  timerAlarmEnable(timerAmostragem);
  Serial.println("Servidor HTTP pronto em http://192.168.4.1/");
}

void loop() {
  servidor.handleClient();
  atualizarTeste();
  delay(1);
}
