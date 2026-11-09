"""train.py — Treina os dois classificadores do SENTINELA sobre embeddings do YAMNet.

  1. Porteiro: "isto é som de carro?"  (carro × nao_carro)
  2. Diagnóstico: normal / falha_batida_pino / falha_ignicao / falha_outros

Fluxo:
  data/train/manifest.csv -> YAMNet (quadros de 0,96 s, passo 0,48 s) -> embedding
  de 1024 números por quadro -> StandardScaler + LogisticRegression.
  A previsão de um trecho é a MÉDIA das probabilidades dos seus quadros.

Cuidados contra resultado enganoso:
  - divisão treino/validação/teste por GRAVAÇÃO (feita em prepare_dataset.py);
  - pesos balanceados por (classe, fonte): cada dataset pesa igual dentro de cada
    classe. Sem isso o modelo aprende "qual dataset é este" em vez de "que som é
    este" (aconteceu na 1ª versão: o porteiro rejeitava todo carro do amrrashed,
    porque todos os negativos vinham de lá);
  - C e o limiar de confiança são escolhidos na VALIDAÇÃO; o teste só é usado no fim;
  - o modelo final é treinado em treino+validação e avaliado no teste;
  - cada trecho de treino ganha uma cópia "aumentada" (alto-falante + ruído).

Saídas: models/classificador.joblib, models/classes.json, docs/metricas_ia.md
Uso:    python src/ai/train.py
"""
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analise import LIMIAR_PORTEIRO, veto_yamnet  # noqa: E402
from audio_util import RMS_MINIMO_FRAME, aumentar, carregar, simular_captura  # noqa: E402
from yamnet_util import Yamnet  # noqa: E402

RAIZ = Path(__file__).resolve().parents[2]
PASTA_TREINO = RAIZ / "data" / "train"
CACHE = RAIZ / "data" / "cache" / "embeddings_v2.npz"
PASTA_MODELOS = RAIZ / "models"
DOC_METRICAS = RAIZ / "docs" / "metricas_ia.md"
VALORES_C = [0.01, 0.1, 1.0]
SEMENTE = 42
JANELA, PASSO = 15360, 7680  # 0,96 s e 0,48 s em amostras (iguais aos do YAMNet)


def quadros_validos(sinal, n_quadros):
    """Máscara dos quadros do YAMNet com energia suficiente (descarta pausas/silêncio)."""
    mascara = np.zeros(n_quadros, dtype=bool)
    for i in range(n_quadros):
        trecho = sinal[i * PASSO:i * PASSO + JANELA]
        mascara[i] = len(trecho) > 0 and np.sqrt(np.mean(trecho ** 2)) >= RMS_MINIMO_FRAME
    if not mascara.any():
        mascara[:] = True  # trecho todo baixo: mantém, para não sumir com o clipe
    return mascara


def extrair_embeddings(linhas, yamnet):
    """Embeddings e média dos scores YAMNet de cada trecho (e da versão aumentada no treino)."""
    cache = np.load(CACHE, allow_pickle=True)["cache"].item() if CACHE.exists() else {}
    rng = np.random.default_rng(SEMENTE)
    novos, inicio = 0, time.time()
    for i, linha in enumerate(linhas, 1):
        chaves = [linha["arquivo"]] + ([linha["arquivo"] + "|aum"] if linha["split"] == "train" else [])
        if all(c in cache for c in chaves):
            continue
        sinal = carregar(PASTA_TREINO / linha["arquivo"])
        for chave in chaves:
            entrada = aumentar(sinal, rng) if chave.endswith("|aum") else sinal
            scores, emb = yamnet.analisar(entrada)
            mascara = quadros_validos(entrada, len(emb))
            cache[chave] = {"emb": emb[mascara].astype(np.float16),
                            "scores": scores[mascara].mean(axis=0).astype(np.float16)}
            novos += 1
        if i % 200 == 0:
            print(f"  {i}/{len(linhas)} trechos ({time.time() - inicio:.0f} s)")
    if novos:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(CACHE, cache=np.array(cache, dtype=object))
    return cache


