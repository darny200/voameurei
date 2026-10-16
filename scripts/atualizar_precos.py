#!/usr/bin/env python3
"""
Atualiza o arquivo precos.json com preços REAIS da Travelpayouts (Data API).

Como funciona (bem simples):
  1. Pega o token da variável TP_TOKEN (no GitHub vem do "secret"; no PC vem do arquivo .env).
  2. Para cada rota e para os próximos 3 meses, pergunta a 4 "fontes" da API (cada uma
     conhece dias diferentes), com o código da cidade E dos aeroportos dela, e junta tudo,
     ficando com o menor preço de cada dia.
  3. Cada rota é pedida JÁ na moeda em que o cliente vai pagar na Kiwi.com:
     dólar (usd) para os EUA, libra (gbp) para Londres e euro (eur) para o resto da Europa.
     (Rota que sai do Brasil usa a moeda do destino.) A moeda vai gravada em cada rota.
  4. Grava tudo em precos.json, que o site lê. O token NUNCA vai para o site.
     Os links de compra NÃO vêm daqui: o site monta o link da Kiwi.com sozinho.

Rodar:  python3 scripts/atualizar_precos.py
"""
import datetime as dt
import json
import threading
from concurrent.futures import ThreadPoolExecutor
import os
import sys
import time
from pathlib import Path

import requests

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "precos.json"
PAUSA = 0.25  # segundos entre o início de uma chamada e o da próxima
TRABALHADORES = 4  # chamadas ao mesmo tempo (o ritmo continua 1 chamada a cada PAUSA)
LIMITE_SEGUNDOS = 17 * 60  # depois disso, para de consultar os aeroportos extras (o GitHub tem limite de tempo)
MAX_AEROPORTOS_EXTRAS = 3

# Aeroportos de cada cidade. Tudo é somado na rota cidade→cidade.
AEROPORTOS = {
    "SAO": ["GRU", "VCP", "CGH"], "RIO": ["GIG", "SDU"], "BHZ": ["CNF"],
    "NYC": ["JFK", "EWR", "LGA"], "LON": ["LHR", "LGW", "STN"], "ORL": ["MCO"],
    "MIA": ["MIA", "FLL"], "PAR": ["CDG", "ORY"], "MIL": ["MXP"], "ROM": ["FCO"],
}

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
EUA = {"MIA", "ORL", "NYC", "BOS", "ATL"}
BRASIL = {"SAO", "RIO", "BHZ", "GYN", "SSA", "REC", "FOR", "BSB"}
# Taxa fixa aproximada (em dólar) SÓ para ordenar promoções de moedas diferentes. Nunca é mostrada.
TAXA_ORDENAR = {"usd": 1.0, "eur": 1.08, "gbp": 1.27}


def moeda_da_rota(origem, destino):
    """usd (EUA), gbp (Londres) ou eur (resto da Europa). Saindo do Brasil, vale a cidade de destino."""
    fora = destino if origem in BRASIL else origem
    if fora in EUA:
        return "usd"
    if fora == "LON":
        return "gbp"
    return "eur"


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


_trava = threading.Lock()
_proxima = [0.0]
_contador = {"chamadas": 0, "erros": 0}


def _esperar_vez():
    """Garante ~PAUSA segundos entre o começo de cada chamada (mesmo com várias linhas de trabalho)."""
    with _trava:
        agora = time.monotonic()
        espera = _proxima[0] - agora
        _proxima[0] = max(agora, _proxima[0]) + PAUSA
        _contador["chamadas"] += 1
    if espera > 0:
        time.sleep(espera)


def chamar(sessao, url, params):
    for tentativa in range(3):
        _esperar_vez()
        try:
            r = sessao.get(url, params=params, timeout=30)
            if r.status_code == 429:  # pediu para ir mais devagar
                time.sleep(2 + 3 * tentativa)
                continue
            if r.status_code != 200:
                print(f"  aviso: HTTP {r.status_code} em {url} {params.get('origin')}-{params.get('destination')}", file=sys.stderr)
                _contador["erros"] += 1
                return None
            return r.json()
        except Exception as e:  # rede, JSON inválido etc.
            print(f"  aviso: falha em {url}: {e}", file=sys.stderr)
            time.sleep(1)
    _contador["erros"] += 1
    return None


def saida_curta(departure_at):
    # "2026-12-03T08:10:00-05:00" -> "2026-12-03T08:10"
    return departure_at[:16] if departure_at else None


