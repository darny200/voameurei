#!/usr/bin/env python3
"""
Gera as páginas de SEO do Baianinho das Passagens a partir do precos.json.

O que ele cria (tudo estático, sem depender de nada além do Python):
  - passagens/{origem}-{destino}/index.html  -> uma página para CADA rota exterior -> Brasil
  - passagens/index.html                      -> lista de todas as rotas, por cidade de origem
  - sitemap.xml                               -> home + /passagens/ + todas as rotas (lastmod = hoje)

Os botões de compra usam o MESMO formato do index.html (função linkCompra):
  Travelpayouts (shmarker 790537.voameurei, promo_id 3791) -> deep link da Kiwi.com.

Rodar:  python3 scripts/gerar_paginas.py
"""
import datetime as dt
import html
import json
import shutil
import unicodedata
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
SITE = "https://voameurei.com"
PASTA = RAIZ / "passagens"
VERIFICACAO = '<meta name="google-site-verification" content="VzCaHKdRFDAxf74clYELchxyOjPEsG1rvAhHsuzMCyM" />'
FUSO_BR = dt.timezone(dt.timedelta(hours=-3))  # horário de Brasília (sem horário de verão)

EUA = ["MIA", "ORL", "NYC", "BOS", "ATL"]
EUROPA = ["LIS", "OPO", "LON", "MAD", "BCN", "ROM", "MIL", "PAR"]
BRASIL = ["BHZ", "SAO", "GYN", "RIO", "SSA", "REC", "FOR", "BSB"]
NOMES = {
    "MIA": "Miami", "ORL": "Orlando", "NYC": "Nova York", "BOS": "Boston", "ATL": "Atlanta",
    "LIS": "Lisboa", "OPO": "Porto", "LON": "Londres", "MAD": "Madri", "BCN": "Barcelona",
    "ROM": "Roma", "MIL": "Milão", "PAR": "Paris",
    "SAO": "São Paulo", "RIO": "Rio de Janeiro", "BHZ": "Belo Horizonte", "GYN": "Goiânia",
    "SSA": "Salvador", "REC": "Recife", "FOR": "Fortaleza", "BSB": "Brasília",
}
# "de Miami" / "do Porto";  "para São Paulo" / "para o Rio de Janeiro"
DE = {"OPO": "do Porto"}
PARA = {"RIO": "para o Rio de Janeiro"}
MOEDAS = {"usd": ("US$", "dólar"), "eur": ("€", "euro"), "gbp": ("£", "libra")}
COMPANHIAS = {
    "LA": "LATAM", "JJ": "LATAM", "G3": "GOL", "AD": "Azul", "TP": "TAP", "AA": "American Airlines", "DL": "Delta",
    "UA": "United", "CM": "Copa Airlines", "AV": "Avianca", "IB": "Iberia", "UX": "Air Europa", "AF": "Air France",
    "KL": "KLM", "BA": "British Airways", "LH": "Lufthansa", "LX": "Swiss", "AZ": "ITA Airways", "TK": "Turkish Airlines",
    "EK": "Emirates", "QR": "Qatar Airways", "AT": "Royal Air Maroc", "AR": "Aerolíneas Argentinas", "H2": "SKY Airline",
    "DM": "Arajet", "F9": "Frontier", "NK": "Spirit", "B6": "JetBlue", "ET": "Ethiopian", "AC": "Air Canada",
    "TS": "Air Transat", "P5": "Wingo", "WN": "Southwest",
}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]           # date.weekday()
DIAS_CURTOS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
DIAS_PLURAL = ["as segundas", "as terças", "as quartas", "as quintas", "as sextas", "os sábados", "os domingos"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro",
         "outubro", "novembro", "dezembro"]

e = html.escape


def de(c): return DE.get(c, "de " + NOMES[c])
def para(c): return PARA.get(c, "para " + NOMES[c])


def slug(texto):
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return "-".join("".join(ch if ch.isalnum() else " " for ch in t).split())


def caminho_rota(o, d): return "passagens/" + slug(NOMES[o]) + "-" + slug(NOMES[d]) + "/"