def montar(linhas, cache, classes, splits, rotulo, com_aumento):
    """Quadros (X), rótulo (y), trecho de origem e peso de cada quadro.

    Peso: cada classe pesa igual no total. Dentro da classe, cada fonte pesa
    proporcional à RAIZ QUADRADA do seu tamanho: uma fonte grande não abafa a
    pequena, mas uma fonte com 1 trecho também não vale tanto quanto 700.
    """
    X, y, trecho, celula = [], [], [], []
    for linha in linhas:
        if linha["split"] not in splits or rotulo(linha) is None:
            continue
        chaves = [linha["arquivo"]] + ([linha["arquivo"] + "|aum"] if com_aumento and linha["split"] == "train" else [])
        for chave in chaves:
            emb = cache[chave]["emb"].astype(np.float32)
            X.append(emb)
            y += [classes.index(rotulo(linha))] * len(emb)
            trecho += [chave] * len(emb)
            celula += [(rotulo(linha), linha["fonte"])] * len(emb)
    n_celula = Counter(celula)
    soma_raizes = Counter()
    for (c, f), n in n_celula.items():
        soma_raizes[c] += np.sqrt(n)
    total = len(celula)
    # parcela da fonte na classe = raiz(n) / soma das raízes; cada classe soma total/n_classes
    pesos = np.array([total / len(classes) * (np.sqrt(n_celula[(c, f)]) / soma_raizes[c]) / n_celula[(c, f)]
                      for c, f in celula])
    return np.vstack(X), np.array(y), np.array(trecho), pesos


def prever_trechos(modelo, X, trecho):
    """Probabilidade por trecho = média das probabilidades dos seus quadros."""
    probs = modelo.predict_proba(X)
    por_trecho = defaultdict(list)
    for p, t in zip(probs, trecho):
        por_trecho[t].append(p)
    return {t: np.mean(v, axis=0) for t, v in por_trecho.items()}


def avaliar(probs_trecho, por_arquivo, classes, rotulo):
    chaves = list(probs_trecho)
    verdade = np.array([classes.index(rotulo(por_arquivo[k])) for k in chaves])
    previsto = np.array([int(np.argmax(probs_trecho[k])) for k in chaves])
    confianca = np.array([float(np.max(probs_trecho[k])) for k in chaves])
    return verdade, previsto, confianca, chaves


def treinar(C, X, y, pesos):
    modelo = make_pipeline(StandardScaler(), LogisticRegression(C=C, max_iter=3000, random_state=SEMENTE))
    return modelo.fit(X, y, logisticregression__sample_weight=pesos)


def escolher_e_treinar(nome, linhas, cache, classes, rotulo, por_arquivo, relatorio):
    """Escolhe C pela F1-macro de validação; devolve o modelo final e as previsões de validação/teste."""
    X_tr, y_tr, _, w_tr = montar(linhas, cache, classes, {"train"}, rotulo, True)
    X_va, _, t_va, _ = montar(linhas, cache, classes, {"validation"}, rotulo, False)
    print(f"\n[{nome}] {len(X_tr)} quadros de treino, {len(X_va)} de validação")
    resultados = []
    for C in VALORES_C:
        modelo = treinar(C, X_tr, y_tr, w_tr)
        probs_va = prever_trechos(modelo, X_va, t_va)
        v, p, _, _ = avaliar(probs_va, por_arquivo, classes, rotulo)
        f1 = f1_score(v, p, average="macro")
        resultados.append((f1, C, modelo))
        print(f"  C={C:<5} F1-macro validação = {f1:.3f}")
        relatorio.append(f"| {nome} | C = {C} | {f1:.3f} |")
    _, C, modelo_validacao = max(resultados, key=lambda r: r[0])
    X_fin, y_fin, _, w_fin = montar(linhas, cache, classes, {"train", "validation"}, rotulo, True)
    modelo = treinar(C, X_fin, y_fin, w_fin)
    X_te, _, t_te, _ = montar(linhas, cache, classes, {"test"}, rotulo, False)
    return modelo, C, modelo_validacao, prever_trechos(modelo, X_te, t_te)


