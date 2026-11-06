// captura_audio.h — Interface do módulo de captura de áudio do MAX9814.
//
// Responsabilidade: amostrar o microfone (GPIO34, ADC1_CH6) a 16 kHz em segundo
// plano, guardar os ~2 s mais recentes num buffer circular e publicar a cada
// ~250 ms as métricas da janela (RMS, pico, nível, clipping).
// Quem usa este módulo (o servidor HTTP) só lê dados; nunca escreve no buffer.
#pragma once
#include <Arduino.h>

static constexpr uint32_t TAXA_ALVO_HZ = 16000;     // taxa de amostragem desejada
static constexpr uint32_t CAPACIDADE_AUDIO = 32768; // amostras no buffer (64 KB, ~2,05 s)

// Resumo da última janela de ~250 ms. É copiado inteiro para evitar mistura de janelas.
struct LeituraSensor {
  uint16_t rms;          // RMS em contagens do ADC, já sem o nível DC
  uint16_t pico;         // maior desvio absoluto em relação ao DC
  uint8_t nivel;         // escala relativa 0..100 para o dashboard (não é dB)
  bool clipping;         // ADC encostou em 0 ou 4095 nesta janela
  uint16_t adcMin;       // menor leitura bruta da janela (diagnóstico de leituras zeradas)
  uint16_t adcMax;       // maior leitura bruta da janela
  uint32_t tsMs;         // millis() em que a janela foi fechada
  uint32_t numeroJanela; // contador crescente; muda quando há janela nova
};

bool iniciarCaptura();          // cria a tarefa e liga o timer; false se falhar
LeituraSensor lerSensor();      // cópia consistente da última janela
uint32_t taxaRealHz();          // amostras efetivamente lidas no último segundo
uint32_t intervaloMaximoUs();   // maior intervalo entre duas amostras no último segundo
uint32_t amostrasPerdidas();    // total de ticks do timer sem leitura (desde o boot)
uint32_t totalAmostras();       // total de amostras gravadas desde o boot

// Índice no buffer onde começa o trecho com as `quantidade` amostras mais recentes.
uint32_t inicioTrechoRecente(uint32_t quantidade);
// Copia `n` amostras a partir de `indice` (dá a volta no fim do buffer).
void copiarAmostras(uint32_t indice, int16_t* destino, uint32_t n);
