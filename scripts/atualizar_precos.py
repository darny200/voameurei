#!/usr/bin/env python3
"""
Atualiza o arquivo precos.json com preços REAIS da Travelpayouts/Aviasales.

Como funciona (bem simples):
  1. Pega o token da variável TP_TOKEN (no GitHub vem do "secret"; no PC vem do arquivo .env).
  2. Para cada rota e para os próximos 3 meses, pergunta à API qual o preço de cada dia.
  3. Grava tudo em precos.json, que o site lê. O token NUNCA vai para o site.

Rodar:  python3 scripts/atualizar_precos.py
"""
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "precos.json"
MARKER = "790537"
PAUSA = 0.3  # segundos entre chamadas

CIDADES = {
    # EUA
    "MIA": "Miami", "ORL": "Orlando", "NYC": "Nova York", "BOS": "Boston", "ATL": "Atlanta",
    # Europa
    "LIS": "Lisboa", "OPO": "Porto", "LON": "Londres", "MAD": "Madri", "BCN": "Barcelona",
    "ROM": "Roma", "MIL": "Milão", "PAR": "Paris",
    # Brasil
    "SAO": "São Paulo", "RIO": "Rio de Janeiro", "BHZ": "Belo Horizonte", "GYN": "Goiânia",
    "SSA": "Salvador", "REC": "Recife", "FOR": "Fortaleza", "BSB": "Brasília",
}
ORIGENS_FORA = ["MIA", "ORL", "NYC", "BOS", "ATL", "LIS", "OPO", "LON", "MAD", "BCN", "ROM", "MIL", "PAR"]
DESTINOS_PRIORITARIOS = ["BHZ", "SAO", "GYN"]
ORIGENS_EXTRA = ["MIA", "ORL", "LIS", "LON"]
DESTINOS_EXTRA = ["RIO", "SSA", "REC", "FOR", "BSB"]

ROTAS = [(o, d) for o in ORIGENS_FORA for d in DESTINOS_PRIORITARIOS] + \
        [(o, d) for o in ORIGENS_EXTRA for d in DESTINOS_EXTRA]


def carregar_token():
    token = os.environ.get("TP_TOKEN", "").strip()
    if token:
        return token
    env = RAIZ / ".env"
    if env.exists():
        for linha in env.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("TP_TOKEN="):
                return linha.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("ERRO: TP_TOKEN não encontrado (nem na variável de ambiente, nem no .env).")


def meses_alvo(hoje):
    lista = []
    ano, mes = hoje.year, hoje.month
    for _ in range(3):
        lista.append(f"{ano:04d}-{mes:02d}")
        mes += 1
        if mes > 12:
            mes, ano = 1, ano + 1
    return lista


def chamar(sessao, url, params):
    try:
        r = sessao.get(url, params=params, timeout=30)
        if r.status_code != 200:
            print(f"  aviso: HTTP {r.status_code} em {url}", file=sys.stderr)
            return None
        return r.json()
    except Exception as e:  # rede, JSON inválido etc.
        print(f"  aviso: falha em {url}: {e}", file=sys.stderr)
        return None
    finally:
        time.sleep(PAUSA)


def link_padrao(origem, destino, data_iso):
    _, mm, dd = data_iso.split("-")
    return f"https://www.aviasales.com/search/{origem}{dd}{mm}{destino}1?marker={MARKER}"


def link_da_api(link):
    if not link:
        return None
    if not link.startswith("/"):
        link = "/" + link
    sep = "&" if "?" in link else "?"
    return f"https://www.aviasales.com{link}{sep}marker={MARKER}"


def saida_curta(departure_at):
    # "2026-12-03T08:10:00-05:00" -> "2026-12-03T08:10"
    return departure_at[:16] if departure_at else None


def buscar_calendario(sessao, token, origem, destino, mes):
    j = chamar(sessao, "https://api.travelpayouts.com/v1/prices/calendar", {
        "origin": origem, "destination": destino, "depart_date": mes,
        "calendar_type": "departure_date", "currency": "brl", "token": token,
    })
    dias = {}
    if not j or not j.get("success") or not isinstance(j.get("data"), dict):
        return dias
    for data_iso, v in j["data"].items():
        if not data_iso.startswith(mes) or not v.get("price"):
            continue
        dias[data_iso] = {
            "preco": round(v["price"]),
            "cia": v.get("airline"),
            "escalas": v.get("transfers"),
            "saida": saida_curta(v.get("departure_at")),
            "duracao_min": v.get("duration"),
            "link": link_padrao(origem, destino, data_iso),
        }
    return dias


