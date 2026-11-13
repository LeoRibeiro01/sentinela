// esp32_server.ino — Firmware principal do SENTINELA (ESP32 DevKit v1).
//
// O ESP32 é o SERVIDOR da arquitetura cliente-servidor: abre a porta TCP 80, fica
// passivo aguardando conexões e responde pedidos HTTP (somente GET):
//   /                  dashboard (HTML+CSS+JS embutidos na flash)
//   /status /sensor    estado do sistema, rede (IP/MAC) e leituras do microfone
//   /audio.wav?ms=     trecho de áudio em WAV
//   /atuador?estado=&falha=   LEDs, buzzer e tela OLED
//   /config?modo=&limiar=     modo automático (fallback sem IA)
//   /log?linhas=       log persistente (flash) com ERRO/AVISO/INFO e data/hora
//   /wifi?ssid=&senha= rede Wi-Fi da estação     /relogio?epoch=  acerta a hora
// Módulos: captura_audio (microfone), atuadores (LEDs/buzzer), tela_oled (display),
// rede (Wi-Fi AP+STA), registro_log (log na flash). Este arquivo faz o HTTP:
// recebe pedidos, valida parâmetros e monta as respostas. O WebServer atende um
// cliente por vez, então os handlers são curtos.
#include <WiFi.h>
#include "servidor_rapido.h"  // WebServer que descarta conexões paradas (ver o arquivo)
#include "captura_audio.h"
#include "atuadores.h"
#include "tela_oled.h"
#include "rede.h"
#include "registro_log.h"
#include "pagina_web.h"  // dashboard embutido (gerado por tools/gerar_pagina_esp32.py)

static const char* VERSAO = "2.0";
static constexpr uint32_t INTERVALO_SAUDE_MS = 10000;  // linha de saúde na Serial
static constexpr uint32_t HEAP_BAIXO = 40000;          // abaixo disso: AVISO no log
static constexpr size_t TAMANHO_MAX_FALHA = 40;        // texto da falha (bytes UTF-8)

ServidorRapido servidor(80);
static uint32_t ultimaJanelaAvaliada = 0;
static uint32_t ultimoLogMs = 0;
static uint32_t perdidasNoUltimoLog = 0;
static volatile uint32_t voltasPorSegundo = 0;  // ritmo da tarefa principal (diagnóstico)

// ---------- Utilidades de resposta ----------

// Todas as respostas liberam CORS (o serviço de IA e outras ferramentas leem a API)
// e proíbem cache (o dado precisa ser sempre o atual).
static void adicionarCabecalhos() {
  servidor.sendHeader("Access-Control-Allow-Origin", "*");
  servidor.sendHeader("Cache-Control", "no-store");
}

static void responderJson(int codigo, const char* json) {
  adicionarCabecalhos();
  servidor.send(codigo, "application/json; charset=utf-8", json);
}