def moeda_da_rota(o, d):
    """Mesma regra do index.html: usd (EUA), gbp (Londres), eur (resto da Europa)."""
    fora = d if o in BRASIL else o
    return "usd" if fora in EUA else ("gbp" if fora == "LON" else "eur")


def link_compra(o, d, data):
    """Cópia fiel da função linkCompra do index.html (Kiwi.com via Travelpayouts)."""
    aaaa, mm, dd = data.split("-")
    deeplink = ("https://www.kiwi.com/deep?from=" + quote(o, safe="") + "&to=" + quote(d, safe="")
                + "&departure=" + dd + "-" + mm + "-" + aaaa + "&return=no-return&lang=br&currency="
                + moeda_da_rota(o, d) + "&adults=1")
    return ("https://c111.travelpayouts.com/click?shmarker=790537.voameurei&promo_id=3791"
            "&source_type=customlink&type=click&custom_url=" + quote(deeplink, safe="-_.!~*'()"))


def dinheiro(v, moeda):
    return MOEDAS[moeda][0] + " " + f"{round(v):,}".replace(",", ".")


def data_longa(d):  # "quarta, 11 de novembro"
    return DIAS[d.weekday()] + ", " + str(d.day) + " de " + MESES[d.month - 1]


def nome_mes(d): return MESES[d.month - 1] + " de " + str(d.year)


def cia(cod): return COMPANHIAS.get(cod, cod) if cod else "Várias companhias"


def escalas(n):
    if n is None: return ""
    return "voo direto" if n == 0 else ("1 escala" if n == 1 else f"{n} escalas")


