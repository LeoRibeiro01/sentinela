// rede.cpp — Implementação da conectividade Wi-Fi (ver rede.h).
#include "rede.h"
#include <WiFi.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include "registro_log.h"

static const char* SSID_AP = "SENTINELA";
static const char* SENHA_AP = "sentinela123";
static const IPAddress IP_AP(192, 168, 4, 1);
static const IPAddress MASCARA_AP(255, 255, 255, 0);
static const char* NOME_MDNS = "sentinela";  // http://sentinela.local/
static constexpr uint32_t INTERVALO_RECONEXAO_MS = 15000;

static char ssidSta[33] = "";
static char senhaSta[65] = "";
static volatile bool conectado = false;
static volatile uint32_t quedaMs = 0;       // quando a conexão caiu (0 = nunca caiu)
static uint32_t ultimaTentativaMs = 0;
static uint32_t tentativas = 0;

// Eventos do Wi-Fi rodam na tarefa de eventos do sistema: aqui só se registra no log
// (registrar() é seguro entre tarefas) e se atualizam flags simples.
static void aoEventoWifi(arduino_event_id_t evento, arduino_event_info_t info) {
  switch (evento) {
    case ARDUINO_EVENT_WIFI_STA_GOT_IP: {
      conectado = true;
      tentativas = 0;
      String ip = IPAddress(info.got_ip.ip_info.ip.addr).toString();
      if (quedaMs)
        registrar(LOG_INFO, "Wi-Fi RECONECTADO a \"%s\" após %lu s: IP %s", ssidSta,
                  (unsigned long)((millis() - quedaMs) / 1000), ip.c_str());
      else
        registrar(LOG_INFO, "Wi-Fi conectado a \"%s\": IP %s, sinal %d dBm", ssidSta, ip.c_str(), WiFi.RSSI());
      quedaMs = 0;
      break;
    }
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      if (conectado) {  // só a transição conectado -> desconectado vira registro
        conectado = false;
        quedaMs = millis();
        registrar(LOG_AVISO, "Conexão Wi-Fi com \"%s\" PERDIDA (motivo %u); reconectando",
                  ssidSta, info.wifi_sta_disconnected.reason);
      }
      break;
    case ARDUINO_EVENT_WIFI_AP_STACONNECTED: {
      const uint8_t* m = info.wifi_ap_staconnected.mac;
      registrar(LOG_INFO, "Cliente entrou na rede SENTINELA (MAC %02X:%02X:%02X:%02X:%02X:%02X)",
                m[0], m[1], m[2], m[3], m[4], m[5]);
      break;
    }
    case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED: {
      const uint8_t* m = info.wifi_ap_stadisconnected.mac;
      registrar(LOG_INFO, "Cliente saiu da rede SENTINELA (MAC %02X:%02X:%02X:%02X:%02X:%02X)",
                m[0], m[1], m[2], m[3], m[4], m[5]);
      break;
    }
    default:
      break;
  }
}

static void conectarEstacao() {
  ultimaTentativaMs = millis();
  tentativas++;
  WiFi.disconnect(false, false);  // encerra a tentativa anterior, mantendo o AP
  WiFi.begin(ssidSta, senhaSta);
}

void iniciarRede() {
  Preferences prefs;
  prefs.begin("rede", true);
  prefs.getString("ssid", ssidSta, sizeof(ssidSta));
  prefs.getString("senha", senhaSta, sizeof(senhaSta));
  prefs.end();

  WiFi.persistent(false);  // a rede fica na NOSSA NVS, não na configuração interna do Wi-Fi
  WiFi.onEvent(aoEventoWifi);
  WiFi.mode(ssidSta[0] ? WIFI_AP_STA : WIFI_AP);
  WiFi.softAPConfig(IP_AP, IP_AP, MASCARA_AP);
  // Canal 6, rede visível, até 4 clientes. Se a estação conectar num roteador de outro
  // canal, o AP passa para o canal dele (o rádio é um só).
  if (WiFi.softAP(SSID_AP, SENHA_AP, 6, false, 4))
    registrar(LOG_INFO, "Ponto de acesso \"%s\" ativo: IP %s, MAC %s", SSID_AP,
              WiFi.softAPIP().toString().c_str(), WiFi.softAPmacAddress().c_str());
  else
    registrar(LOG_ERRO, "Falha ao iniciar o ponto de acesso \"%s\"", SSID_AP);
  WiFi.setSleep(false);  // sem economia de energia: menor latência e menos quedas
  WiFi.setAutoReconnect(false);  // a reconexão é feita por processarRede(), com registro no log

  if (ssidSta[0]) {
    registrar(LOG_INFO, "Conectando à rede Wi-Fi \"%s\" (MAC da estação %s)", ssidSta, WiFi.macAddress().c_str());
    conectarEstacao();
  } else {
    registrar(LOG_AVISO, "Nenhuma rede Wi-Fi configurada: só o ponto de acesso está ativo (use /wifi)");
  }

  // Relógio pela internet (fuso de Brasília). Só funciona quando a estação tem internet.
  configTzTime("<-03>3", "pool.ntp.org", "time.google.com");
  if (MDNS.begin(NOME_MDNS)) {
    MDNS.addService("http", "tcp", 80);
  } else {
    registrar(LOG_AVISO, "mDNS não iniciou: use o endereço IP");
  }
}

