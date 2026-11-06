// Teste simples do módulo MAX9814 ligado ao GPIO 34, antes de ativar o Wi-Fi.
// O valor bruto deve variar ao falar ou bater palmas perto do microfone.
static const uint8_t PINO_MICROFONE = 34;

void setup() {
  Serial.begin(115200);
  analogReadResolution(12);
  analogSetPinAttenuation(PINO_MICROFONE, ADC_11db);
  Serial.println("Teste do microfone MAX9814 no GPIO 34");
}

void loop() {
  Serial.println(analogRead(PINO_MICROFONE));
  delay(10);
}
