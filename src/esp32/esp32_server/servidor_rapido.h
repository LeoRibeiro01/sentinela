// servidor_rapido.h — WebServer que não trava com conexões "paradas" de navegadores.
//
// Problema (visto na placa real em 09/11): o WebServer do Arduino atende UM cliente
// por vez e, quando uma conexão é aberta mas não envia o pedido, espera até 5 s
// (HTTP_MAX_DATA_WAIT, fixo na biblioteca). O Chrome abre conexões "de reserva"
// (pré-conexão) que ficam paradas; enquanto isso, todos os outros pedidos ficavam
// na fila e expiravam ou eram derrubados.
//
// Solução: esta subclasse reimplementa só handleClient() (o método é virtual e os
// membros usados são protected na biblioteca). Uma conexão sem pedido é descartada
// após ESPERA_PEDIDO_MS, ou imediatamente se outro cliente estiver esperando.
// O restante (rotas, send, arg) é o WebServer original.
#pragma once
#include <WebServer.h>

class ServidorRapido : public WebServer {
 public:
  static constexpr uint32_t ESPERA_PEDIDO_MS = 300;

  explicit ServidorRapido(int porta) : WebServer(porta) {}

  void handleClient() override {
    if (_currentStatus == HC_NONE) {
      _currentClient = _server.available();
      if (!_currentClient) return;  // ninguém conectado
      _currentStatus = HC_WAIT_READ;
      _statusChange = millis();
    }

    bool manterCliente = false;
    if (_currentClient.connected() && _currentStatus == HC_WAIT_READ) {
      if (_currentClient.available()) {
        // O pedido chegou: mesmo fluxo da biblioteca original.
        if (_parseRequest(_currentClient)) {
          _currentClient.setTimeout(HTTP_MAX_SEND_WAIT / 1000);
          _contentLength = CONTENT_LENGTH_NOT_SET;
          _handleRequest();
        }
      } else {
        // Conexão parada: espera pouco, e nada se já houver outro cliente na fila.
        bool expirou = millis() - _statusChange > ESPERA_PEDIDO_MS;
        manterCliente = !expirou && !_server.hasClient();
      }
    }

    if (!manterCliente) {  // libera para o próximo cliente
      _currentClient = WiFiClient();
      _currentStatus = HC_NONE;
      _currentUpload.reset();
    }
  }
};
