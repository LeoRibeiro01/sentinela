// tela_oled.cpp — Implementação da tela OLED (ver tela_oled.h).
#include "tela_oled.h"
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "atuadores.h"
#include "captura_audio.h"
#include "rede.h"
#include "registro_log.h"

static constexpr uint8_t PINO_SDA = 21;
static constexpr uint8_t PINO_SCL = 22;
static constexpr uint32_t PERIODO_MS = 250;        // 4 quadros por segundo
static constexpr uint32_t NOVA_PROCURA_MS = 3000;  // sem tela: procura de novo a cada 3 s
static constexpr uint8_t COLUNAS = 21;             // 128 px / 6 px por letra (fonte padrão)

static Adafruit_SSD1306 tela(128, 64, &Wire, -1);  // -1: o módulo de 4 pinos não tem pino de reset
static volatile bool presente = false;
static uint8_t endereco = 0;
static char mensagem[44] = "";
static portMUX_TYPE trava = portMUX_INITIALIZER_UNLOCKED;  // mensagem é escrita por outra tarefa

// Converte UTF-8 para ASCII simples: "Ignição" -> "Ignicao". A fonte do OLED não tem acentos.
static void paraAscii(const char* origem, char* destino, size_t tamanho) {
  size_t j = 0;
  for (size_t i = 0; origem[i] && j + 1 < tamanho; i++) {
    uint8_t c = (uint8_t)origem[i];
    if (c < 0x80) { destino[j++] = (c >= 32) ? (char)c : ' '; continue; }
    if (c == 0xC3 && origem[i + 1]) {  // letras latinas acentuadas (U+00C0..U+00FF)
      uint8_t d = (uint8_t)origem[++i];
      char base = '?';
      if (d >= 0x80 && d <= 0x85) base = 'A';
      else if (d == 0x87) base = 'C';
      else if (d >= 0x88 && d <= 0x8B) base = 'E';
      else if (d >= 0x8C && d <= 0x8F) base = 'I';
      else if (d == 0x91) base = 'N';
      else if (d >= 0x92 && d <= 0x96) base = 'O';
      else if (d >= 0x99 && d <= 0x9C) base = 'U';
      else if (d >= 0xA0 && d <= 0xA5) base = 'a';
      else if (d == 0xA7) base = 'c';
      else if (d >= 0xA8 && d <= 0xAB) base = 'e';
      else if (d >= 0xAC && d <= 0xAF) base = 'i';
      else if (d == 0xB1) base = 'n';
      else if (d >= 0xB2 && d <= 0xB6) base = 'o';
      else if (d >= 0xB9 && d <= 0xBC) base = 'u';
      destino[j++] = base;
      continue;
    }
    // Outros caracteres de vários bytes: pula os bytes de continuação e põe '?'.
    while ((uint8_t)origem[i + 1] >= 0x80 && (uint8_t)origem[i + 1] < 0xC0) i++;
    destino[j++] = '?';
  }
  destino[j] = '\0';
}

void definirMensagemTela(const char* texto) {
  char limpo[sizeof(mensagem)];
  paraAscii(texto ? texto : "", limpo, sizeof(limpo));
  portENTER_CRITICAL(&trava);
  strlcpy(mensagem, limpo, sizeof(mensagem));
  portEXIT_CRITICAL(&trava);
}

void lerMensagemTela(char* destino, size_t tamanho) {
  portENTER_CRITICAL(&trava);
  strlcpy(destino, mensagem, tamanho);
  portEXIT_CRITICAL(&trava);
}

bool telaPresente() { return presente; }

static uint8_t procurarEndereco() {
  const uint8_t candidatos[] = {0x3C, 0x3D};  // os dois endereços possíveis do SSD1306
  for (uint8_t a : candidatos) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) return a;
  }
  return 0;
}

static void escreverCentralizado(const char* texto, int16_t y, uint8_t escala) {
  int16_t largura = strlen(texto) * 6 * escala;
  tela.setTextSize(escala);
  tela.setCursor(largura < 128 ? (128 - largura) / 2 : 0, y);
  tela.print(texto);
}