void processarRede() {
  if (!ssidSta[0] || conectado) return;
  if (millis() - ultimaTentativaMs < INTERVALO_RECONEXAO_MS) return;
  // Não registra cada tentativa (lotaria o log): só a 2ª e depois a cada 20 (~5 min).
  if (tentativas == 1 || tentativas % 20 == 0)
    registrar(LOG_AVISO, "Sem conexão com \"%s\": tentativa %lu (a cada %lu s)", ssidSta,
              (unsigned long)(tentativas + 1), (unsigned long)(INTERVALO_RECONEXAO_MS / 1000));
  conectarEstacao();
}

const char* validarRedeWifi(const String& ssid, const String& senha) {
  if (ssid.length() > 32) return "ssid deve ter no maximo 32 caracteres";
  if (senha.length() > 0 && (senha.length() < 8 || senha.length() > 63))
    return "senha deve ter de 8 a 63 caracteres (ou ser vazia para rede aberta)";
  // Aspas e barras quebrariam o JSON do /status; caracteres de controle não fazem sentido.
  for (size_t i = 0; i < ssid.length(); i++) {
    char c = ssid[i];
    if (c == '"' || c == '\\' || (uint8_t)c < 32) return "ssid contem caractere invalido";
  }
  return nullptr;
}

void configurarRedeWifi(const String& ssid, const String& senha) {
  strlcpy(ssidSta, ssid.c_str(), sizeof(ssidSta));
  strlcpy(senhaSta, senha.c_str(), sizeof(senhaSta));
  Preferences prefs;
  prefs.begin("rede", false);
  prefs.putString("ssid", ssidSta);
  prefs.putString("senha", senhaSta);
  prefs.end();

  conectado = false;
  quedaMs = 0;
  tentativas = 0;
  if (!ssidSta[0]) {
    WiFi.disconnect(false, false);
    WiFi.mode(WIFI_AP);
    registrar(LOG_INFO, "Rede Wi-Fi esquecida: só o ponto de acesso fica ativo");
    return;
  }
  registrar(LOG_INFO, "Nova rede Wi-Fi configurada: \"%s\" (senha não é registrada)", ssidSta);
  WiFi.mode(WIFI_AP_STA);
  conectarEstacao();
}

bool staConectado() { return conectado; }
uint8_t clientesNoAp() { return WiFi.softAPgetStationNum(); }

void escreverIpPrincipal(char* destino, size_t tamanho) {
  IPAddress ip = conectado ? WiFi.localIP() : WiFi.softAPIP();
  snprintf(destino, tamanho, "%u.%u.%u.%u", ip[0], ip[1], ip[2], ip[3]);
}

void escreverJsonRede(char* destino, size_t tamanho) {
  IPAddress ipSta = WiFi.localIP();
  IPAddress ipAp = WiFi.softAPIP();
  snprintf(destino, tamanho,
           "{\"modo\":\"%s\",\"ap_ssid\":\"%s\",\"ap_ip\":\"%u.%u.%u.%u\",\"ap_mac\":\"%s\",\"clientes_ap\":%u,"
           "\"sta_ssid\":\"%s\",\"sta_conectado\":%s,\"sta_ip\":\"%u.%u.%u.%u\",\"sta_mac\":\"%s\","
           "\"rssi\":%d,\"mdns\":\"%s.local\"}",
           ssidSta[0] ? "ap+sta" : "ap", SSID_AP, ipAp[0], ipAp[1], ipAp[2], ipAp[3],
           WiFi.softAPmacAddress().c_str(), WiFi.softAPgetStationNum(), ssidSta, conectado ? "true" : "false",
           conectado ? ipSta[0] : 0, conectado ? ipSta[1] : 0, conectado ? ipSta[2] : 0, conectado ? ipSta[3] : 0,
           WiFi.macAddress().c_str(), conectado ? WiFi.RSSI() : 0, NOME_MDNS);
}
