// registro_log.cpp — Implementação do log persistente (ver registro_log.h).
#include "registro_log.h"
#include <LittleFS.h>
#include <Preferences.h>
#include <stdarg.h>
#include <sys/time.h>

static const char* ARQUIVO = "/log.txt";
static const char* ARQUIVO_ANTIGO = "/log_antigo.txt";
static constexpr size_t TAMANHO_MAXIMO = 48 * 1024;   // ~500 linhas; depois rotaciona
static constexpr uint32_t ESPERA_RELOGIO_MS = 90000;  // quanto os eventos esperam pela hora certa
static constexpr time_t EPOCH_VALIDO = 1700000000;    // nov/2023: antes disso o relógio não foi ajustado
static constexpr uint8_t MAX_PENDENTES = 24;
static constexpr uint16_t MAX_LINHAS_ENVIO = 500;

struct Evento {
  NivelLog nivel;
  uint32_t uptimeMs;  // millis() no momento do evento
  time_t epoch;       // 0 se o relógio ainda não estava ajustado
  char texto[100];
};

static QueueHandle_t fila = nullptr;
static volatile bool flashOk = false;
static volatile bool montagemConcluida = false;  // até lá, os eventos esperam na fila
static uint32_t boot = 0;
static Evento pendentes[MAX_PENDENTES];  // eventos esperando o relógio (só a tarefa principal mexe)
static uint8_t qtdPendentes = 0;
static bool relogioOk = false;
static char origemRelogio[16] = "NTP";
static volatile uint32_t descartados = 0;  // eventos perdidos por fila cheia

bool relogioAjustado() { return time(nullptr) > EPOCH_VALIDO; }
uint32_t numeroBoot() { return boot; }

void ajustarRelogio(time_t epoch, const char* origem) {
  timeval tv = {epoch, 0};
  settimeofday(&tv, nullptr);
  strlcpy(origemRelogio, origem, sizeof(origemRelogio));
}

void escreverDataHora(char* destino, size_t tamanho) {
  time_t agora = time(nullptr);
  if (agora <= EPOCH_VALIDO) { strlcpy(destino, "sem hora", tamanho); return; }
  tm t;
  localtime_r(&agora, &t);
  strftime(destino, tamanho, "%Y-%m-%d %H:%M:%S", &t);
}

void prepararLog() {
  setenv("TZ", "<-03>3", 1);  // horário de Brasília: UTC-3, sem horário de verão
  tzset();
  fila = xQueueCreate(32, sizeof(Evento));

  // Contador de boots na NVS (memória não volátil): ajuda a ler o log entre reinícios.
  Preferences prefs;
  prefs.begin("sentinela", false);
  boot = prefs.getUInt("boots", 0) + 1;
  prefs.putUInt("boots", boot);
  prefs.end();
}

bool montarFlashDoLog() {
  // true = formata se não conseguir montar (primeira vez). Partição de dados do esquema padrão.
  flashOk = LittleFS.begin(true);
  montagemConcluida = true;
  if (!flashOk) Serial.println("ERRO: nao foi possivel montar o LittleFS (log so na Serial)");
  return flashOk;
}

void registrar(NivelLog nivel, const char* formato, ...) {
  if (!fila) return;
  Evento e;
  e.nivel = nivel;
  e.uptimeMs = millis();
  e.epoch = relogioAjustado() ? time(nullptr) : 0;
  va_list args;
  va_start(args, formato);
  vsnprintf(e.texto, sizeof(e.texto), formato, args);
  va_end(args);
  if (xQueueSend(fila, &e, 0) != pdTRUE) descartados = descartados + 1;  // nunca bloqueia quem chamou
}

// Escreve UMA linha no arquivo: "2026-11-11 14:03:22 [AVISO] mensagem".
static void gravar(const Evento& e) {
  static const char* NOMES[] = {"INFO ", "AVISO", "ERRO "};
  char quando[28];
  time_t epoch = e.epoch;
  // Evento de antes do ajuste do relógio: calcula a hora dele voltando no tempo.
  if (epoch == 0 && relogioAjustado()) epoch = time(nullptr) - (time_t)((millis() - e.uptimeMs) / 1000);
  if (epoch != 0) {
    tm t;
    localtime_r(&epoch, &t);
    strftime(quando, sizeof(quando), "%Y-%m-%d %H:%M:%S", &t);
  } else {
    snprintf(quando, sizeof(quando), "sem hora (+%lus)", (unsigned long)(e.uptimeMs / 1000));
  }
  char linha[160];
  int n = snprintf(linha, sizeof(linha), "%s [%s] %s\n", quando, NOMES[e.nivel], e.texto);
  if (n < 0) return;
  if (n >= (int)sizeof(linha)) n = sizeof(linha) - 1;
  Serial.print(linha);
  if (!flashOk) return;

  File f = LittleFS.open(ARQUIVO, FILE_APPEND);
  if (!f) return;
  f.write((const uint8_t*)linha, n);
  size_t tamanho = f.size();
  f.close();
  if (tamanho > TAMANHO_MAXIMO) {  // rotação: o arquivo cheio vira o "antigo"
    LittleFS.remove(ARQUIVO_ANTIGO);
    LittleFS.rename(ARQUIVO, ARQUIVO_ANTIGO);
  }
}

