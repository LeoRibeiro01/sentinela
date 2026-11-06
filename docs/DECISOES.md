# Decisões técnicas das Fases 0 e 1

- A rede usa modo Access Point fixo em `192.168.4.1`; isso evita isolamento de clientes de redes compartilhadas e não depende de internet.
- A amostragem usa timer de hardware e tarefa FreeRTOS no núcleo 1. O Wi-Fi e o servidor permanecem no fluxo principal, sem `delay()` para marcar amostras.
- O MAX9814 fica no ADC1 (GPIO 34), com 12 bits e atenuação de 11 dB. O nível DC é acompanhado por filtro simples e removido antes do RMS e do WAV.
- O buffer circular guarda até 2 s em PCM16 (64 KiB). O WAV é montado em blocos de 512 bytes durante o envio, sem duplicar o buffer nem suspender a captura.
- GPIO 16/17/18 atendem os atuadores externos. GPIO 2 espelha o alerta para o teste sem atuadores.
- `nivel` usa RMS relativo e não pretende ser uma medida acústica calibrada.
- O FQBN e APIs de timer foram escolhidos para ESP32 Arduino core 2.0.17, conforme o ambiente da disciplina.
