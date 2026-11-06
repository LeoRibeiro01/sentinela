// atuadores.h — Interface do módulo de atuadores (LEDs, buzzer e LED onboard).
//
// Responsabilidade: guardar o estado do atuador (off/normal/alerta/teste),
// refletir esse estado nos pinos e implementar o modo "auto" (fallback sem IA).
// Todas as funções são chamadas só pelo loop() (mesma tarefa), sem concorrência.
#pragma once
#include <Arduino.h>

enum EstadoAtuador : uint8_t { ATUADOR_OFF, ATUADOR_NORMAL, ATUADOR_ALERTA, ATUADOR_TESTE };

void iniciarAtuadores();
// Muda o estado. Se temBuzzer for true, `buzzer` força o buzzer ligado/desligado.
void definirEstado(EstadoAtuador novo, bool temBuzzer = false, bool buzzer = false);
void atualizarAtuadores();  // chamar no loop(): anima a sequência de teste
EstadoAtuador estadoAtual();
const char* nomeEstado(EstadoAtuador estado);
bool verdeLigado();
bool vermelhoLigado();
bool buzzerLigado();

// Modo automático: o próprio ESP32 liga o alerta quando o nível passa do limiar.
void configurarModoAuto(bool ativo, uint8_t limiar);
bool modoAutoAtivo();
uint8_t limiarAuto();
void processarJanelaAuto(uint8_t nivel);  // chamar uma vez por janela nova de ~250 ms
