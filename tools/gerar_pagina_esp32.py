"""gerar_pagina_esp32.py — Embute o dashboard (src/client) no firmware do ESP32.

Por quê: a interface precisa ser servida PELA PLACA. Abrindo http://192.168.4.1/
no celular ou no PC, a página vem da memória flash do ESP32; com a placa
desligada, não há página.

O que faz:
  1. Junta index.html + style.css + app.js num único HTML (CSS e JS embutidos),
     para o navegador fazer UM pedido só (o WebServer atende um cliente por vez).
  2. Comprime com gzip (~4x menor: menos tempo ocupando o servidor).
  3. Gera src/esp32/esp32_server/pagina_web.h com os bytes num array em flash.

Uso (depois de QUALQUER mudança em src/client, antes de compilar o firmware):
    python tools/gerar_pagina_esp32.py
"""
import gzip
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PASTA_CLIENTE = RAIZ / "src" / "client"
SAIDA = RAIZ / "src" / "esp32" / "esp32_server" / "pagina_web.h"


def montar_pagina():
    """Devolve o HTML final (bytes) com o CSS e o JS embutidos."""
    html = (PASTA_CLIENTE / "index.html").read_text(encoding="utf-8")
    css = (PASTA_CLIENTE / "style.css").read_text(encoding="utf-8")
    js = (PASTA_CLIENTE / "app.js").read_text(encoding="utf-8")
    tag_css = '<link rel="stylesheet" href="style.css">'
    tag_js = '<script src="app.js"></script>'
    assert tag_css in html and tag_js in html, "index.html mudou: ajuste as tags procuradas"
    assert "</script" not in js and "</style" not in css, "texto que fecharia a tag antes da hora"
    html = html.replace(tag_css, f"<style>\n{css}\n</style>").replace(tag_js, f"<script>\n{js}\n</script>")
    return html.encode("utf-8")


def main():
    pagina = montar_pagina()
    # mtime=0: o mesmo conteúdo gera sempre os mesmos bytes (diff limpo no git).
    comprimida = gzip.compress(pagina, compresslevel=9, mtime=0)
    linhas = [", ".join(f"0x{b:02x}" for b in comprimida[i:i + 16]) for i in range(0, len(comprimida), 16)]
    SAIDA.write_text(
        "// pagina_web.h — GERADO por tools/gerar_pagina_esp32.py. NÃO edite à mão:\n"
        "// mude src/client/ e rode o gerador de novo.\n"
        f"// Dashboard completo (HTML+CSS+JS), gzip: {len(pagina)} -> {len(comprimida)} bytes.\n"
        "#pragma once\n#include <Arduino.h>\n\n"
        f"const size_t PAGINA_GZ_TAM = {len(comprimida)};\n"
        "const uint8_t PAGINA_GZ[] PROGMEM = {\n  " + ",\n  ".join(linhas) + "\n};\n",
        encoding="utf-8")
    print(f"Página: {len(pagina)} bytes -> gzip {len(comprimida)} bytes -> {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
