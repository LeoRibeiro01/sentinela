// captura_audio.cpp — Amostragem do MAX9814 a 16 kHz com timer de hardware.
//
// Fluxo: o timer 0 dispara a cada 62,5 us (16 kHz) e só "acorda" a tarefa de
// captura (a interrupção é mínima: não lê o ADC, porque adc1_get_raw usa travas
// que não podem ser usadas dentro de interrupção). A tarefa roda no núcleo 1,
// lê o ADC, remove o DC, grava no buffer circular e fecha janelas de ~250 ms.
// O Wi-Fi roda no núcleo 0, então a captura não disputa CPU com a pilha de rede.
// Não há Serial.print nem delay() dentro do laço de amostragem.
#include "captura_audio.h"
#include <driver/adc.h>
#include <math.h>

static constexpr adc1_channel_t CANAL_MICROFONE = ADC1_CHANNEL_6; // GPIO34
static constexpr uint32_t AMOSTRAS_JANELA = TAXA_ALVO_HZ / 4;     // 4000 = 250 ms
static constexpr float ALFA_DC = 1.0f / 1024.0f;  // média móvel do DC (~2,5 Hz de corte)
static constexpr int32_t GANHO_PCM = 16;          // 12 bits do ADC -> faixa de 16 bits
static constexpr uint32_t RMS_NIVEL_100 = 600;    // RMS que corresponde a nível 100

// Buffer circular estático (sem PSRAM nesta placa): 32768 × 2 bytes = 64 KB.
static int16_t bufferAudio[CAPACIDADE_AUDIO];
static volatile uint32_t indiceEscrita = 0;  // próxima posição a ser gravada
static volatile uint32_t contadorAmostras = 0;

static volatile uint32_t taxaMedida = 0;
static volatile uint32_t intervaloMaximo = 0;
static volatile uint32_t perdidas = 0;

static LeituraSensor ultimaLeitura = {};
static portMUX_TYPE travaLeitura = portMUX_INITIALIZER_UNLOCKED;
static TaskHandle_t tarefaCapturaHandle = nullptr;
static hw_timer_t* timerAmostragem = nullptr;

// Interrupção do timer: apenas notifica a tarefa. Fica na IRAM por ser chamada 16 mil vezes/s.
static void IRAM_ATTR aoTickDoTimer() {
  BaseType_t precisaTrocar = pdFALSE;
  vTaskNotifyGiveFromISR(tarefaCapturaHandle, &precisaTrocar);
  if (precisaTrocar) portYIELD_FROM_ISR();
}