static void desenhar() {
  EstadoAtuador estado = estadoAtual();
  LeituraSensor leitura = lerSensor();
  char texto[sizeof(mensagem)];
  lerMensagemTela(texto, sizeof(texto));
  if (!texto[0]) {  // sem texto vindo da rede: mensagem padrão do estado
    const char* padrao = estado == ATUADOR_NORMAL ? "Motor normal"
                       : estado == ATUADOR_ALERTA ? "Falha detectada"
                       : estado == ATUADOR_TESTE  ? "Testando atuadores"
                                                  : "Aguardando comando";
    strlcpy(texto, padrao, sizeof(texto));
  }

  tela.clearDisplay();
  tela.setTextColor(SSD1306_WHITE);

  // Linha 1: nome do sistema e hora.
  tela.setTextSize(1);
  tela.setCursor(0, 0);
  tela.print("SENTINELA");
  char hora[8] = "--:--";
  if (relogioAjustado()) {
    time_t agora = time(nullptr);
    tm t;
    localtime_r(&agora, &t);
    strftime(hora, sizeof(hora), "%H:%M", &t);
  }
  tela.setCursor(128 - 5 * 6, 0);
  tela.print(hora);
  tela.drawFastHLine(0, 10, 128, SSD1306_WHITE);

  // Estado em letras grandes. No alerta, a faixa pisca (inverte) a cada 0,5 s.
  const char* titulo = estado == ATUADOR_NORMAL ? "NORMAL"
                     : estado == ATUADOR_ALERTA ? "ALERTA"
                     : estado == ATUADOR_TESTE  ? "TESTE"
                                                : "DESLIGADO";
  bool inverter = (estado == ATUADOR_ALERTA) && ((millis() / 500) % 2 == 0);
  if (inverter) {
    tela.fillRect(0, 13, 128, 18, SSD1306_WHITE);
    tela.setTextColor(SSD1306_BLACK);
  }
  escreverCentralizado(titulo, 15, 2);
  tela.setTextColor(SSD1306_WHITE);

  // Falha/mensagem: até 2 linhas de 21 letras, quebrando no último espaço.
  size_t n = strlen(texto);
  size_t corte = n;
  if (n > COLUNAS) {
    corte = COLUNAS;
    for (size_t i = COLUNAS; i > 0; i--) {
      if (texto[i] == ' ') { corte = i; break; }
    }
  }
  char linha1[COLUNAS + 1], linha2[COLUNAS + 1];
  strlcpy(linha1, texto, min(corte, (size_t)COLUNAS) + 1);
  const char* resto = texto + corte;
  while (*resto == ' ') resto++;
  strlcpy(linha2, resto, sizeof(linha2));
  escreverCentralizado(linha1, 34, 1);
  escreverCentralizado(linha2, 43, 1);

  // Rodapé: IP para acessar a placa ("AP" = rede própria SENTINELA) e barra de nível.
  char ip[20];
  escreverIpPrincipal(ip, sizeof(ip));
  tela.setTextSize(1);
  tela.setCursor(0, 53);
  tela.print(staConectado() ? "IP " : "AP ");
  tela.print(ip);
  tela.fillRect(0, 62, (int16_t)leitura.nivel * 128 / 100, 2, SSD1306_WHITE);

  tela.display();  // envia o quadro inteiro (1 KB) pelo I2C
}

static void tarefaTela(void*) {
  uint32_t ultimaProcuraMs = 0;
  bool avisouAusencia = false;
  for (;;) {
    if (!presente) {
      if (ultimaProcuraMs == 0 || millis() - ultimaProcuraMs >= NOVA_PROCURA_MS) {
        ultimaProcuraMs = millis();
        endereco = procurarEndereco();
        // periphBegin=false: o Wire já foi configurado com os pinos certos em iniciarTela().
        if (endereco && tela.begin(SSD1306_SWITCHCAPVCC, endereco, true, false)) {
          presente = true;
          registrar(LOG_INFO, "Tela OLED detectada no endereço I2C 0x%02X", endereco);
        } else if (!avisouAusencia) {
          avisouAusencia = true;
          registrar(LOG_AVISO, "Tela OLED não encontrada (I2C 0x3C/0x3D, SDA 21, SCL 22); seguindo sem ela");
        }
      }
    } else {
      Wire.beginTransmission(endereco);  // confere se a tela continua respondendo
      if (Wire.endTransmission() != 0) {
        presente = false;
        registrar(LOG_ERRO, "Tela OLED parou de responder no I2C (fio solto?)");
      } else {
        desenhar();
      }
    }
    vTaskDelay(pdMS_TO_TICKS(PERIODO_MS));
  }
}

void iniciarTela() {
  Wire.begin(PINO_SDA, PINO_SCL);
  Wire.setClock(400000);  // I2C rápido: um quadro leva ~25 ms
  // Pilha de 4 KB, prioridade 1, núcleo 0 (longe da captura de áudio no núcleo 1).
  xTaskCreatePinnedToCore(tarefaTela, "tela", 4096, nullptr, 1, nullptr, 0);
}