# ---------------------------------------------------------------- HTML comum
CSS = """:root{--sol:#F6B700;--sol-suave:#FFF1C2;--mar:#0A4D86;--mar-fundo:#083E6C;--laranja:#E4610F;--verde:#12804A;--verde-forte:#0B6B3C;--verde-suave:#DDF3E6;--fundo:#F8FAFC;--superficie:#FFF;--superficie-2:#EEF3F8;--tinta:#0E2A47;--tinta-2:#4A607A;--linha:#D6E0EA;--sobre-mar:#FFF;--sobre-mar-2:#CFE2F3;--sobre-sol:#2A1E00;--sombra:rgba(10,45,80,.12);--fita-5:#FFF;--fonte:"Bricolage Grotesque","Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;--raio:18px;--raio-p:10px;color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--sol:#FFC629;--sol-suave:#3A3110;--mar:#0D3A63;--mar-fundo:#082A4A;--laranja:#FF8A3D;--verde:#2FBF71;--verde-forte:#49D98A;--verde-suave:#123826;--fundo:#071A2C;--superficie:#0F2740;--superficie-2:#15324F;--tinta:#EEF4FA;--tinta-2:#A5B8CC;--linha:#24425F;--sobre-mar-2:#B7CFE6;--sombra:rgba(0,0,0,.35);--fita-5:#EEF4FA;color-scheme:dark}}
:root[data-theme="dark"]{--sol:#FFC629;--sol-suave:#3A3110;--mar:#0D3A63;--mar-fundo:#082A4A;--laranja:#FF8A3D;--verde:#2FBF71;--verde-forte:#49D98A;--verde-suave:#123826;--fundo:#071A2C;--superficie:#0F2740;--superficie-2:#15324F;--tinta:#EEF4FA;--tinta-2:#A5B8CC;--linha:#24425F;--sobre-mar-2:#B7CFE6;--sombra:rgba(0,0,0,.35);--fita-5:#EEF4FA;color-scheme:dark}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--fundo);color:var(--tinta);font-family:var(--fonte);font-size:1rem;line-height:1.5;overflow-x:hidden}
h1,h2,h3{text-wrap:balance;line-height:1.12;margin:0}p{margin:0}a{color:inherit}:focus-visible{outline:3px solid var(--sol);outline-offset:2px}
.wrap{max-width:880px;margin:0 auto;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
.hero{background:var(--mar-fundo);color:var(--sobre-mar)}.hero .wrap{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:56px}
.logo{display:flex;align-items:center;gap:8px;font-weight:800;text-decoration:none;white-space:nowrap;min-width:0}
.logo-sol{width:28px;height:28px;border-radius:50%;background:var(--sol);display:grid;place-items:center;color:var(--sobre-sol);flex:none}
.slogan{color:var(--sol);font-weight:800;font-size:.9rem;white-space:nowrap}
.fita{height:4px;background:repeating-linear-gradient(90deg,#12804A 0 40px,#F6B700 40px 80px,#1E6FD9 80px 120px,#D7263D 120px 160px,var(--fita-5) 160px 200px,#E4610F 200px 240px)}
main .wrap{padding-block:24px 40px;display:grid;gap:22px}
.trilha{font-size:.85rem;color:var(--tinta-2)}.trilha a{color:var(--tinta-2)}
h1{font-size:clamp(1.7rem,6vw,2.5rem);font-weight:800;letter-spacing:-.02em}
h2{font-size:1.3rem;font-weight:800;letter-spacing:-.01em}
.intro{font-size:1.08rem;max-width:42rem}.intro strong{color:var(--verde-forte)}
.mini{font-size:.85rem;color:var(--tinta-2)}
.dias{list-style:none;margin:0;padding:0;display:grid;gap:10px}
.dia{background:var(--superficie);border:1px solid var(--linha);border-radius:var(--raio);padding:14px 16px;display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 14px;align-items:center}
.dia.campeao{border-color:var(--verde);box-shadow:0 8px 24px var(--sombra)}
.dia .quando{font-weight:700}.dia .info{font-size:.85rem;color:var(--tinta-2)}
.dia .valor{font-size:1.5rem;font-weight:800;color:var(--verde-forte);font-variant-numeric:tabular-nums;grid-column:1}
.dia .btn{grid-column:2;grid-row:1/span 3}
.btn{font:inherit;font-weight:700;border:0;border-radius:999px;padding:12px 20px;min-height:48px;display:inline-flex;align-items:center;justify-content:center;text-decoration:none;text-align:center;cursor:pointer}
.btn-verde{background:var(--verde);color:#fff}.btn-sol{background:var(--sol);color:var(--sobre-sol)}
.btn-grande{width:100%;font-size:1.2rem;min-height:56px}
.caixa{background:var(--superficie);border:1px solid var(--linha);border-radius:var(--raio);padding:18px;display:grid;gap:12px}
.aviso{font-size:.8rem;color:var(--tinta-2)}
.links{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:0;padding:0}
.links a{display:inline-block;border:2px solid var(--sol);background:var(--sol-suave);border-radius:999px;padding:7px 14px;font-weight:600;font-size:.9rem;text-decoration:none;color:var(--tinta)}
.links a:hover{background:var(--sol);color:var(--sobre-sol)}.links small{font-weight:500;color:var(--tinta-2)}
.grupo{display:grid;gap:10px}
footer{background:var(--mar-fundo);color:var(--sobre-mar-2)}footer .wrap{padding-block:24px 36px;display:grid;gap:8px;font-size:.9rem}footer strong{color:var(--sobre-mar)}
@media (max-width:560px){.dia{grid-template-columns:minmax(0,1fr)}.dia .btn{grid-column:1;grid-row:auto;width:100%;margin-top:6px}}"""

AVIAO = '<svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22l3.5-1 3.5 1v-1.5L13 19v-5.5z"/></svg>'