def prever_grupos_5s(modelo, linhas, cache, classes, split, rotulo):
    """Simula o botão DIAGNOSTICAR: média de 10 quadros consecutivos (≈ 5 janelas de 1 s)."""
    verdade, previsto, confianca = [], [], []
    for linha in linhas:
        if linha["split"] != split or rotulo(linha) is None:
            continue
        probs = modelo.predict_proba(cache[linha["arquivo"]]["emb"].astype(np.float32))
        for i in range(0, max(1, len(probs) - 9), 10):
            media = probs[i:i + 10].mean(axis=0)
            verdade.append(classes.index(rotulo(linha)))
            previsto.append(int(np.argmax(media)))
            confianca.append(float(np.max(media)))
    return np.array(verdade), np.array(previsto), np.array(confianca)


def avaliar_degradado(diag, porteiro, linhas, yamnet, classes, rotulo):
    """Teste de robustez: trechos de teste degradados (celular + MAX9814 + 12 bits), em grupos de 5 s."""
    rng = np.random.default_rng(7)
    verdade, previsto, confianca, carro = [], [], [], []
    for linha in linhas:
        if linha["split"] != "test" or rotulo(linha) is None:
            continue
        sinal = simular_captura(carregar(PASTA_TREINO / linha["arquivo"]), rng)
        for i in range(0, max(1, len(sinal) - 80000 + 1), 80000):  # pedaços de 5 s, como o botão
            _, emb = yamnet.analisar(sinal[i:i + 80000])
            media = diag.predict_proba(emb).mean(axis=0)
            verdade.append(classes.index(rotulo(linha)))
            previsto.append(int(np.argmax(media)))
            confianca.append(float(np.max(media)))
            carro.append(float(porteiro.predict_proba(emb).mean(axis=0)[0]))
    return np.array(verdade), np.array(previsto), np.array(confianca), np.array(carro)


def escolher_limiar(v, p, conf):
    """Menor limiar (≥ 50%) cuja acurácia nos trechos respondidos seja ≥ 90% respondendo ≥ 60% deles."""
    for limiar in range(50, 91, 5):
        sel = conf * 100 >= limiar
        if sel.mean() >= 0.6 and (v[sel] == p[sel]).mean() >= 0.9:
            return limiar
    return 60


def curva_limiar(v, p, conf):
    linhas = ["| limiar | trechos respondidos | acurácia nos respondidos |", "|---:|---:|---:|"]
    for limiar in range(40, 91, 10):
        sel = conf * 100 >= limiar
        if sel.any():
            linhas.append(f"| {limiar}% | {sel.mean() * 100:.0f}% | {(v[sel] == p[sel]).mean() * 100:.1f}% |")
    return linhas


def tabela_confusao(v, p, classes):
    m = confusion_matrix(v, p, labels=range(len(classes)))
    linhas = ["| real \\ previsto | " + " | ".join(classes) + " |", "|---" * (len(classes) + 1) + "|"]
    for i, c in enumerate(classes):
        linhas.append(f"| **{c}** | " + " | ".join(str(x) for x in m[i]) + " |")
    return linhas