def buscar_por_datas(sessao, token, origem, destino, mes):
    j = chamar(sessao, "https://api.travelpayouts.com/aviasales/v3/prices_for_dates", {
        "origin": origem, "destination": destino, "departure_at": mes, "currency": "brl",
        "sorting": "price", "limit": 30, "one_way": "true", "token": token,
    })
    dias = {}
    if not j or not isinstance(j.get("data"), list):
        return dias
    for v in j["data"]:
        saida = v.get("departure_at") or ""
        data_iso = saida[:10]
        if not data_iso.startswith(mes) or not v.get("price"):
            continue
        preco = round(v["price"])
        if data_iso in dias and dias[data_iso]["preco"] <= preco:
            continue  # já temos um voo mais barato nesse dia
        dias[data_iso] = {
            "preco": preco,
            "cia": v.get("airline"),
            "escalas": v.get("transfers"),
            "saida": saida_curta(saida),
            "duracao_min": v.get("duration_to") or v.get("duration"),
            "link": link_da_api(v.get("link")) or link_padrao(origem, destino, data_iso),
        }
    return dias


def escolher_promocoes(rotas, hoje_iso, quantas=8, max_por_origem=2):
    melhores = []  # o dia mais barato de cada rota (entre todos os meses)
    for rota, meses in rotas.items():
        candidato = None
        for mes, dias in meses.items():
            for dd, v in dias.items():
                data_iso = f"{mes}-{dd}"
                if data_iso < hoje_iso:
                    continue
                if candidato is None or v["preco"] < candidato["preco"]:
                    candidato = dict(v, data=data_iso)
        if candidato:
            o, d = rota.split("-")
            melhores.append({
                "rota": rota, "origem": o, "destino": d,
                "origem_nome": CIDADES[o], "destino_nome": CIDADES[d],
                "data": candidato["data"], "preco": candidato["preco"],
                "cia": candidato.get("cia"), "escalas": candidato.get("escalas"),
                "saida": candidato.get("saida"), "duracao_min": candidato.get("duracao_min"),
                "link": candidato["link"],
            })
    melhores.sort(key=lambda p: p["preco"])
    escolhidas, por_origem = [], {}
    for p in melhores:
        if por_origem.get(p["origem"], 0) >= max_por_origem:
            continue
        escolhidas.append(p)
        por_origem[p["origem"]] = por_origem.get(p["origem"], 0) + 1
        if len(escolhidas) >= quantas:
            break
    return escolhidas


def main():
    token = carregar_token()
    agora = dt.datetime.now(dt.timezone.utc)
    hoje_iso = agora.date().isoformat()
    meses = meses_alvo(agora.date())
    sessao = requests.Session()

    rotas = {}
    com_dados, vazias = 0, 0
    for i, (o, d) in enumerate(ROTAS, 1):
        chave = f"{o}-{d}"
        rotas[chave] = {}
        for mes in meses:
            # Calendário primeiro; a busca por datas completa os dias que faltam
            # (e, quando o preço empata ou é menor, traz o link direto do voo).
            dias = buscar_calendario(sessao, token, o, d, mes)
            for data_iso, v in buscar_por_datas(sessao, token, o, d, mes).items():
                if data_iso not in dias or v["preco"] <= dias[data_iso]["preco"]:
                    dias[data_iso] = v
            # só dias de hoje em diante, em ordem
            dias = {k: v for k, v in sorted(dias.items()) if k >= hoje_iso}
            rotas[chave][mes] = {k[-2:]: v for k, v in dias.items()}
        total = sum(len(x) for x in rotas[chave].values())
        if total:
            com_dados += 1
        else:
            vazias += 1
        print(f"[{i:2d}/{len(ROTAS)}] {chave}: {total} dias com preço")

    resultado = {
        "atualizado_em": agora.replace(microsecond=0).isoformat(),
        "moeda": "BRL",
        "meses": meses,
        "cidades": CIDADES,
        "rotas": rotas,
        "promocoes": escolher_promocoes(rotas, hoje_iso),
    }
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nPronto: {com_dados} rotas com preço, {vazias} vazias. Arquivo: {SAIDA}")


if __name__ == "__main__":
    main()