def pagina(titulo, descricao, url, corpo, jsonld=None):
    ld = ""
    if jsonld:
        ld = '<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False) + "</script>\n"
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{VERIFICACAO}
<title>{e(titulo)}</title>
<meta name="description" content="{e(descricao)}">
<link rel="canonical" href="{url}">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<meta property="og:type" content="website">
<meta property="og:locale" content="pt_BR">
<meta property="og:site_name" content="Baianinho das Passagens">
<meta property="og:title" content="{e(titulo)}">
<meta property="og:description" content="{e(descricao)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}/og-image.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(titulo)}">
<meta name="twitter:description" content="{e(descricao)}">
<meta name="twitter:image" content="{SITE}/og-image.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&display=swap">
<style>{CSS}</style>
{ld}</head>
<body>
<header class="hero"><div class="wrap">
<a class="logo" href="/"><span class="logo-sol">{AVIAO}</span><span>Baianinho das Passagens</span></a>
<span class="slogan">Voa, meu rei!</span>
</div></header>
<div class="fita" aria-hidden="true"></div>
<main><div class="wrap">
{corpo}
</div></main>
<footer><div class="wrap">
<strong>Baianinho das Passagens · VoaMeuRei.com</strong>
<p>Os preços vêm de buscas recentes de viajantes e são atualizados todo dia. Só ida, por pessoa, na moeda da compra (dólar, euro ou libra). A compra é feita na Kiwi.com, nossa parceira, e o preço pode mudar até a hora da compra.</p>
<p><a href="/">Buscar passagens</a> · <a href="/passagens/">Todas as rotas</a></p>
</div></footer>
</body>
</html>
"""


def ajustar_descricao(base, extras):
    """Junta frases até ficar entre 140 e 160 caracteres (o tamanho que o Google mostra)."""
    texto = base
    for x in extras:
        if len(texto) >= 140:
            break
        if len(texto) + 1 + len(x) <= 160:
            texto += " " + x
    return texto


# ---------------------------------------------------------------- dados
def dias_da_rota(rota, hoje):
    """Lista [(date, info)] de todos os dias com preço, de hoje em diante."""
    lista = []
    for mes, dias in rota.items():
        if mes == "moeda" or not isinstance(dias, dict):
            continue
        for dd, v in dias.items():
            try:
                d = dt.date.fromisoformat(mes + "-" + dd)
            except ValueError:
                continue
            if d >= hoje and isinstance(v, dict) and v.get("preco"):
                lista.append((d, v))
    return sorted(lista)


def dia_semana_barato(dias):
    """Mesma regra do site: só com 10+ dias e 3+ dias da semana com 2+ preços."""
    soma, qtd = [0] * 7, [0] * 7
    for d, v in dias:
        soma[d.weekday()] += v["preco"]
        qtd[d.weekday()] += 1
    validos = [s for s in range(7) if qtd[s] >= 2]
    if len(dias) < 10 or len(validos) < 3:
        return None
    s = min(validos, key=lambda s: soma[s] / qtd[s])
    return s, soma[s] / qtd[s]


# ---------------------------------------------------------------- páginas
def pagina_rota(o, d, rota, hoje, atualizado, todas):
    moeda = rota.get("moeda") if rota.get("moeda") in MOEDAS else moeda_da_rota(o, d)
    simbolo, nome_moeda = MOEDAS[moeda]
    url = SITE + "/" + caminho_rota(o, d)
    dias = dias_da_rota(rota, hoje)
    rota_txt = de(o) + " " + para(d)               # "de Miami para São Paulo"
    titulo = "Passagem barata " + rota_txt + " | Baianinho das Passagens"
    h1 = "Passagem barata " + rota_txt
    aviso = f'<p class="aviso">Você vai para a Kiwi.com, nossa parceira. O site é em português e o preço aparece em {nome_moeda}.</p>'

    if dias:
        melhor_d, melhor_v = min(dias, key=lambda x: (x[1]["preco"], x[0]))
        descricao = ajustar_descricao(
            f"Passagem {rota_txt} a partir de {dinheiro(melhor_v['preco'], moeda)} em {nome_mes(melhor_d)}.",
            [("Veja os " + str(min(5, len(dias))) + " dias mais baratos" if len(dias) > 1 else "Veja o dia mais barato")
             + " e compre só ida, em " + nome_moeda + ".",
             "Preços atualizados todo dia.", "Voa, meu rei!"])
        semana = dia_semana_barato(dias)
        frase_semana = ""
        if semana:
            s, media = semana
            verbo = "costumam ser mais baratos" if s in (5, 6) else "costumam ser mais baratas"
            frase_semana = f" Nesta rota, {DIAS_PLURAL[s]} {verbo} (média de {dinheiro(media, moeda)})."
        intro = (f'<p class="intro">O dia mais barato que achamos para voar {rota_txt} é '
                 f'<strong>{data_longa(melhor_d)} de {melhor_d.year}, por {dinheiro(melhor_v["preco"], moeda)}</strong> '
                 f'(só ida, por pessoa, em {nome_moeda}).{frase_semana} '
                 f'Achamos preço em {len(dias)} {"dia" if len(dias) == 1 else "dias"} dos próximos meses.</p>')
        cinco = sorted(dias, key=lambda x: (x[1]["preco"], x[0]))[:5]
        itens = []
        for i, (dd, v) in enumerate(cinco):
            info = ", ".join(x for x in [cia(v.get("cia")), escalas(v.get("escalas"))] if x)
            itens.append(
                f'<li class="dia{" campeao" if i == 0 else ""}">'
                f'<span class="quando">{"★ " if i == 0 else ""}{data_longa(dd).capitalize()} de {dd.year}</span>'
                f'<span class="valor">{dinheiro(v["preco"], moeda)}</span>'
                f'<span class="info">{e(info)}</span>'
                f'<a class="btn btn-verde" href="{e(link_compra(o, d, dd.isoformat()))}" target="_blank" rel="noopener sponsored">Comprar este dia</a>'
                f'</li>')
        bloco = (f'<section class="grupo" aria-labelledby="t-dias"><h2 id="t-dias">Os {len(cinco)} dias mais baratos {rota_txt}</h2>'
                 f'<ol class="dias">{"".join(itens)}</ol>{aviso}</section>')
        mes_cal = melhor_d.strftime("%Y-%m")
    else:
        alvo = hoje + dt.timedelta(days=30)
        descricao = ajustar_descricao(
            f"Passagem {rota_txt}: veja o preço ao vivo, só ida, em {nome_moeda}.",
            ["Feito para brasileiros no exterior que querem voltar para casa.",
             "Preços atualizados todo dia.", "Voa, meu rei!"])
        intro = (f'<p class="intro">Ainda não temos preço guardado para voar {rota_txt}. '
                 f'Toque no botão para ver os voos ao vivo na Kiwi.com (só ida, por pessoa, em {nome_moeda}). '
                 f'Os preços são atualizados todo dia: volte amanhã para ver o calendário com os dias mais baratos.</p>')
        bloco = (f'<section class="caixa" aria-labelledby="t-vivo"><h2 id="t-vivo">Ver o preço ao vivo</h2>'
                 f'<p>Sugestão de data: {data_longa(alvo)} de {alvo.year}. Na Kiwi.com você pode trocar o dia.</p>'
                 f'<a class="btn btn-verde btn-grande" href="{e(link_compra(o, d, alvo.isoformat()))}" target="_blank" rel="noopener sponsored">Ver voos ao vivo</a>'
                 f'{aviso}</section>')
        mes_cal = None

    cal = SITE + "/?de=" + o + "&para=" + d + ("&mes=" + mes_cal if mes_cal else "")
    dica = ('<p class="mini">Dica de quem mora fora: para o Natal e as férias de julho, compre com 2 a 3 meses de '
            'antecedência. Voar no meio da semana costuma sair mais em conta.</p>')
    mesma_origem = [x for x in todas if x[0] == o and x[1] != d]
    mesmo_destino = [x for x in todas if x[1] == d and x[0] != o]
    def lista(rotas, rotulo):
        return "".join(f'<li><a href="/{caminho_rota(a, b)}">{e(rotulo(a, b))}</a></li>' for a, b in rotas)
    corpo = f"""<nav class="trilha" aria-label="Você está aqui"><a href="/">Início</a> › <a href="/passagens/">Passagens</a> › {e(NOMES[o])} → {e(NOMES[d])}</nav>