def tabela_classes(v, p, classes):
    prec, rec, f1, sup = precision_recall_fscore_support(v, p, labels=range(len(classes)), zero_division=0)
    linhas = ["| classe | precisão | revocação | F1 | trechos |", "|---|---:|---:|---:|---:|"]
    for i, c in enumerate(classes):
        linhas.append(f"| {c} | {prec[i]:.2f} | {rec[i]:.2f} | {f1[i]:.2f} | {sup[i]} |")
    return linhas


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config = json.loads((Path(__file__).parent / "fontes.json").read_text(encoding="utf-8"))
    classes = config["classes_diagnostico"]
    nao_carro = config["classe_nao_carro"]
    with open(PASTA_TREINO / "manifest.csv", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    por_arquivo = {l["arquivo"]: l for l in linhas}
    print(f"{len(linhas)} trechos no manifesto. Carregando YAMNet...")
    yamnet = Yamnet()
    cache = extrair_embeddings(linhas, yamnet)

    md = ["# Métricas da IA", "", f"Gerado por `src/ai/train.py` em {time.strftime('%d/%m/%Y %H:%M')}. "
          "Avaliação por **trecho** (média das probabilidades dos quadros de 0,96 s) no conjunto de **teste**, "
          "separado por gravação e nunca usado para escolher hiperparâmetros ou limiares.", ""]
    contagem = Counter((l["classe"], l["split"]) for l in linhas)
    md += ["## Dados (trechos de até 10 s)", "", "| classe | treino | validação | teste | real_test | fontes |",
           "|---|---:|---:|---:|---:|---|"]
    for c in classes + config.get("classes_somente_porteiro", []) + [nao_carro]:
        fontes = ", ".join(sorted({l["fonte"] for l in linhas if l["classe"] == c}))
        md.append(f"| {c} | " + " | ".join(str(contagem[(c, s)]) for s in
                                            ["train", "validation", "test", "real_test"]) + f" | {fontes} |")
    md += ["", "Treino usa também uma cópia aumentada de cada trecho (passa-faixa 150–6000 Hz + ruído, SNR 15–30 dB). "
           "Pesos balanceados por classe e, dentro da classe, pela raiz do tamanho de cada fonte. "
           "`falha_outros` (falhas mecânicas variadas, ~4 min) só ensina o porteiro: é pouco para virar diagnóstico.", ""]
    escolha = ["## Escolha do hiperparâmetro C (F1-macro na validação)", "", "| modelo | valor | F1 |", "|---|---|---:|"]

    # ---- 1. Porteiro: carro × nao_carro ----
    classes_porteiro = ["carro", nao_carro]
    rot_porteiro = lambda l: nao_carro if l["classe"] == nao_carro else "carro"  # noqa: E731
    # (classes_somente_porteiro, como falha_outros, entram aqui como "carro")
    porteiro, C_p, _, probs_p = escolher_e_treinar("porteiro", linhas, cache, classes_porteiro, rot_porteiro,
                                                   por_arquivo, escolha)
    v, p, _, chaves_p = avaliar(probs_p, por_arquivo, classes_porteiro, rot_porteiro)

    # Decisão completa como roda ao vivo: porteiro + veto do YAMNet (fala, música, animais...).
    def e_carro(chave):
        resumo = yamnet.resumo_da_media(cache[chave]["scores"].astype(np.float32))
        return probs_p[chave][0] >= LIMIAR_PORTEIRO and not veto_yamnet(resumo)
    p_veto = np.array([0 if e_carro(k) else 1 for k in chaves_p])
    acc_p, acc_pv = (v == p).mean(), (v == p_veto).mean()
    por_fonte = defaultdict(lambda: [0, 0, 0])
    for k, real, so_p, com_veto in zip(chaves_p, v, p, p_veto):
        linha = por_arquivo[k]
        celula = por_fonte[(linha["classe"], linha["fonte"])]
        celula[0] += 1; celula[1] += int(so_p == real); celula[2] += int(com_veto == real)
    print(f"[porteiro] teste: acurácia {acc_p:.3f} (com veto YAMNet: {acc_pv:.3f})")

    # ---- 2. Diagnóstico: só trechos de carro ----
    rot_diag = lambda l: l["classe"] if l["classe"] in classes else None  # noqa: E731
    diag, C_d, diag_validacao, probs_d = escolher_e_treinar("diagnóstico", linhas, cache, classes, rot_diag,
                                                      por_arquivo, escolha)
    # Limiar escolhido na validação, no formato real do botão (grupos de ~5 s).
    limiar = escolher_limiar(*prever_grupos_5s(diag_validacao, linhas, cache, classes, "validation", rot_diag))
    g_v, g_p, g_c = prever_grupos_5s(diag, linhas, cache, classes, "test", rot_diag)
    vd, pd, conf, chaves_d = avaliar(probs_d, por_arquivo, classes, rot_diag)
    acc_d, f1_d = (vd == pd).mean(), f1_score(vd, pd, average="macro")
    print(f"[diagnóstico] teste: acurácia {acc_d:.3f}, F1-macro {f1_d:.3f}; limiar escolhido na validação: {limiar}%")

    i_normal = classes.index("normal")
    vb, pb = (vd != i_normal).astype(int), (pd != i_normal).astype(int)
    prec_b, rec_b, f1_b, _ = precision_recall_fscore_support(vb, pb, average="binary", zero_division=0)
    sel = g_c * 100 >= limiar
    diag_fonte = defaultdict(lambda: [0, 0])
    for k, real, prev in zip(chaves_d, vd, pd):
        celula = diag_fonte[(por_arquivo[k]["classe"], por_arquivo[k]["fonte"])]
        celula[0] += 1; celula[1] += int(real == prev)

    # Knock real (AudioSet) nunca usado no treino: o modelo reconhece knock de verdade?
    X_rt, _, t_rt, _ = montar(linhas, cache, classes, {"real_test"}, rot_diag, False)
    rt = prever_trechos(diag, X_rt, t_rt) if len(X_rt) else {}
    i_knock = classes.index("falha_batida_pino")
    rt_knock = np.mean([np.argmax(q) == i_knock for q in rt.values()]) if rt else float("nan")
    rt_falha = np.mean([np.argmax(q) != i_normal for q in rt.values()]) if rt else float("nan")
    rt_carro = np.mean([porteiro.predict_proba(cache[t]["emb"].astype(np.float32)).mean(axis=0)[0] >= 0.5
                        for t in rt]) if rt else float("nan")

    d_v, d_p, d_c, d_carro = avaliar_degradado(diag, porteiro, linhas, yamnet, classes, rot_diag)
    d_sel = d_c * 100 >= limiar
    print(f"[robustez] áudio degradado: acurácia {(d_v == d_p).mean():.3f}; porteiro aceita {(d_carro >= 0.5).mean():.3f}")

    PASTA_MODELOS.mkdir(exist_ok=True)
    pacote = {"versao": 2, "classes": classes, "diagnostico": diag, "porteiro": porteiro,
              "classes_porteiro": classes_porteiro, "limiar_confianca": limiar,
              "treinado_em": time.strftime("%Y-%m-%d %H:%M")}
    joblib.dump(pacote, PASTA_MODELOS / "classificador.joblib", compress=3)
    (PASTA_MODELOS / "classes.json").write_text(json.dumps(
        {"classes": classes, "porteiro": classes_porteiro, "limiar_confianca": limiar,
         "treinado_em": pacote["treinado_em"]}, ensure_ascii=False, indent=2), encoding="utf-8")

    md += escolha + [""]
    md += ["## 1. Porteiro: é som de carro?", "",
           f"C escolhido: {C_p}. **Acurácia no teste: {acc_p * 100:.1f}%** só com o classificador; "
           f"**{acc_pv * 100:.1f}%** com o veto do YAMNet (fala, música, animais, chuva...), que é como roda ao vivo.", ""]
    md += tabela_classes(v, p, classes_porteiro) + [""] + tabela_confusao(v, p, classes_porteiro) + [""]
    md += ["Acertos por classe e fonte (teste):", "", "| classe | fonte | trechos | só porteiro | porteiro + veto |",
           "|---|---|---:|---:|---:|"]
    for (c, f), (n, a1, a2) in sorted(por_fonte.items()):
        md.append(f"| {c} | {f} | {n} | {a1 / n * 100:.0f}% | {a2 / n * 100:.0f}% |")
    md += ["", "Os negativos (`nao_carro`) vêm só do amrrashed (animais, clima, sirenes, tiros, obras). "
           "Fala e música não têm exemplos de treino e dependem do veto do YAMNet.", ""]
    md += [f"## 2. Diagnóstico ({len(classes)} classes)", "",
           f"C escolhido: {C_d}. **Acurácia no teste: {acc_d * 100:.1f}%** · F1-macro: {f1_d:.3f}.", ""]
    md += tabela_classes(vd, pd, classes) + ["", "Matriz de confusão (trechos de teste):", ""]
    md += tabela_confusao(vd, pd, classes) + [""]
    md += ["Acerto por classe e fonte (teste):", "", "| classe | fonte | trechos | acerto |", "|---|---|---:|---:|"]
    for (c, f), (n, a) in sorted(diag_fonte.items()):
        md.append(f"| {c} | {f} | {n} | {a / n * 100:.0f}% |")
    md += ["", "### Normal × falha (o que aciona o alerta)", "",
           f"Precisão {prec_b * 100:.1f}% · revocação {rec_b * 100:.1f}% · F1 {f1_b:.3f}.", ""]
    md += ["### Simulação do botão DIAGNOSTICAR (grupos de ~5 s = 10 quadros)", "",
           f"Acurácia em {len(g_v)} grupos de teste: **{(g_v == g_p).mean() * 100:.1f}%**.", "",
           *tabela_classes(g_v, g_p, classes), "",
           "### Limiar de confiança (\"inconclusivo\")", "", "Curva no teste (grupos de 5 s):", "",
           *curva_limiar(g_v, g_p, g_c), "",
           f"Limiar escolhido **na validação**: **{limiar}%** (menor limiar com ≥ 90% de acerto respondendo ≥ 60% "
           f"dos grupos). No teste ele responde {sel.mean() * 100:.0f}% dos diagnósticos com "
           f"{(g_v[sel] == g_p[sel]).mean() * 100:.1f}% de acerto; o resto vira \"inconclusivo\" "
           "(o sistema não finge certeza). O serviço permite ajustar o limiar.", ""]
    md += ["### Robustez: teste com áudio degradado (simula celular + MAX9814 + ADC de 12 bits)", "",
           "Trechos de teste filtrados em 250–5000 Hz, ruído com SNR de 12 dB, saturação leve e quantização de 12 bits "
           "(degradação mais forte e diferente da usada no aumento de dados do treino), em pedaços de 5 s.", "",
           f"- acurácia: **{(d_v == d_p).mean() * 100:.1f}%** em {len(d_v)} pedaços "
           f"(sem degradação: {(g_v == g_p).mean() * 100:.1f}%)",
           f"- com o limiar de {limiar}%: responde {d_sel.mean() * 100:.0f}% com "
           f"{(d_v[d_sel] == d_p[d_sel]).mean() * 100 if d_sel.any() else 0:.1f}% de acerto",
           f"- porteiro reconhece como carro: {(d_carro >= 0.5).mean() * 100:.1f}%", "",
           *tabela_confusao(d_v, d_p, classes), ""]
    md += ["### Knock real nunca visto (`real_test`, 38 clipes do AudioSet)", "",
           f"- classificado como `falha_batida_pino`: **{rt_knock * 100:.1f}%**",
           f"- classificado como alguma falha (alerta acionado): {rt_falha * 100:.1f}%",
           f"- reconhecido como carro pelo porteiro: {rt_carro * 100:.1f}%", ""]
    md += ["## Leitura honesta", "",
           "- Os dados vêm de gravações da internet, e parte do knock/normal é **sintética** (Revix). O áudio captado "
           "pelo MAX9814 a partir de um alto-falante é diferente: **espere desempenho menor ao vivo**.",
           "- `falha_ignicao` vem praticamente de uma única fonte (16 trechos de teste): o 100% de revocação é "
           "promissor, mas a amostra é pequena.",
           "- Falhas mecânicas variadas (rolamento, correia, escapamento...) **não** são diagnosticadas: só há ~4 min "
           "de áudio delas, de 29 gravações diferentes. Elas ensinam o porteiro (\"é carro\") e são trabalho futuro.",
           "- Os WAVs segmentados do dataset amrrashed estão corrompidos (ruído branco); usamos as gravações originais.",
           "- A melhoria mais eficaz é gravar com `record.py` (som tocado no alto-falante e captado pelo próprio "
           "MAX9814) e retreinar.",
           "- As porcentagens são probabilidade estimada pelo modelo, não certeza.", ""]
    DOC_METRICAS.write_text("\n".join(md), encoding="utf-8")
    print(f"\nModelo salvo em {PASTA_MODELOS / 'classificador.joblib'}; métricas em {DOC_METRICAS}")


if __name__ == "__main__":
    main()
