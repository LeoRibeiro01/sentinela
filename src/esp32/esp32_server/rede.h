// rede.h — Conectividade Wi-Fi do SENTINELA.
//
// Dois papéis ao mesmo tempo (modo AP+STA):
//  - ESTAÇÃO (STA): conecta-se a uma rede Wi-Fi existente (roteador ou hotspot do
//    celular), como pede o regulamento. Se a conexão cair, tenta de novo sozinha a
//    cada 15 s e registra queda e reconexão (com data e hora) no log da flash.
//    O nome e a senha da rede ficam na NVS e podem ser trocados pela rota /wifi.
//  - PONTO DE ACESSO (AP): a rede própria "SENTINELA" (192.168.4.1) continua sempre
//    ativa como plano B, para acessar a placa mesmo sem nenhum roteador.
// Também anuncia o nome "sentinela.local" (mDNS) e acerta o relógio pelo NTP
// quando a rede da estação tem internet.
#pragma once
#include <Arduino.h>

void iniciarRede();       // liga o AP e, se houver rede salva, a estação
void processarRede();     // chamar na tarefa principal: cuida das tentativas de reconexão

// Salva a rede na NVS e conecta. ssid vazio = esquecer a rede (fica só o AP).
// Devolve uma mensagem de erro (ou nullptr se os dados forem válidos).
const char* validarRedeWifi(const String& ssid, const String& senha);
void configurarRedeWifi(const String& ssid, const String& senha);

bool staConectado();
void escreverIpPrincipal(char* destino, size_t tamanho);  // IP da estação, ou do AP se não conectada
void escreverJsonRede(char* destino, size_t tamanho);     // bloco "rede" do /status
uint8_t clientesNoAp();