<h1>{e(h1)}</h1>
{intro}
<p class="mini">Preços atualizados em {atualizado}. O preço pode mudar até a hora da compra.</p>
{bloco}
<a class="btn btn-sol btn-grande" href="{e(cal)}">Ver o calendário completo</a>
{dica}
<section class="grupo"><h2>Outras rotas saindo {e(de(o))}</h2><ul class="links">{lista(mesma_origem, lambda a, b: NOMES[a] + " → " + NOMES[b])}</ul></section>
<section class="grupo"><h2>Outras cidades com voo {e(para(d))}</h2><ul class="links">{lista(mesmo_destino, lambda a, b: NOMES[a] + " → " + NOMES[b])}</ul></section>"""
    jsonld = {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": 1, "name": "Início", "item": SITE + "/"},
        {"@type": "ListItem", "position": 2, "name": "Passagens", "item": SITE + "/passagens/"},
        {"@type": "ListItem", "position": 3, "name": NOMES[o] + " → " + NOMES[d], "item": url}]}
    return pagina(titulo, descricao, url, corpo, jsonld), (min(v["preco"] for _, v in dias) if dias else None, moeda)


def pagina_lista(todas, resumo, atualizado):
    url = SITE + "/passagens/"
    titulo = "Passagens baratas para o Brasil por rota | Baianinho"
    descricao = ("Todas as rotas do Baianinho: passagem barata dos Estados Unidos e da Europa para BH, São Paulo, "
                 "Goiânia, Rio e Nordeste. Veja o menor preço de cada rota.")
    grupos = []
    for regiao, origens in (("Saindo dos Estados Unidos", EUA), ("Saindo da Europa", EUROPA)):
        blocos = []
        for o in origens:
            rotas = [x for x in todas if x[0] == o]
            if not rotas:
                continue
            itens = []
            for a, b in rotas:
                preco, moeda = resumo[(a, b)]
                extra = f" <small>desde {dinheiro(preco, moeda)}</small>" if preco else ""
                itens.append(f'<li><a href="/{caminho_rota(a, b)}">{e(NOMES[b])}{extra}</a></li>')
            blocos.append(f'<div class="grupo"><h3>Passagem {e(de(o))} para o Brasil</h3><ul class="links">{"".join(itens)}</ul></div>')
        grupos.append(f'<section class="grupo"><h2>{regiao}</h2>{"".join(blocos)}</section>')
    corpo = f"""<nav class="trilha" aria-label="Você está aqui"><a href="/">Início</a> › Passagens</nav>
