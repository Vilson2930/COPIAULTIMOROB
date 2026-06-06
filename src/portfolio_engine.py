import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd


LIVE_PORTFOLIO_PATH = "config/live_portfolio.csv"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def load_live_portfolio(path=LIVE_PORTFOLIO_PATH, required_assets=None):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Arquivo obrigatório ausente: {path}")

    portfolio = pd.read_csv(path)

    required_columns = ["ativo", "quantidade"]
    missing = [col for col in required_columns if col not in portfolio.columns]

    if missing:
        raise ValueError(f"live_portfolio.csv com colunas ausentes: {missing}")

    portfolio = portfolio.copy()
    portfolio["ativo"] = portfolio["ativo"].astype(str).str.strip()
    portfolio["quantidade"] = portfolio["quantidade"].astype(float)

    if portfolio["ativo"].duplicated().any():
        portfolio = portfolio.groupby("ativo", as_index=False)["quantidade"].sum()

    if required_assets is not None:
        required_assets = list(required_assets)

        unknown_assets = sorted(set(portfolio["ativo"]) - set(required_assets))

        if unknown_assets:
            raise ValueError(
                f"Ativos no live_portfolio.csv sem preço/regra no robô: {unknown_assets}"
            )

        missing_assets = sorted(set(required_assets) - set(portfolio["ativo"]))

        if missing_assets:
            missing_df = pd.DataFrame({
                "ativo": missing_assets,
                "quantidade": [0.0] * len(missing_assets),
            })

            portfolio = pd.concat([portfolio, missing_df], ignore_index=True)

        portfolio = portfolio.set_index("ativo").loc[required_assets].reset_index()

    return dict(zip(portfolio["ativo"], portfolio["quantidade"]))


def interpolate_allocations(a, b, t):
    return {
        asset: a[asset] * (1 - t) + b[asset] * t
        for asset in a
    }


def build_target_allocation(latest):
    allocation_anchors = {
        "DEFENSIVA": {
            "BTC-USD": 0.08,
            "USDT-USD": 0.32,
            "GLD": 0.22,
            "VOO": 0.05,
            "TLT": 0.33,
            "BOTZ": 0.00,
            "INDA": 0.00,
        },
        "NEUTRA": {
            "BTC-USD": 0.20,
            "USDT-USD": 0.18,
            "GLD": 0.12,
            "VOO": 0.20,
            "TLT": 0.20,
            "BOTZ": 0.05,
            "INDA": 0.05,
        },
        "RISCO_ON": {
            "BTC-USD": 0.25,
            "USDT-USD": 0.10,
            "GLD": 0.10,
            "VOO": 0.25,
            "TLT": 0.15,
            "BOTZ": 0.08,
            "INDA": 0.07,
        },
        "EXPANSAO_FORTE": {
            "BTC-USD": 0.30,
            "USDT-USD": 0.05,
            "GLD": 0.07,
            "VOO": 0.30,
            "TLT": 0.08,
            "BOTZ": 0.12,
            "INDA": 0.08,
        },
    }

    conviction = float(latest["macro_conviction"])
    confidence = float(latest["confidence_score"])
    momentum = float(latest["macro_momentum"])

    if conviction < 40:
        t = conviction / 40
        target_allocation = interpolate_allocations(
            allocation_anchors["DEFENSIVA"],
            allocation_anchors["NEUTRA"],
            t,
        )

    elif conviction < 60:
        t = (conviction - 40) / 20
        target_allocation = interpolate_allocations(
            allocation_anchors["NEUTRA"],
            allocation_anchors["RISCO_ON"],
            t,
        )

    elif conviction < 80:
        t = (conviction - 60) / 20
        target_allocation = interpolate_allocations(
            allocation_anchors["RISCO_ON"],
            allocation_anchors["EXPANSAO_FORTE"],
            t,
        )

    else:
        target_allocation = allocation_anchors["EXPANSAO_FORTE"].copy()

    risk_assets = ["BTC-USD", "VOO", "BOTZ", "INDA"]
    defensive_assets = ["USDT-USD", "GLD", "TLT"]

    if confidence < 60:
        confidence_penalty = (60 - confidence) / 100
        risk_reduction = 0

        for asset in risk_assets:
            cut = target_allocation[asset] * confidence_penalty
            target_allocation[asset] -= cut
            risk_reduction += cut

        defensive_add = risk_reduction / len(defensive_assets)

        for asset in defensive_assets:
            target_allocation[asset] += defensive_add

    if momentum < 0:
        momentum_penalty = min(abs(momentum) / 50, 0.15)
        risk_reduction = 0

        for asset in risk_assets:
            cut = target_allocation[asset] * momentum_penalty
            target_allocation[asset] -= cut
            risk_reduction += cut

        defensive_add = risk_reduction / len(defensive_assets)

        for asset in defensive_assets:
            target_allocation[asset] += defensive_add

    total_weight = sum(target_allocation.values())

    for asset in target_allocation:
        target_allocation[asset] = target_allocation[asset] / total_weight

    return target_allocation