// Erro do cliente (400/404): responde e registra AVISO no log, com o IP de quem pediu.
static void responderErro(int codigo, const char* json) {
  registrar(LOG_AVISO, "Pedido inválido (%d) em %s de %s", codigo, servidor.uri().c_str(),
            servidor.client().remoteIP().toString().c_str());
  responderJson(codigo, json);
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

static String ipDoCliente() { return servidor.client().remoteIP().toString(); }

// JSON do atuador, reaproveitado por /status e /atuador.
static void escreverJsonAtuador(char* destino, size_t tamanho) {
  char mensagem[48];
  lerMensagemTela(mensagem, sizeof(mensagem));
  snprintf(destino, tamanho,
           "{\"estado\":\"%s\",\"verde\":%d,\"vermelho\":%d,\"buzzer\":%d,\"tela\":%s,\"falha\":\"%s\"}",
           nomeEstado(estadoAtual()), verdeLigado(), vermelhoLigado(), buzzerLigado(),
           telaPresente() ? "true" : "false", mensagem);
}

// Motivo do último reinício: um reinício inesperado vira ERRO no log.
static const char* motivoReinicio(bool& inesperado) {
  inesperado = true;
  switch (esp_reset_reason()) {
    case ESP_RST_POWERON: inesperado = false; return "energia ligada";
    case ESP_RST_SW: inesperado = false; return "reinício por software";
    case ESP_RST_EXT: inesperado = false; return "botão EN";
    case ESP_RST_DEEPSLEEP: inesperado = false; return "saída do sono profundo";
    case ESP_RST_BROWNOUT: return "queda de tensão (brownout)";
    case ESP_RST_PANIC: return "falha de software (panic)";
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT: return "cão de guarda (watchdog)";
    default: return "motivo desconhecido";
  }
}

// ---------- Rotas ----------

// GET / — a interface web (dashboard) sai da flash da placa, já comprimida em gzip.
// O navegador descomprime sozinho (Content-Encoding). "no-store" impede que ele guarde
// uma cópia: com o ESP32 desligado, a página não abre.
static void rotaPagina() {
  servidor.sendHeader("Content-Encoding", "gzip");
  servidor.sendHeader("Cache-Control", "no-store");
  servidor.send_P(200, "text/html; charset=utf-8", (const char*)PAGINA_GZ, PAGINA_GZ_TAM);
}

static void rotaInfo() {
  responderJson(200, "{\"nome\":\"SENTINELA\",\"versao\":\"2.0\",\"rotas\":[\"/\",\"/status\",\"/sensor\","
                     "\"/audio.wav?ms=1000\",\"/atuador?estado=normal&bip=1\",\"/config?modo=manual\",\"/log?linhas=50\","
                     "\"/wifi?ssid=&senha=\",\"/relogio?epoch=\"]}");
}

static void rotaStatus() {
  char atuador[160];
  escreverJsonAtuador(atuador, sizeof(atuador));
  char rede[420];
  escreverJsonRede(rede, sizeof(rede));
  char hora[24];
  escreverDataHora(hora, sizeof(hora));
  char json[1100];
  snprintf(json, sizeof(json),
           "{\"ok\":true,\"versao\":\"%s\",\"boot\":%lu,\"uptime_s\":%lu,\"hora\":\"%s\",\"hora_ok\":%s,"
           "\"fs_real_hz\":%lu,\"heap_livre\":%lu,\"heap_minimo\":%lu,\"modo\":\"%s\",\"limiar\":%u,"
           "\"atuador\":%s,\"rede\":%s,\"amostras_perdidas\":%lu,\"intervalo_max_us\":%lu,"
           "\"clientes_wifi\":%u,\"laco_hz\":%lu}",
           VERSAO, (unsigned long)numeroBoot(), (unsigned long)(millis() / 1000), hora,
           relogioAjustado() ? "true" : "false", (unsigned long)taxaRealHz(),
           (unsigned long)ESP.getFreeHeap(), (unsigned long)ESP.getMinFreeHeap(),
           modoAutoAtivo() ? "auto" : "manual", limiarAuto(), atuador, rede,
           (unsigned long)amostrasPerdidas(), (unsigned long)intervaloMaximoUs(),
           clientesNoAp(), (unsigned long)voltasPorSegundo);
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

// Texto da falha: até 40 bytes, sem aspas, barras ou caracteres de controle (vai no JSON e na tela).
static bool falhaValida(const String& texto) {
  if (texto.length() > TAMANHO_MAX_FALHA) return false;
  for (size_t i = 0; i < texto.length(); i++) {
    char c = texto[i];
    if (c == '"' || c == '\\' || ((uint8_t)c < 32)) return false;
  }
  return true;
}

static void rotaAtuador() {
  // bip=1 dá um apito leve (fim de diagnóstico). Pode vir sozinho, sem mudar o estado.
  bool bip = servidor.arg("bip") == "1";
  if (!servidor.hasArg("estado")) {
    if (bip) {
      bipar();
      char atuador[160];
      escreverJsonAtuador(atuador, sizeof(atuador));
      char json[200];
      snprintf(json, sizeof(json), "{\"ok\":true,\"atuador\":%s}", atuador);
      responderJson(200, json);
      return;
    }
    responderErro(400, "{\"erro\":\"informe estado=normal|alerta|off|teste (ou bip=1)\"}");
    return;
  }
  bool temBuzzer = servidor.hasArg("buzzer");
  bool buzzer = false;
  if (temBuzzer) {
    String valor = servidor.arg("buzzer");
    if (valor != "0" && valor != "1") {
      responderErro(400, "{\"erro\":\"buzzer deve ser 0 ou 1\"}");
      return;
    }
    buzzer = (valor == "1");
  }
  String falha = servidor.arg("falha");  // vazio se não veio
  if (!falhaValida(falha)) {
    responderErro(400, "{\"erro\":\"falha deve ter ate 40 caracteres, sem aspas ou barras\"}");
    return;
  }

  String estado = servidor.arg("estado");
  EstadoAtuador anterior = estadoAtual();
  if (estado == "normal") definirEstado(ATUADOR_NORMAL, temBuzzer, buzzer);
  else if (estado == "alerta") definirEstado(ATUADOR_ALERTA, temBuzzer, buzzer);
  else if (estado == "off") definirEstado(ATUADOR_OFF);
  else if (estado == "teste") definirEstado(ATUADOR_TESTE);
  else {
    responderErro(400, "{\"erro\":\"estado invalido; use normal, alerta, off ou teste\"}");
    return;
  }
  // O teste não apaga a mensagem: quando ele termina, o estado anterior volta com ela.
  if (estado != "teste") definirMensagemTela(falha.c_str());
  if (bip) bipar();

  // Registra mudanças de estado (a IA repete o mesmo comando várias vezes; isso não vira log).
  if (estadoAtual() != anterior || falha.length() || temBuzzer) {
    registrar(estadoAtual() == ATUADOR_ALERTA ? LOG_AVISO : LOG_INFO, "Atuador -> %s%s%s%s (comando de %s)",
              nomeEstado(estadoAtual()), falha.length() ? " | falha: " : "", falha.c_str(),
              temBuzzer ? (buzzer ? " | buzzer ligado" : " | buzzer desligado") : "", ipDoCliente().c_str());
  }

  char atuador[160];
  escreverJsonAtuador(atuador, sizeof(atuador));
  char json[200];
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
    else { responderErro(400, "{\"erro\":\"modo deve ser auto ou manual\"}"); return; }
  }
  if (servidor.hasArg("limiar") && !lerInteiro(servidor.arg("limiar"), 0, 100, novoLimiar)) {
    responderErro(400, "{\"erro\":\"limiar deve ser inteiro de 0 a 100\"}");
    return;
  }
  if (novoAuto != modoAutoAtivo() || novoLimiar != limiarAuto())
    registrar(LOG_INFO, "Configuração: modo %s, limiar %ld (comando de %s)", novoAuto ? "auto" : "manual",
              novoLimiar, ipDoCliente().c_str());
  configurarModoAuto(novoAuto, (uint8_t)novoLimiar);
  char json[80];
  snprintf(json, sizeof(json), "{\"ok\":true,\"modo\":\"%s\",\"limiar\":%u}",
           modoAutoAtivo() ? "auto" : "manual", limiarAuto());
  responderJson(200, json);
}

// GET /log?linhas=100 (padrão 100, máx. 500) ou /log?completo=1 (arquivos inteiros).
static void rotaLog() {
  long linhas = 100;
  if (servidor.hasArg("linhas") && !lerInteiro(servidor.arg("linhas"), 1, 500, linhas)) {
    responderErro(400, "{\"erro\":\"linhas deve ser inteiro de 1 a 500\"}");
    return;
  }
  enviarLog(servidor, (uint32_t)linhas, servidor.arg("completo") == "1");
}

// GET /relogio?epoch=1762790400 — acerta a data/hora (segundos desde 1970, UTC).
// Usado pelo dashboard quando a placa não tem internet para o NTP.
static void rotaRelogio() {
  String texto = servidor.arg("epoch");
  bool valido = texto.length() == 10;
  for (size_t i = 0; valido && i < texto.length(); i++) valido = isDigit(texto[i]);
  time_t epoch = valido ? (time_t)strtoul(texto.c_str(), nullptr, 10) : 0;
  if (!valido || epoch < 1700000000) {
    responderErro(400, "{\"erro\":\"epoch deve ser o horario Unix em segundos (10 digitos)\"}");
    return;
  }
  bool jaTinhaHora = relogioAjustado();
  ajustarRelogio(epoch, "navegador");
  if (jaTinhaHora) registrar(LOG_INFO, "Relógio reajustado por %s", ipDoCliente().c_str());
  char hora[24];
  escreverDataHora(hora, sizeof(hora));
  char json[80];
  snprintf(json, sizeof(json), "{\"ok\":true,\"hora\":\"%s\"}", hora);
  responderJson(200, json);
}

// GET /wifi?ssid=MinhaRede&senha=12345678 — rede que a estação deve usar (salva na NVS).
// GET /wifi?ssid= (vazio) esquece a rede. A resposta sai ANTES de reconfigurar o rádio.
static void rotaWifi() {
  if (!servidor.hasArg("ssid")) {
    responderErro(400, "{\"erro\":\"informe ssid= (e senha=); ssid vazio esquece a rede\"}");
    return;
  }
  String ssid = servidor.arg("ssid");
  String senha = servidor.arg("senha");
  const char* erro = validarRedeWifi(ssid, senha);
  if (erro) {
    char json[160];
    snprintf(json, sizeof(json), "{\"erro\":\"%s\"}", erro);
    responderErro(400, json);
    return;
  }
  responderJson(200, ssid.length() ? "{\"ok\":true,\"mensagem\":\"conectando; acompanhe em /status e /log\"}"
                                   : "{\"ok\":true,\"mensagem\":\"rede esquecida; so o ponto de acesso fica ativo\"}");
  servidor.client().flush();
  configurarRedeWifi(ssid, senha);
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
    responderErro(400, "{\"erro\":\"ms deve ser inteiro de 200 a 2000\"}");
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
  responderErro(404, "{\"erro\":\"rota nao encontrada\"}");
}

// ---------- Saúde do sistema ----------

// A cada 10 s: linha de saúde na Serial (base do teste de 30 min) e avisos no log
// quando algo sai do normal (memória baixa, perda de amostras).
static void verificarSaude() {
  if (millis() - ultimoLogMs < INTERVALO_SAUDE_MS) return;
  ultimoLogMs = millis();
  LeituraSensor l = lerSensor();
  Serial.printf("[saude] uptime=%lus heap=%lu heap_min=%lu fs=%luHz perdidas=%lu int_max=%luus "
                "rms=%u adc=[%u..%u] clientes=%u estado=%s laco=%luHz sta=%s\n",
                (unsigned long)(millis() / 1000), (unsigned long)ESP.getFreeHeap(),
                (unsigned long)ESP.getMinFreeHeap(), (unsigned long)taxaRealHz(),
                (unsigned long)amostrasPerdidas(), (unsigned long)intervaloMaximoUs(),
                l.rms, l.adcMin, l.adcMax, clientesNoAp(), nomeEstado(estadoAtual()),
                (unsigned long)voltasPorSegundo, staConectado() ? "sim" : "nao");
  if (ESP.getFreeHeap() < HEAP_BAIXO)
    registrar(LOG_AVISO, "Memória livre baixa: %lu bytes", (unsigned long)ESP.getFreeHeap());
  uint32_t perdidas = amostrasPerdidas();
  if (perdidas - perdidasNoUltimoLog > 1600)  // > 1% das amostras em 10 s
    registrar(LOG_AVISO, "Captura de áudio perdeu %lu amostras em 10 s",
              (unsigned long)(perdidas - perdidasNoUltimoLog));
  perdidasNoUltimoLog = perdidas;
}

// ---------- Inicialização e laço principal ----------

// Imprime na Serial quanto tempo levou cada etapa do boot (diagnóstico de inicialização lenta).
static uint32_t marcaBootMs = 0;
static void tempoEtapa(const char* etapa) {
  Serial.printf("[boot] %-22s %5lu ms\n", etapa, (unsigned long)(millis() - marcaBootMs));
  marcaBootMs = millis();
}

void setup() {
  Serial.begin(115200);
  Serial.println("\nSENTINELA iniciando...");
  marcaBootMs = millis();
  prepararLog();  // instantâneo: a partir daqui tudo pode ser registrado (fica na fila)
  bool inesperado = false;
  const char* motivo = motivoReinicio(inesperado);
  registrar(inesperado ? LOG_ERRO : LOG_INFO, "=== Boot #%lu: SENTINELA v%s ligado (%s) ===",
            (unsigned long)numeroBoot(), VERSAO, motivo);
  tempoEtapa("log (fila e boot)");

  iniciarAtuadores();
  iniciarRede();
  tempoEtapa("rede (AP + estacao)");

  servidor.on("/", HTTP_GET, rotaPagina);
  servidor.on("/info", HTTP_GET, rotaInfo);
  servidor.on("/status", HTTP_GET, rotaStatus);
  servidor.on("/sensor", HTTP_GET, rotaSensor);
  servidor.on("/audio.wav", HTTP_GET, rotaAudio);
  servidor.on("/atuador", HTTP_GET, rotaAtuador);
  servidor.on("/config", HTTP_GET, rotaConfig);
  servidor.on("/log", HTTP_GET, rotaLog);
  servidor.on("/relogio", HTTP_GET, rotaRelogio);
  servidor.on("/wifi", HTTP_GET, rotaWifi);
  servidor.onNotFound(rotaNaoEncontrada);
  servidor.begin();
  registrar(LOG_INFO, "Servidor HTTP ouvindo na porta TCP 80");
  tempoEtapa("servidor HTTP");

  iniciarTela();
  // Pilha de 8 KB (igual à do loop() do Arduino); prioridade 1, abaixo do Wi-Fi.
  xTaskCreatePinnedToCore(tarefaPrincipal, "principal", 8192, nullptr, 1, nullptr, 0);
  tempoEtapa("tela e tarefa principal");
  Serial.printf("Servidor no ar em %lu ms. Heap livre: %lu bytes\n", (unsigned long)millis(),
                (unsigned long)ESP.getFreeHeap());

  // A flash do log: o servidor já atende enquanto ela monta, e os eventos do boot
  // ficam esperando na fila até a montagem terminar.
  if (!montarFlashDoLog()) registrar(LOG_ERRO, "Memória flash do log indisponível: registros só na Serial");
  tempoEtapa("montagem do LittleFS");

  // A captura de áudio é a ÚLTIMA etapa. Ela roda no núcleo 1 (o mesmo do setup) com
  // prioridade maior, 16 mil vezes por segundo: depois que começa, o que sobrar do setup
  // quase não ganha CPU. Medido na placa em 12/11: com a captura antes da tela, o
  // restante do setup levou 25 s; depois dela, o setup termina aqui.
  if (!iniciarCaptura()) registrar(LOG_ERRO, "Falha ao iniciar a captura de áudio (microfone)");
  tempoEtapa("captura de audio");
}

// Tarefa principal: servidor HTTP, modo auto, reconexão Wi-Fi, gravação do log e saúde.
// Roda no NÚCLEO 0, longe da captura de áudio (núcleo 1). Medido na placa em 09/11:
// no núcleo 1, a captura a 16 kHz (prioridade maior) deixava só ~22 voltas/s para
// o loop(); cada pedido HTTP precisava de várias voltas e expirava no navegador.
// É a ÚNICA tarefa que mexe nos atuadores e que escreve na flash: sem condição de corrida.
static void tarefaPrincipal(void*) {
  uint32_t voltas = 0, inicioContagemMs = millis();
  for (;;) {
    servidor.handleClient();

    // O modo auto é avaliado aqui (e não na tarefa de áudio) para que só esta
    // tarefa mexa nos atuadores, evitando conflito com os comandos HTTP.
    LeituraSensor l = lerSensor();
    if (l.numeroJanela != ultimaJanelaAvaliada) {
      ultimaJanelaAvaliada = l.numeroJanela;
      EstadoAtuador antes = estadoAtual();
      processarJanelaAuto(l.nivel);
      if (estadoAtual() != antes && estadoAtual() == ATUADOR_ALERTA) {
        definirMensagemTela("Ruido acima do limiar");
        registrar(LOG_AVISO, "Modo auto: nível %u acima do limiar %u -> ALERTA", l.nivel, limiarAuto());
      } else if (estadoAtual() != antes && estadoAtual() == ATUADOR_NORMAL) {
        definirMensagemTela("");
        registrar(LOG_INFO, "Modo auto: nível voltou ao normal -> NORMAL");
      }
    }
    atualizarAtuadores();
    processarRede();
    processarLog();
    verificarSaude();

    voltas++;
    if (millis() - inicioContagemMs >= 1000) {
      voltasPorSegundo = voltas;
      voltas = 0;
      inicioContagemMs = millis();
    }
    vTaskDelay(1);  // cede a CPU (Wi-Fi e a tarefa ociosa, vigiada pelo watchdog)
  }
}

void loop() {
  // Todo o trabalho está em tarefaPrincipal (núcleo 0); o loop() do Arduino só dorme.
  vTaskDelay(pdMS_TO_TICKS(1000));
}
