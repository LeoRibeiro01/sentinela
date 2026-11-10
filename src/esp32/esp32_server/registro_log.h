// registro_log.h — Log do sistema persistente na memória flash (LittleFS).
//
// Requisito do TDE: os clientes da rede acessam um log persistente com todas as
// ocorrências marcadas como ERRO, AVISO ou INFO, com data e hora de cada evento.
//
// Como funciona:
//  - registrar() pode ser chamado de QUALQUER tarefa (inclusive dos eventos de Wi-Fi):
//    só coloca a mensagem numa fila do FreeRTOS, sem tocar na flash.
//  - processarLog() roda na tarefa principal: tira as mensagens da fila e grava
//    no arquivo /log.txt. Uma única tarefa escreve na flash = sem conflito.
//  - Data e hora: o relógio vem do NTP (quando a placa tem internet pela rede Wi-Fi)
//    ou do navegador (rota /relogio). Eventos anteriores ao ajuste (ex.: o boot)
//    esperam até 90 s na RAM e são gravados com a hora corrigida retroativamente.
//  - O arquivo é limitado a ~48 KB; ao encher, vira /log_antigo.txt (rotação).
#pragma once
#include <Arduino.h>
#include <WebServer.h>

enum NivelLog : uint8_t { LOG_INFO, LOG_AVISO, LOG_ERRO };

bool iniciarLog();       // monta o sistema de arquivos e cria a fila; false se a flash falhar
void registrar(NivelLog nivel, const char* formato, ...);  // estilo printf; seguro entre tarefas
void processarLog();     // chamar na tarefa principal: grava a fila na flash

bool relogioAjustado();                          // true quando a data/hora é válida
void ajustarRelogio(time_t epoch, const char* origem);  // ex.: origem = "navegador"
void escreverDataHora(char* destino, size_t tamanho);   // "2026-11-11 14:03:22" ou "sem hora"
uint32_t numeroBoot();                           // quantas vezes a placa já ligou

// GET /log: envia as últimas `linhas` linhas (ou os dois arquivos inteiros se completo).
void enviarLog(WebServer& servidor, uint32_t linhas, bool completo);
