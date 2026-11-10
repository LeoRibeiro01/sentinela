@echo off
rem iniciar_ia.bat - Duplo clique: sobe o servico de IA e abre o dashboard (servido pelo ESP32).
rem Uso opcional: iniciar_ia.bat 127.0.0.1:8080   (endereco do ESP32; padrao 192.168.4.1)
rem Para encerrar, feche esta janela (ou Ctrl+C).
cd /d "%~dp0.."
set ESP32=%1
if "%ESP32%"=="" set ESP32=192.168.4.1
if not exist ".venv\Scripts\python.exe" (
  echo ERRO: ambiente .venv nao encontrado. Veja a secao "Servico de IA" do README.
  pause
  exit /b 1
)
echo Iniciando o servico de IA (ESP32 em %ESP32%)... o navegador abre em alguns segundos.
start "" /b cmd /c "timeout /t 12 /nobreak >nul & start http://%ESP32%/"
".venv\Scripts\python.exe" src\ai\server.py --esp32 %ESP32%
pause