static void tarefaCaptura(void*) {
  // Começa a média do DC na leitura atual para não haver transiente na partida.
  float mediaDc = (float)adc1_get_raw(CANAL_MICROFONE);
  uint64_t somaQuadrados = 0;
  uint16_t picoJanela = 0, minJanela = 4095, maxJanela = 0;
  uint32_t contagemJanela = 0, numeroJanela = 0;
  uint32_t contagemSegundo = 0, maiorIntervaloSegundo = 0;
  uint32_t inicioSegundoUs = micros(), ultimaAmostraUs = micros();

  for (;;) {
    // Dorme até o timer notificar. Se voltar com mais de 1 notificação, a tarefa
    // atrasou e perdeu ticks: contamos para medir a estabilidade da amostragem.
    uint32_t pendentes = ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
    if (pendentes > 1) perdidas += pendentes - 1;

    uint32_t agoraUs = micros();
    uint32_t intervalo = agoraUs - ultimaAmostraUs;
    ultimaAmostraUs = agoraUs;
    if (intervalo > maiorIntervaloSegundo) maiorIntervaloSegundo = intervalo;

    int leitura = adc1_get_raw(CANAL_MICROFONE);
    if (leitura < 0) { perdidas++; continue; }  // erro do driver: descarta a amostra

    // Remove o nível DC (~1,25 V do MAX9814) com média móvel em ponto flutuante.
    // Em float não há a "zona morta" que um filtro inteiro com deslocamento teria.
    mediaDc += ((float)leitura - mediaDc) * ALFA_DC;
    int32_t semDc = (int32_t)((float)leitura - mediaDc);

    int32_t pcm = semDc * GANHO_PCM;
    if (pcm > 32767) pcm = 32767;
    if (pcm < -32768) pcm = -32768;
    bufferAudio[indiceEscrita] = (int16_t)pcm;
    indiceEscrita = (indiceEscrita + 1) % CAPACIDADE_AUDIO;
    contadorAmostras++;
    contagemSegundo++;

    // Acumula as métricas da janela atual.
    somaQuadrados += (uint64_t)((int64_t)semDc * semDc);
    uint16_t desvio = (uint16_t)abs(semDc);
    if (desvio > picoJanela) picoJanela = desvio;
    if (leitura < minJanela) minJanela = (uint16_t)leitura;
    if (leitura > maxJanela) maxJanela = (uint16_t)leitura;

    // A cada 1 s publica a taxa real e o pior intervalo observado.
    if (agoraUs - inicioSegundoUs >= 1000000) {
      taxaMedida = (uint32_t)((uint64_t)contagemSegundo * 1000000 / (agoraUs - inicioSegundoUs));
      intervaloMaximo = maiorIntervaloSegundo;
      contagemSegundo = 0;
      maiorIntervaloSegundo = 0;
      inicioSegundoUs = agoraUs;
    }

    if (++contagemJanela < AMOSTRAS_JANELA) continue;

    // Fecha a janela de ~250 ms e publica o resumo de forma atômica.
    LeituraSensor nova;
    nova.rms = (uint16_t)sqrtf((float)somaQuadrados / contagemJanela);
    nova.pico = picoJanela;
    nova.nivel = (uint8_t)min((uint32_t)100, (uint32_t)nova.rms * 100 / RMS_NIVEL_100);
    nova.clipping = (minJanela <= 5 || maxJanela >= 4090);
    nova.adcMin = minJanela;
    nova.adcMax = maxJanela;
    nova.tsMs = millis();
    nova.numeroJanela = ++numeroJanela;
    portENTER_CRITICAL(&travaLeitura);
    ultimaLeitura = nova;
    portEXIT_CRITICAL(&travaLeitura);

    somaQuadrados = 0;
    picoJanela = 0; minJanela = 4095; maxJanela = 0;
    contagemJanela = 0;
  }
}

bool iniciarCaptura() {
  // ADC1 com 12 bits e atenuação máxima ("11 dB", hoje chamada DB_12; faixa ~0,15–2,45 V). ADC2 não funciona com Wi-Fi.
  adc1_config_width(ADC_WIDTH_BIT_12);
  adc1_config_channel_atten(CANAL_MICROFONE, ADC_ATTEN_DB_12);  // "12 dB" = antigo 11 dB, mesmo efeito

  // Prioridade 3 (acima do loop(), que é 1) no núcleo 1; o Wi-Fi fica no núcleo 0.
  if (xTaskCreatePinnedToCore(tarefaCaptura, "captura_audio", 4096, nullptr, 3,
                              &tarefaCapturaHandle, 1) != pdPASS) {
    return false;
  }
  // Timer 0 com divisor 40: 80 MHz / 40 = 2 MHz. Alarme a cada 125 ticks = 62,5 us = 16 kHz exatos.
  timerAmostragem = timerBegin(0, 40, true);
  timerAttachInterrupt(timerAmostragem, &aoTickDoTimer, true);
  timerAlarmWrite(timerAmostragem, 125, true);
  timerAlarmEnable(timerAmostragem);
  return true;
}

LeituraSensor lerSensor() {
  portENTER_CRITICAL(&travaLeitura);
  LeituraSensor copia = ultimaLeitura;
  portEXIT_CRITICAL(&travaLeitura);
  return copia;
}

uint32_t taxaRealHz() { return taxaMedida; }
uint32_t intervaloMaximoUs() { return intervaloMaximo; }
uint32_t amostrasPerdidas() { return perdidas; }
uint32_t totalAmostras() { return contadorAmostras; }

uint32_t inicioTrechoRecente(uint32_t quantidade) {
  return (indiceEscrita + CAPACIDADE_AUDIO - quantidade) % CAPACIDADE_AUDIO;
}

void copiarAmostras(uint32_t indice, int16_t* destino, uint32_t n) {
  for (uint32_t i = 0; i < n; i++) destino[i] = bufferAudio[(indice + i) % CAPACIDADE_AUDIO];
}
