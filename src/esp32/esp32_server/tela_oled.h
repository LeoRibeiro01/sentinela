// tela_oled.h — Tela OLED SSD1306 128x64 (I2C): o atuador de exibição do SENTINELA.
//
// Mostra o estado atual (NORMAL / ALERTA / DESLIGADO / TESTE), o texto da falha
// diagnosticada (enviado pela rede em /atuador?...&falha=), o IP para acessar a placa,
// a hora e o nível do microfone. Ligação: VCC->3V3, GND->GND, SDA->GPIO21, SCL->GPIO22.
//
// Roda numa tarefa própria (núcleo 0, prioridade baixa), redesenhando a cada 250 ms.
// Detecta a tela sozinha (endereço 0x3C ou 0x3D) e tenta de novo a cada 3 s: o
// firmware funciona igual sem ela e a reconhece se for ligada depois.
#pragma once
#include <Arduino.h>

void iniciarTela();
// Texto da falha/mensagem (UTF-8; os acentos viram letras simples, a fonte da tela não os tem).
// Vazio = mensagem padrão do estado (ex.: "Motor normal").
void definirMensagemTela(const char* texto);
void lerMensagemTela(char* destino, size_t tamanho);
bool telaPresente();