<h1>Passagens baratas para o Brasil, rota por rota</h1>
<p class="intro">Para brasileiros no exterior que querem voltar para casa gastando pouco. Escolha a sua rota e veja o dia mais barato, só ida, em dólar, euro ou libra.</p>
<p class="mini">Preços atualizados em {atualizado}. "Desde" = menor preço guardado nos próximos meses.</p>
{"".join(grupos)}
<a class="btn btn-sol btn-grande" href="/">Buscar no calendário</a>"""
    return pagina(titulo, descricao, url, corpo)


def main():
    precos = json.loads((RAIZ / "precos.json").read_text(encoding="utf-8"))
    agora_br = dt.datetime.now(FUSO_BR)
    hoje = agora_br.date()
    try:
        at = dt.datetime.fromisoformat(precos["atualizado_em"]).astimezone(FUSO_BR)
        atualizado = at.strftime("%d/%m/%Y")
    except (KeyError, ValueError):
        atualizado = hoje.strftime("%d/%m/%Y")

    rotas_json = precos.get("rotas", {})
    ordem = {c: i for i, c in enumerate(EUA + EUROPA + BRASIL)}
    todas = []
    for chave in rotas_json:
        o, _, d = chave.partition("-")
        if o in NOMES and d in BRASIL and o not in BRASIL:
            todas.append((o, d))
    todas.sort(key=lambda x: (ordem[x[0]], ordem[x[1]]))

    if PASTA.exists():
        shutil.rmtree(PASTA)   # recria do zero (rota que saiu do json some do site)
    resumo = {}
    for o, d in todas:
        conteudo, resumo[(o, d)] = pagina_rota(o, d, rotas_json[o + "-" + d], hoje, atualizado, todas)
        destino = RAIZ / caminho_rota(o, d) / "index.html"
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(conteudo, encoding="utf-8")
    (PASTA / "index.html").write_text(pagina_lista(todas, resumo, atualizado), encoding="utf-8")

    urls = [SITE + "/", SITE + "/passagens/"] + [SITE + "/" + caminho_rota(o, d) for o, d in todas]
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u in urls:
        xml.append(f"  <url><loc>{u}</loc><lastmod>{hoje.isoformat()}</lastmod></url>")
    xml.append("</urlset>")
    (RAIZ / "sitemap.xml").write_text("\n".join(xml) + "\n", encoding="utf-8")
    print(f"{len(todas)} páginas de rota + passagens/index.html + sitemap.xml ({len(urls)} URLs) — {hoje}")


if __name__ == "__main__":
    main()
