import os
import pandas as pd
from datetime import datetime, timezone

OUTPUT_DIR = "outputs"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def run_stress_engine(
    rebalance,
    monthly_expense_usd=2000,
):

    timestamp_utc = utc_now()

    positions_df = rebalance.copy().reset_index()

    if "index" in positions_df.columns:
        positions_df.rename(columns={"index": "ativo"}, inplace=True)

    weights = dict(
        zip(
            positions_df["ativo"],
            positions_df["peso_atual"]
        )
    )

    survival_assets = [
        "USDT-USD",
        "TLT",
        "GLD"
    ]

    survival_weight = sum(
        weights.get(asset, 0)
        for asset in survival_assets
    )

    runway_months = (
        survival_weight * 100000
    ) / monthly_expense_usd

    scenarios = {
        "2008_LIKE": {
            "BTC-USD": -0.65,
            "VOO": -0.45,
            "BOTZ": -0.55,
            "INDA": -0.50,
            "TLT": 0.20,
            "GLD": 0.10,
            "USDT-USD": 0.00,
            "ttr": "24-60",
        },
        "2020_LIKE": {
            "BTC-USD": -0.50,
            "VOO": -0.35,
            "BOTZ": -0.45,
            "INDA": -0.40,
            "TLT": 0.15,
            "GLD": 0.08,
            "USDT-USD": 0.00,
            "ttr": "6-18",
        },
        "2022_LIKE": {
            "BTC-USD": -0.60,
            "VOO": -0.25,
            "BOTZ": -0.45,
            "INDA": -0.20,
            "TLT": -0.30,
            "GLD": -0.05,
            "USDT-USD": 0.00,
            "ttr": "12-36",
        },
        "CRIPTO_INVERNO": {
            "BTC-USD": -0.75,
            "VOO": -0.15,
            "BOTZ": -0.25,
            "INDA": -0.15,
            "TLT": 0.05,
            "GLD": 0.05,
            "USDT-USD": 0.00,
            "ttr": "24-60",
        },
        "CHOQUE_REGULATORIO_CUSTODIA": {
            "BTC-USD": -0.35,
            "VOO": -0.05,
            "BOTZ": -0.10,
            "INDA": -0.05,
            "TLT": -0.03,
            "GLD": 0.00,
            "USDT-USD": -0.20,
            "ttr": "indefinido",
        },
    }

    rows = []

    for scenario, shock in scenarios.items():

        portfolio_return = 0

        for asset, weight in weights.items():
            portfolio_return += (
                weight * shock.get(asset, 0)
            )

        drawdown = abs(min(0, portfolio_return)) * 100

        forced_selling = (
            runway_months < 12
        )

        if (
            scenario ==
            "CHOQUE_REGULATORIO_CUSTODIA"
            and weights.get("USDT-USD", 0) > 0.15
        ):
            forced_selling = True

        if forced_selling:
            color = "VERMELHO"
        elif drawdown <= 20:
            color = "VERDE"
        elif drawdown <= 35:
            color = "AMARELO"
        else:
            color = "VERMELHO"

        rows.append({
            "timestamp_utc": timestamp_utc,
            "cenario": scenario,
            "drawdown_pct": round(drawdown, 2),
            "ttr_estimado": shock["ttr"],
            "forced_selling": forced_selling,
            "cor": color,
            "runway_meses": round(
                runway_months,
                1
            ),
        })

    stress_results = pd.DataFrame(rows)

    os.makedirs(
        OUTPUT_DIR,
        exist_ok=True
    )

    stress_results.to_csv(
        f"{OUTPUT_DIR}/stress_results_v2.csv",
        index=False
    )

    print("====================================================")
    print("STRESS ENGINE")
    print("====================================================")
    print(stress_results.to_string(index=False))
    print("====================================================")

    return {
        "stress_results": stress_results
    }