def run_rebalance(latest, latest_market, target_allocation):
    MIN_DRIFT = 0.02
    MIN_TRADE_USD = 1000
    MAX_TURNOVER = 0.25
    MAX_USDT_DEPLOY = 0.50

    USDT_MIN_WEIGHT = 0.05
    TLT_MIN_WEIGHT = 0.08

    GLD_MIN_WEIGHT = 0.07
    GLD_MAX_WEIGHT = 0.25

    EXPANSAO_ON = 62
    EXPANSAO_OFF = 55

    GROWTH_BUY_ASSETS = ["VOO", "BOTZ", "INDA"]

    MAX_WEIGHT = {
        "BTC-USD": 0.50,
        "VOO": 0.40,
        "BOTZ": 0.20,
        "INDA": 0.15,
    }

    portfolio_qty = load_live_portfolio(
        required_assets=target_allocation.keys()
    )

    latest_prices = {
        "BTC-USD": float(latest_market["btc"]),
        "USDT-USD": 1.0,
        "GLD": float(latest_market["gld"]),
        "VOO": float(latest_market["voo"]),
        "TLT": float(latest_market["tlt"]),
        "BOTZ": float(latest_market["botz"]),
        "INDA": float(latest_market["inda"]),
    }

    macro_conviction = float(latest["macro_conviction"])
    macro_score = float(latest["macro_score"])
    macro_momentum = float(latest["macro_momentum"])
    confidence_score = float(latest["confidence_score"])

    liquidity_score = float(latest["liquidez"])
    stress_score_macro = float(latest["stress"])

    warning_score_current = 0.0
    trend_positive = macro_momentum > 0

    macro_extremo = (
        liquidity_score < 25
        or stress_score_macro < 40
        or warning_score_current > 80
    )

    macro_favoravel = (
        macro_conviction >= EXPANSAO_ON
        and stress_score_macro >= 60
        and liquidity_score >= 40
        and trend_positive
        and not macro_extremo
    )

    macro_atencao = (
        (EXPANSAO_OFF <= macro_conviction < EXPANSAO_ON)
        or warning_score_current >= 50
        or liquidity_score < 40
    )

    macro_defensivo = (
        macro_conviction < EXPANSAO_OFF
        or stress_score_macro < 60
        or liquidity_score < 35
    )

    rebalance = pd.DataFrame(index=portfolio_qty.keys())

    rebalance["quantidade_atual"] = pd.Series(portfolio_qty)
    rebalance["preco_atual"] = pd.Series(latest_prices)
    rebalance["valor_atual"] = (
        rebalance["quantidade_atual"] * rebalance["preco_atual"]
    )

    total_value = rebalance["valor_atual"].sum()

    if total_value <= 0:
        raise ValueError("Valor total da carteira inválido.")

    rebalance["peso_atual"] = rebalance["valor_atual"] / total_value
    rebalance["peso_alvo"] = pd.Series(target_allocation)

    if rebalance.loc["GLD", "peso_alvo"] > GLD_MAX_WEIGHT:
        excess = rebalance.loc["GLD", "peso_alvo"] - GLD_MAX_WEIGHT
        rebalance.loc["GLD", "peso_alvo"] = GLD_MAX_WEIGHT
        rebalance.loc["USDT-USD", "peso_alvo"] += excess

    if rebalance.loc["GLD", "peso_alvo"] < GLD_MIN_WEIGHT:
        shortage = GLD_MIN_WEIGHT - rebalance.loc["GLD", "peso_alvo"]
        rebalance.loc["GLD", "peso_alvo"] = GLD_MIN_WEIGHT
        rebalance.loc["USDT-USD", "peso_alvo"] -= shortage

    rebalance["peso_alvo"] = (
        rebalance["peso_alvo"] / rebalance["peso_alvo"].sum()
    )

    rebalance["valor_alvo"] = rebalance["peso_alvo"] * total_value
    rebalance["desvio_peso"] = rebalance["peso_alvo"] - rebalance["peso_atual"]
    rebalance["ajuste_usd_bruto"] = (
        rebalance["valor_alvo"] - rebalance["valor_atual"]
    )

    rebalance["ajuste_usd"] = 0.0
    rebalance["motivo_execucao"] = ""

    for asset in rebalance.index:
        ajuste = rebalance.loc[asset, "ajuste_usd_bruto"]
        desvio = rebalance.loc[asset, "desvio_peso"]
        peso_atual = rebalance.loc[asset, "peso_atual"]
        valor_atual = rebalance.loc[asset, "valor_atual"]

        if asset in MAX_WEIGHT and peso_atual > MAX_WEIGHT[asset]:
            excesso = peso_atual - MAX_WEIGHT[asset]
            excesso_usd = excesso * total_value

            if excesso_usd >= MIN_TRADE_USD:
                rebalance.loc[asset, "ajuste_usd"] = -excesso_usd
                rebalance.loc[asset, "motivo_execucao"] = (
                    "REDUCAO_CONCENTRACAO_FIDUCIARIA"
                )
                continue

        if abs(desvio) < MIN_DRIFT or abs(ajuste) < MIN_TRADE_USD:
            rebalance.loc[asset, "ajuste_usd"] = 0
            rebalance.loc[asset, "motivo_execucao"] = "SEM_DRIFT_RELEVANTE"
            continue

        if asset == "USDT-USD":
            usdt_min_value = USDT_MIN_WEIGHT * total_value
            usdt_excess_value = max(0, valor_atual - usdt_min_value)
            max_deploy_value = usdt_excess_value * MAX_USDT_DEPLOY

            if ajuste < 0 and macro_favoravel:
                allowed_sale = min(abs(ajuste), max_deploy_value)
                rebalance.loc[asset, "ajuste_usd"] = -allowed_sale
                rebalance.loc[asset, "motivo_execucao"] = (
                    "USDT_FINANCIA_RISCO_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_atencao:
                allowed_sale = min(abs(ajuste) * 0.50, max_deploy_value)
                rebalance.loc[asset, "ajuste_usd"] = -allowed_sale
                rebalance.loc[asset, "motivo_execucao"] = (
                    "USDT_FINANCIA_RISCO_COM_CAUTELA"
                )
                continue

            if ajuste < 0 and macro_defensivo:
                rebalance.loc[asset, "ajuste_usd"] = 0
                rebalance.loc[asset, "motivo_execucao"] = (
                    "USDT_PRESERVADO_MACRO_DEFENSIVO"
                )
                continue

            if ajuste > 0:
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "RECOMPOSICAO_LIQUIDEZ_OPERACIONAL"
                )
                continue

        if asset == "BTC-USD":
            if ajuste > 0 and macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "COMPRA_BTC_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = 0
                rebalance.loc[asset, "motivo_execucao"] = (
                    "BTC_MANTIDO_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_atencao:
                rebalance.loc[asset, "ajuste_usd"] = ajuste * 0.35
                rebalance.loc[asset, "motivo_execucao"] = (
                    "VENDA_BTC_PARCIAL_ATENCAO"
                )
                continue

            if ajuste < 0 and (macro_defensivo or macro_extremo):
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "VENDA_BTC_MACRO_DETERIORADO"
                )
                continue

            if ajuste > 0 and not macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = ajuste * 0.50
                rebalance.loc[asset, "motivo_execucao"] = (
                    "COMPRA_BTC_COM_CAUTELA"
                )
                continue

        if asset in GROWTH_BUY_ASSETS:
            if ajuste > 0 and macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "COMPRA_RISCO_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = 0
                rebalance.loc[asset, "motivo_execucao"] = (
                    "RISCO_MANTIDO_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_atencao:
                rebalance.loc[asset, "ajuste_usd"] = ajuste * 0.35
                rebalance.loc[asset, "motivo_execucao"] = (
                    "VENDA_RISCO_PARCIAL_ATENCAO"
                )
                continue

            if ajuste < 0 and (macro_defensivo or macro_extremo):
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "VENDA_RISCO_MACRO_DETERIORADO"
                )
                continue

            if ajuste > 0 and not macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = ajuste * 0.50
                rebalance.loc[asset, "motivo_execucao"] = (
                    "COMPRA_RISCO_COM_CAUTELA"
                )
                continue

        if asset == "TLT":
            tlt_floor_value = TLT_MIN_WEIGHT * total_value
            tlt_excess_value = max(0, valor_atual - tlt_floor_value)

            if macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = 0
                rebalance.loc[asset, "motivo_execucao"] = (
                    "TLT_MANTIDO_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_atencao:
                allowed_sale = min(abs(ajuste) * 0.50, tlt_excess_value)
                rebalance.loc[asset, "ajuste_usd"] = -allowed_sale
                rebalance.loc[asset, "motivo_execucao"] = (
                    "TLT_FINANCIA_RISCO_COM_CAUTELA"
                )
                continue

            if ajuste > 0 and macro_defensivo:
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "COMPRA_TLT_MACRO_DEFENSIVO"
                )
                continue

            rebalance.loc[asset, "ajuste_usd"] = 0
            rebalance.loc[asset, "motivo_execucao"] = "TLT_MANTIDO"
            continue

        if asset == "GLD":
            if macro_favoravel:
                rebalance.loc[asset, "ajuste_usd"] = 0
                rebalance.loc[asset, "motivo_execucao"] = (
                    "GLD_MANTIDO_MACRO_FAVORAVEL"
                )
                continue

            if ajuste < 0 and macro_atencao:
                rebalance.loc[asset, "ajuste_usd"] = 0
                rebalance.loc[asset, "motivo_execucao"] = (
                    "GLD_PRESERVADO_MACRO_ATENCAO"
                )
                continue

            if ajuste > 0 and (macro_defensivo or macro_extremo):
                rebalance.loc[asset, "ajuste_usd"] = ajuste
                rebalance.loc[asset, "motivo_execucao"] = (
                    "COMPRA_GLD_MACRO_DEFENSIVO"
                )
                continue

            rebalance.loc[asset, "ajuste_usd"] = 0
            rebalance.loc[asset, "motivo_execucao"] = (
                "GLD_REDUNDANCIA_SISTEMICA"
            )
            continue

        rebalance.loc[asset, "ajuste_usd"] = 0
        rebalance.loc[asset, "motivo_execucao"] = "SEM_REGRA_EXECUTAVEL"

    total_buys = rebalance.loc[
        rebalance["ajuste_usd"] > 0,
        "ajuste_usd",
    ].sum()

    total_sells = abs(
        rebalance.loc[
            rebalance["ajuste_usd"] < 0,
            "ajuste_usd",
        ].sum()
    )

    if total_buys > total_sells and total_buys > 0:
        scale_factor_cash = total_sells / total_buys if total_sells > 0 else 0
        buy_mask = rebalance["ajuste_usd"] > 0

        rebalance.loc[buy_mask, "ajuste_usd"] = (
            rebalance.loc[buy_mask, "ajuste_usd"] * scale_factor_cash
        )

        rebalance.loc[buy_mask, "motivo_execucao"] = (
            rebalance.loc[buy_mask, "motivo_execucao"]
            + "_AJUSTADO_A_CAIXA"
        )

    kill_switch = False
    kill_reasons = []

    gross_turnover_theoretical = (
        rebalance["ajuste_usd_bruto"].abs().sum() / total_value
    )

    gross_turnover_pre_limit = (
        rebalance["ajuste_usd"].abs().sum() / total_value
    )

    if gross_turnover_pre_limit > MAX_TURNOVER and gross_turnover_pre_limit > 0:
        scale_factor = MAX_TURNOVER / gross_turnover_pre_limit
        rebalance["ajuste_usd"] = rebalance["ajuste_usd"] * scale_factor
        turnover_status = "GIRO_REDUZIDO_PELO_LIMITE"
    else:
        turnover_status = "GIRO_DENTRO_DO_LIMITE"

    gross_turnover_final = (
        rebalance["ajuste_usd"].abs().sum() / total_value
    )

    rebalance["quantidade_ajuste"] = (
        rebalance["ajuste_usd"] / rebalance["preco_atual"]
    )

    def classify_action(x):
        if x > 0:
            return "COMPRAR"
        if x < 0:
            return "VENDER"
        return "MANTER"

    rebalance["acao"] = rebalance["ajuste_usd"].apply(classify_action)
    rebalance["prioridade"] = rebalance["desvio_peso"].abs()

    rebalance = rebalance.sort_values("prioridade", ascending=False)

    orders = rebalance[rebalance["acao"] != "MANTER"].copy()

    print("====================================================")
    print("PORTFOLIO ENGINE — REBALANCEADOR V8 LIVE PORTFOLIO")
    print("====================================================")
    print(f"Data UTC:                  {utc_now()}")
    print(f"Carteira fonte:            {LIVE_PORTFOLIO_PATH}")
    print(f"Valor total:               US${total_value:,.2f}")
    print(f"Macro Conviction:          {macro_conviction:.2f}")
    print(f"Macro Score:               {macro_score:.2f}")
    print(f"Macro Momentum:            {macro_momentum:.2f}")
    print(f"Confidence Score:          {confidence_score:.2f}")
    print("----------------------------------------------------")
    print(f"Macro Favorável:           {macro_favoravel}")
    print(f"Macro Atenção:             {macro_atencao}")
    print(f"Macro Defensivo:           {macro_defensivo}")
    print(f"Macro Extremo:             {macro_extremo}")
    print("----------------------------------------------------")
    print(f"Giro teórico:              {gross_turnover_theoretical:.2%}")
    print(f"Giro pré-limite:           {gross_turnover_pre_limit:.2%}")
    print(f"Giro final:                {gross_turnover_final:.2%}")
    print(f"Status de giro:            {turnover_status}")
    print("====================================================")

    return {
        "target_allocation": target_allocation,
        "rebalance": rebalance,
        "orders": orders,
        "total_value": total_value,
        "gross_turnover_theoretical": gross_turnover_theoretical,
        "gross_turnover_pre_limit": gross_turnover_pre_limit,
        "gross_turnover_final": gross_turnover_final,
        "turnover_status": turnover_status,
        "kill_switch": kill_switch,
        "kill_reasons": kill_reasons,
    }


def run_portfolio_engine(latest, latest_market):
    target_allocation = build_target_allocation(latest)

    context = run_rebalance(
        latest=latest,
        latest_market=latest_market,
        target_allocation=target_allocation,
    )

    return context
