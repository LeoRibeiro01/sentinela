"""gerar_relatorio_docx.py — Converte docs/RELATORIO_TDE.md em .docx com formatação ABNT.

Formatação aplicada (NBR 14724): papel A4; margens superior/esquerda 3 cm e
inferior/direita 2 cm; Times New Roman 12; espaçamento 1,5; recuo de 1,25 cm na
primeira linha dos parágrafos; títulos de seção em negrito (primários em
maiúsculas, cada um começando em página nova); capa e folha de rosto centralizadas;
quadros e citações longas em fonte 10 e espaço simples; referências em espaço
simples, alinhadas à esquerda, separadas por uma linha em branco; números de
página no canto superior direito.

Entende só o Markdown usado no relatório: títulos (#, ##), parágrafos, listas
(- ou a)), tabelas, imagens ![](arquivo) e **negrito**.

Uso:   .venv\\Scripts\\python tools\\gerar_relatorio_docx.py
Saída: docs/RELATORIO_TDE.docx  (requer: pip install python-docx)
"""
import re
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

RAIZ = Path(__file__).resolve().parents[1]
ENTRADA = RAIZ / "docs" / "RELATORIO_TDE.md"
SAIDA = RAIZ / "docs" / "RELATORIO_TDE.docx"
SECOES_CENTRALIZADAS = {"CAPA", "FOLHA DE ROSTO"}  # títulos que não aparecem: só o conteúdo centralizado


def adicionar_texto(paragrafo, texto, tamanho=12):
    """Escreve `texto` no parágrafo tratando **negrito**, *itálico* e `código`."""
    texto = texto.replace("`", "")
    for parte in re.split(r"(\*\*[^*]+\*\*|\*[^*]+\*)", texto):
        if not parte:
            continue
        negrito = parte.startswith("**") and parte.endswith("**")
        italico = not negrito and parte.startswith("*") and parte.endswith("*") and len(parte) > 2
        conteudo = parte.strip("*") if (negrito or italico) else parte
        run = paragrafo.add_run(conteudo)
        run.bold = negrito
        run.italic = italico
        run.font.size = Pt(tamanho)


def formatar(paragrafo, recuo=True, alinhamento=WD_ALIGN_PARAGRAPH.JUSTIFY, espaco=1.5, depois=0):
    f = paragrafo.paragraph_format
    f.first_line_indent = Cm(1.25) if recuo else Cm(0)
    f.line_spacing = espaco
    f.space_after = Pt(depois)
    f.space_before = Pt(0)
    paragrafo.alignment = alinhamento


def numero_de_pagina(secao):
    """Campo PAGE no cabeçalho, à direita (ABNT: canto superior direito)."""
    p = secao.header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    run = p.add_run()
    for tipo, texto in (("begin", None), (None, "PAGE"), ("end", None)):
        if tipo:
            elemento = OxmlElement("w:fldChar")
            elemento.set(qn("w:fldCharType"), tipo)
        else:
            elemento = OxmlElement("w:instrText")
            elemento.set(qn("xml:space"), "preserve")
            elemento.text = texto
        run._r.append(elemento)
    run.font.size = Pt(10)


def tabela(documento, linhas):
    """Tabela Markdown -> tabela do Word (fonte 10, espaço simples, cabeçalho em negrito)."""
    celulas = [[c.strip() for c in linha.strip().strip("|").split("|")] for linha in linhas]
    celulas = [c for c in celulas if not all(re.fullmatch(r":?-{3,}:?", x) for x in c)]
    t = documento.add_table(rows=len(celulas), cols=len(celulas[0]))
    t.style = "Table Grid"
    for i, linha in enumerate(celulas):
        for j, valor in enumerate(linha[: len(celulas[0])]):
            p = t.cell(i, j).paragraphs[0]
            adicionar_texto(p, f"**{valor}**" if i == 0 and not valor.startswith("**") else valor, 10)
            formatar(p, recuo=False, alinhamento=WD_ALIGN_PARAGRAPH.LEFT, espaco=1.0)