def _guardar(dias, data_iso, item):
    """Guarda o voo no dia, ficando sempre com o MENOR preço."""
    atual = dias.get(data_iso)
    if atual is None or item["preco"] < atual["preco"]:
        dias[data_iso] = item
    elif item["preco"] == atual["preco"] and _riqueza(item) > _riqueza(atual):
        dias[data_iso] = item  # mesmo preço, mas com mais detalhes (companhia, horário, duração)


def _riqueza(item):
    return (1 if item.get("cia") else 0) + (1 if item.get("saida") else 0) + (1 if item.get("duracao_min") else 0)


def buscar_calendario(sessao, token, cid_o, cid_d, o, d, mes):
    j = chamar(sessao, "https://api.travelpayouts.com/v1/prices/calendar", {
        "origin": o, "destination": d, "depart_date": mes,
        "calendar_type": "departure_date", "currency": moeda_da_rota(cid_o, cid_d), "token": token,
    })
    dias = {}
    if not j or not j.get("success") or not isinstance(j.get("data"), dict):
        return dias
    for data_iso, v in j["data"].items():
        if not data_iso.startswith(mes) or not v.get("price"):
            continue
        if v.get("return_at"):
            continue  # é preço de ida E volta; o site mostra só ida
        _guardar(dias, data_iso, {
            "preco": round(v["price"]),
            "cia": v.get("airline"),
            "escalas": v.get("transfers"),
            "saida": saida_curta(v.get("departure_at")),
            "duracao_min": v.get("duration"),
            "de": o, "para": d, "fonte": "calendar",
        })
    return dias


def buscar_matriz(sessao, token, cid_o, cid_d, o, d, mes):
    j = chamar(sessao, "https://api.travelpayouts.com/v2/prices/month-matrix", {
        "currency": moeda_da_rota(cid_o, cid_d), "origin": o, "destination": d, "month": mes + "-01",
        "show_to_affiliates": "true", "token": token,
    })
    dias = {}
    if not j or not isinstance(j.get("data"), list):
        return dias
    for v in j["data"]:
        data_iso = v.get("depart_date") or ""
        if not data_iso.startswith(mes) or not v.get("value") or v.get("return_date"):
            continue
        _guardar(dias, data_iso, {
            "preco": round(v["value"]),
            "cia": None,
            "escalas": v.get("number_of_changes"),
            "saida": None,
            "duracao_min": v.get("duration") or None,
            "de": o, "para": d, "fonte": "month-matrix",
        })
    return dias


def _item_v3(v, cid_o, cid_d, data_iso, o, d, fonte):
    return {
        "preco": round(v["price"]),
        "cia": v.get("airline"),
        "escalas": v.get("transfers"),
        "saida": saida_curta(v.get("departure_at")),
        "duracao_min": v.get("duration_to") or v.get("duration"),
        "de": v.get("origin_airport") or o, "para": v.get("destination_airport") or d, "fonte": fonte,
    }


def buscar_por_datas(sessao, token, cid_o, cid_d, o, d, mes):
    j = chamar(sessao, "https://api.travelpayouts.com/aviasales/v3/prices_for_dates", {
        "origin": o, "destination": d, "departure_at": mes, "currency": moeda_da_rota(cid_o, cid_d),
        "sorting": "price", "limit": 1000, "one_way": "true", "token": token,
    })
    dias = {}
    if not j or not isinstance(j.get("data"), list):
        return dias
    for v in j["data"]:
        data_iso = (v.get("departure_at") or "")[:10]
        if not data_iso.startswith(mes) or not v.get("price"):
            continue
        _guardar(dias, data_iso, _item_v3(v, cid_o, cid_d, data_iso, o, d, "prices_for_dates"))
    return dias


def buscar_agrupado(sessao, token, cid_o, cid_d, o, d, mes):
    j = chamar(sessao, "https://api.travelpayouts.com/aviasales/v3/grouped_prices", {
        "origin": o, "destination": d, "departure_at": mes, "group_by": "departure_at",
        "currency": moeda_da_rota(cid_o, cid_d), "token": token,
    })
    dias = {}
    if not j or not isinstance(j.get("data"), dict):
        return dias
    for v in j["data"].values():
        data_iso = (v.get("departure_at") or "")[:10]
        if not data_iso.startswith(mes) or not v.get("price"):
            continue
        _guardar(dias, data_iso, _item_v3(v, cid_o, cid_d, data_iso, o, d, "grouped_prices"))
    return dias


