// atuadores.cpp — Controle dos LEDs verde/vermelho, do buzzer ativo e do LED onboard.
//
// normal = verde aceso; alerta = vermelho (+ LED azul onboard); off = tudo apagado;
// teste = sequência de ~2 s (pisca verde/vermelho e um bipe curto) e depois volta ao
// estado anterior. O buzzer NÃO acompanha o alerta (um apito contínuo incomodava e
// disparava com o barulho da sala no modo auto): ele só dá bipes curtos, pedidos com
// bipar() — por exemplo, quando a IA termina um diagnóstico. O LED onboard (GPIO2) espelha o alerta,
// o que permite testar a lógica sem nenhum componente externo ligado.
#include "atuadores.h"

static constexpr uint8_t PINO_VERDE = 16;
static constexpr uint8_t PINO_VERMELHO = 17;
static constexpr uint8_t PINO_BUZZER = 18;
static constexpr uint8_t PINO_ONBOARD = 2;  // só usado como saída depois do boot
static constexpr uint32_t DURACAO_TESTE_MS = 2000;
static constexpr uint32_t DURACAO_BIP_MS = 150;  // apito leve
static constexpr uint8_t JANELAS_PARA_ALERTA = 3;  // ~0,75 s acima do limiar
static constexpr uint8_t JANELAS_PARA_NORMAL = 8;  // ~2 s abaixo (histerese evita pisca-pisca)

static EstadoAtuador estado = ATUADOR_OFF;
static EstadoAtuador estadoAntesDoTeste = ATUADOR_OFF;
static bool buzzerForcado = false;   // true quando o comando trouxe &buzzer=
static bool valorBuzzerForcado = false;
static uint32_t inicioTesteMs = 0;
static bool verde = false, vermelho = false, buzzer = false;
static uint32_t fimBipMs = 0;  // millis() em que o bipe atual termina (0 = sem bipe)

static bool modoAuto = false;
static uint8_t limiar = 45;
static uint8_t janelasAcima = 0, janelasAbaixo = 0;

// Calcula o que cada saída deve fazer agora e escreve nos pinos.
static void aplicarSaidas() {
  verde = (estado == ATUADOR_NORMAL);
  vermelho = (estado == ATUADOR_ALERTA);
  buzzer = buzzerForcado && valorBuzzerForcado;  // por padrão o buzzer fica quieto

  if (estado == ATUADOR_TESTE) {
    // Etapas de 250 ms: verde, vermelho, verde, vermelho, beep, beep, apagado, apagado.
    uint32_t etapa = (millis() - inicioTesteMs) / 250;
    verde = (etapa == 0 || etapa == 2);
    vermelho = (etapa == 1 || etapa == 3);
    buzzer = (millis() - inicioTesteMs >= 1000 && millis() - inicioTesteMs < 1000 + DURACAO_BIP_MS);
  }

  digitalWrite(PINO_VERDE, verde ? HIGH : LOW);
  digitalWrite(PINO_VERMELHO, vermelho ? HIGH : LOW);
  if (fimBipMs && (int32_t)(fimBipMs - millis()) > 0) buzzer = true;  // bipe curto em andamento
  digitalWrite(PINO_BUZZER, buzzer ? HIGH : LOW);
  digitalWrite(PINO_ONBOARD, vermelho ? HIGH : LOW);
}

void iniciarAtuadores() {
  pinMode(PINO_VERDE, OUTPUT);
  pinMode(PINO_VERMELHO, OUTPUT);
  pinMode(PINO_BUZZER, OUTPUT);
  pinMode(PINO_ONBOARD, OUTPUT);
  definirEstado(ATUADOR_OFF);  // tudo desligado na partida
}

void definirEstado(EstadoAtuador novo, bool temBuzzer, bool valorBuzzer) {
  if (novo == ATUADOR_TESTE) {
    // Lembra o estado anterior para voltar a ele quando o teste acabar.
    if (estado != ATUADOR_TESTE) estadoAntesDoTeste = estado;
    inicioTesteMs = millis();
  }
  estado = novo;
  buzzerForcado = temBuzzer;
  valorBuzzerForcado = valorBuzzer;
  aplicarSaidas();
}

void bipar() {
  fimBipMs = millis() + DURACAO_BIP_MS;
  aplicarSaidas();
}

void atualizarAtuadores() {
  if (fimBipMs && (int32_t)(fimBipMs - millis()) <= 0) {  // o bipe acabou: desliga o buzzer
    fimBipMs = 0;
    aplicarSaidas();
  }
  if (estado != ATUADOR_TESTE) return;
  if (millis() - inicioTesteMs >= DURACAO_TESTE_MS) definirEstado(estadoAntesDoTeste);
  else aplicarSaidas();
}

EstadoAtuador estadoAtual() { return estado; }

const char* nomeEstado(EstadoAtuador e) {
  switch (e) {
    case ATUADOR_NORMAL: return "normal";
    case ATUADOR_ALERTA: return "alerta";
    case ATUADOR_TESTE: return "teste";
    default: return "off";
  }
}

bool verdeLigado() { return verde; }
bool vermelhoLigado() { return vermelho; }
bool buzzerLigado() { return buzzer; }

void configurarModoAuto(bool ativo, uint8_t novoLimiar) {
  limiar = novoLimiar;
  janelasAcima = 0;
  janelasAbaixo = 0;
  // Ao entrar no modo auto partindo de "off", acende o verde para mostrar que está vigiando.
  if (ativo && !modoAuto && estado == ATUADOR_OFF) definirEstado(ATUADOR_NORMAL);
  modoAuto = ativo;
}

bool modoAutoAtivo() { return modoAuto; }
uint8_t limiarAuto() { return limiar; }

void processarJanelaAuto(uint8_t nivel) {
  if (!modoAuto || estado == ATUADOR_TESTE) return;
  if (nivel > limiar) {
    janelasAbaixo = 0;
    if (janelasAcima < JANELAS_PARA_ALERTA) janelasAcima++;
    if (janelasAcima >= JANELAS_PARA_ALERTA && estado != ATUADOR_ALERTA) definirEstado(ATUADOR_ALERTA);
  } else {
    janelasAcima = 0;
    if (janelasAbaixo < JANELAS_PARA_NORMAL) janelasAbaixo++;
    if (janelasAbaixo >= JANELAS_PARA_NORMAL && estado == ATUADOR_ALERTA) definirEstado(ATUADOR_NORMAL);
  }
}