def main():
    linhas = ENTRADA.read_text(encoding="utf-8").splitlines()
    doc = Document()
    estilo = doc.styles["Normal"]
    estilo.font.name = "Times New Roman"
    estilo.element.rPr.rFonts.set(qn("w:eastAsia"), "Times New Roman")
    estilo.font.size = Pt(12)
    secao = doc.sections[0]
    secao.page_height, secao.page_width = Cm(29.7), Cm(21.0)
    secao.top_margin, secao.left_margin = Cm(3), Cm(3)
    secao.bottom_margin, secao.right_margin = Cm(2), Cm(2)

    secao_atual = ""
    em_comentario = False
    nas_referencias = False
    i = 0
    primeira_secao = True
    while i < len(linhas):
        linha = linhas[i].rstrip()
        if linha.startswith("<!--"):
            em_comentario = True
        if em_comentario:
            em_comentario = "-->" not in linha
            i += 1
            continue

        if linha.startswith("# "):  # seção primária: sempre em página nova
            titulo = linha[2:].strip()
            if not primeira_secao:
                doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
            primeira_secao = False
            secao_atual = titulo
            nas_referencias = titulo == "REFERÊNCIAS"
            if titulo == "RESUMO":  # a numeração de páginas começa a aparecer aqui
                nova = doc.add_section(WD_SECTION.CONTINUOUS)
                nova.header.is_linked_to_previous = False
                numero_de_pagina(nova)
            if titulo not in SECOES_CENTRALIZADAS:
                p = doc.add_paragraph()
                adicionar_texto(p, f"**{titulo.upper()}**")
                centralizado = titulo in ("RESUMO", "REFERÊNCIAS")
                formatar(p, recuo=False, alinhamento=WD_ALIGN_PARAGRAPH.CENTER if centralizado else WD_ALIGN_PARAGRAPH.LEFT, depois=12)
            i += 1
            continue
        if linha.startswith("## "):
            p = doc.add_paragraph()
            adicionar_texto(p, f"**{linha[3:].strip()}**")
            formatar(p, recuo=False, alinhamento=WD_ALIGN_PARAGRAPH.LEFT, depois=6)
            p.paragraph_format.space_before = Pt(12)
            i += 1
            continue
        if linha.startswith("|"):
            bloco = []
            while i < len(linhas) and linhas[i].startswith("|"):
                bloco.append(linhas[i])
                i += 1
            tabela(doc, bloco)
            continue
        imagem = re.match(r"!\[[^\]]*\]\(([^)]+)\)", linha)
        if imagem:
            arquivo = (ENTRADA.parent / imagem.group(1)).resolve()
            if arquivo.exists():
                doc.add_picture(str(arquivo), width=Cm(15))
                doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue
        if not linha.strip():
            i += 1
            continue

        p = doc.add_paragraph()
        if secao_atual in SECOES_CENTRALIZADAS:
            adicionar_texto(p, linha)
            formatar(p, recuo=False, alinhamento=WD_ALIGN_PARAGRAPH.CENTER, depois=6)
        elif nas_referencias:
            adicionar_texto(p, linha)
            formatar(p, recuo=False, alinhamento=WD_ALIGN_PARAGRAPH.LEFT, espaco=1.0, depois=12)
        elif linha.startswith("- "):
            adicionar_texto(p, "– " + linha[2:])
            formatar(p, recuo=False)
            p.paragraph_format.left_indent = Cm(1.25)
        elif re.match(r"^[a-z]\) ", linha):
            adicionar_texto(p, linha)
            formatar(p, recuo=False)
            p.paragraph_format.left_indent = Cm(1.25)
        elif re.match(r"^\d+\. ", linha):
            adicionar_texto(p, linha)
            formatar(p, recuo=False)
            p.paragraph_format.left_indent = Cm(1.25)
        elif linha.startswith("**Quadro") or linha.startswith("**Figura") or linha.startswith("Fonte:"):
            # Legendas: título acima do quadro/figura e fonte abaixo, em fonte 10.
            adicionar_texto(p, linha, 10)
            formatar(p, recuo=False, alinhamento=WD_ALIGN_PARAGRAPH.CENTER if not linha.startswith("Fonte") else WD_ALIGN_PARAGRAPH.LEFT, espaco=1.0, depois=6)
        else:
            adicionar_texto(p, linha)
            formatar(p)
        i += 1

    doc.save(SAIDA)
    print(f"Gerado: {SAIDA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()