FONTES = [buscar_matriz, buscar_calendario, buscar_por_datas, buscar_agrupado]


def codigos(cidade):
    """Código da cidade + até MAX_AEROPORTOS_EXTRAS aeroportos dela (sem repetir)."""
    lista = [cidade]
    for a in AEROPORTOS.get(cidade, [])[:MAX_AEROPORTOS_EXTRAS]:
        if a not in lista:
            lista.append(a)
    return lista


def escolher_promocoes(rotas, hoje_iso, quantas=8, max_por_origem=2):
    melhores = []  # o dia mais barato de cada rota (entre todos os meses)
    for rota, meses in rotas.items():
        candidato = None
        for mes, dias in meses.items():
            if not isinstance(dias, dict):
                continue  # pula o campo "moeda"
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
                "moeda": moeda_da_rota(o, d),
            })
    # Moedas diferentes: ordena pelo valor aproximado em dólar (só para ordenar; o site mostra a moeda original)
    melhores.sort(key=lambda p: p["preco"] * TAXA_ORDENAR[p["moeda"]])
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

    inicio = time.monotonic()
    # Lista de tarefas: (rota, mês, código de saída, código de chegada, fonte).
    # Primeiro TODAS as rotas com os códigos de cidade; depois os aeroportos extras.
    principais, extras = [], []
    for o, d in ROTAS:
        for mes in meses:
            for co in codigos(o):
                for cd in codigos(d):
                    for fonte in FONTES:
                        (principais if (co, cd) == (o, d) else extras).append((o, d, mes, co, cd, fonte))
    print(f"{len(principais)} consultas principais + {len(extras)} de aeroportos extras")

    junto = {}  # (rota, mês) -> {data: voo}
    trava_junto = threading.Lock()
    pulou = [0]

    def fazer(tarefa, opcional):
        o, d, mes, co, cd, fonte = tarefa
        if opcional and time.monotonic() - inicio > LIMITE_SEGUNDOS:
            pulou[0] += 1
            return
        sessao = sessoes.setdefault(threading.get_ident(), requests.Session())
        dias = fonte(sessao, token, o, d, co, cd, mes)
        with trava_junto:
            alvo = junto.setdefault((o, d, mes), {})
            for data_iso, item in dias.items():
                _guardar(alvo, data_iso, item)

    sessoes = {}
    with ThreadPoolExecutor(TRABALHADORES) as ex:
        list(ex.map(lambda t: fazer(t, False), principais))
        print(f"  principais prontas em {time.monotonic() - inicio:.0f}s")
        list(ex.map(lambda t: fazer(t, True), extras))
    if pulou[0]:
        print(f"  aviso: {pulou[0]} consultas de aeroportos extras puladas por falta de tempo", file=sys.stderr)

    rotas = {}
    com_dados, vazias = 0, 0
    for i, (o, d) in enumerate(ROTAS, 1):
        chave = f"{o}-{d}"
        rotas[chave] = {"moeda": moeda_da_rota(o, d)}
        for mes in meses:
            dias = junto.get((o, d, mes), {})
            # só dias de hoje em diante, em ordem
            dias = {k: v for k, v in sorted(dias.items()) if k >= hoje_iso}
            rotas[chave][mes] = {k[-2:]: v for k, v in dias.items()}
        total = sum(len(rotas[chave][m]) for m in meses)
        if total:
            com_dados += 1
        else:
            vazias += 1
        print(f"[{i:2d}/{len(ROTAS)}] {chave}: {total} dias com preço")
    total_dias = sum(len(r[m]) for r in rotas.values() for m in meses)
    print(f"Total: {total_dias} dias com preço; {_contador['chamadas']} chamadas, {_contador['erros']} erros, "
          f"{time.monotonic() - inicio:.0f}s")

    resultado = {
        "atualizado_em": agora.replace(microsecond=0).isoformat(),
        "moeda": "por_rota",  # cada rota tem o seu campo "moeda": usd, eur ou gbp
        "fontes": ["v2/prices/month-matrix", "v1/prices/calendar", "aviasales/v3/prices_for_dates",
                   "aviasales/v3/grouped_prices"],
        "meses": meses,
        "cidades": CIDADES,
        "rotas": rotas,
        "promocoes": escolher_promocoes(rotas, hoje_iso),
    }
    SAIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\nPronto: {com_dados} rotas com preço, {vazias} vazias. Arquivo: {SAIDA}")


if __name__ == "__main__":
    main()