void processarLog() {
  if (!fila || !montagemConcluida) return;  // flash ainda montando: eventos esperam na fila
  if (!relogioOk && relogioAjustado()) {
    relogioOk = true;
    char agora[24];
    escreverDataHora(agora, sizeof(agora));
    registrar(LOG_INFO, "Relógio ajustado pelo %s: %s", origemRelogio, agora);
  }
  if (descartados) {
    uint32_t n = descartados;
    descartados = 0;
    registrar(LOG_AVISO, "%lu evento(s) de log descartados (fila cheia)", (unsigned long)n);
  }

  // Com a hora certa (ou depois de 90 s sem ela), grava; antes disso, guarda na RAM.
  bool podeGravar = relogioOk || millis() > ESPERA_RELOGIO_MS;
  if (podeGravar && qtdPendentes) {
    for (uint8_t i = 0; i < qtdPendentes; i++) gravar(pendentes[i]);
    qtdPendentes = 0;
  }
  Evento e;
  while (xQueueReceive(fila, &e, 0) == pdTRUE) {
    if (podeGravar) { gravar(e); continue; }
    if (qtdPendentes == MAX_PENDENTES) {  // RAM cheia: grava assim mesmo, sem hora
      for (uint8_t i = 0; i < qtdPendentes; i++) gravar(pendentes[i]);
      qtdPendentes = 0;
    }
    pendentes[qtdPendentes++] = e;
  }
}

static void enviarArquivo(WebServer& servidor, const char* nome, size_t inicio) {
  File f = LittleFS.open(nome, FILE_READ);
  if (!f) return;
  f.seek(inicio);
  char bloco[512];
  while (f.available()) {
    size_t n = f.read((uint8_t*)bloco, sizeof(bloco));
    if (n == 0) break;
    servidor.sendContent(bloco, n);
  }
  f.close();
}

// Posição (em bytes) onde começam as últimas `linhas` linhas do arquivo.
// Guarda o início de cada linha num anel de `linhas` posições: memória fixa e pequena.
static size_t inicioDasUltimasLinhas(const char* nome, uint32_t linhas) {
  static uint32_t inicios[MAX_LINHAS_ENVIO];
  File f = LittleFS.open(nome, FILE_READ);
  if (!f) return 0;
  size_t tamanho = f.size();
  uint32_t contagem = 0;
  if (tamanho > 0) inicios[contagem++ % linhas] = 0;
  char bloco[256];
  size_t posicao = 0;
  while (f.available()) {
    size_t n = f.read((uint8_t*)bloco, sizeof(bloco));
    if (n == 0) break;
    for (size_t i = 0; i < n; i++) {
      size_t proxima = posicao + i + 1;
      if (bloco[i] == '\n' && proxima < tamanho) inicios[contagem++ % linhas] = proxima;
    }
    posicao += n;
  }
  f.close();
  return contagem <= linhas ? 0 : inicios[contagem % linhas];
}

void enviarLog(WebServer& servidor, uint32_t linhas, bool completo) {
  servidor.sendHeader("Access-Control-Allow-Origin", "*");
  servidor.sendHeader("Cache-Control", "no-store");
  servidor.setContentLength(CONTENT_LENGTH_UNKNOWN);  // envio em blocos (chunked)
  servidor.send(200, "text/plain; charset=utf-8", "");
  if (!montagemConcluida) {
    servidor.sendContent("Log ainda carregando (montando a memoria flash); tente em alguns segundos\n");
  } else if (!flashOk) {
    servidor.sendContent("ERRO: memoria flash indisponivel; log somente na Serial\n");
  } else if (completo) {
    enviarArquivo(servidor, ARQUIVO_ANTIGO, 0);
    enviarArquivo(servidor, ARQUIVO, 0);
  } else {
    if (linhas < 1) linhas = 1;
    if (linhas > MAX_LINHAS_ENVIO) linhas = MAX_LINHAS_ENVIO;
    enviarArquivo(servidor, ARQUIVO, inicioDasUltimasLinhas(ARQUIVO, linhas));
  }
  servidor.sendContent("");  // bloco vazio = fim da resposta
}
