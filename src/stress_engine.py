# src/stress_engine.py

import os
from datetime import datetime, timezone

import pandas as pd


OUTPUT_DIR = "outputs"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_outputs_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def build_positions_df(rebalance):
    positions_df = rebalance.copy().reset_index()

    if "index" in positions_df.columns:
        positions_df = positions_df.rename(columns={"index": "ativo"})

    if "ativo" not in positions_df.columns:
        positions_df = positions_df.rename(columns={positions_df.columns[0]: "ativo"})

    required_columns = ["ativo", "valor_atual", "peso_atual"]
    missing = [col for col in required_columns if col not in positions_df.columns]

    if missing:
        raise ValueError(f"rebalance com colunas ausentes: {missing}")

    positions_df["ativo"] = positions_df["ativo"].astype(str).str.strip()
    positions_df["valor_atual"] = positions_df["valor_atual"].astype(float)
    positions_df["peso_atual"] = positions_df["peso_atual"].astype(float)

    return positions_df


def ttr_midpoint(ttr_range):
    if ttr_range == "indefinido":
        return 999

    low, high = ttr_range.split("-")
    return (float(low) + float(high)) / 2


def classify_color(drawdown_pct, ttr_range, forced_selling, permanent_impairment=False):
    if forced_selling or permanent_impairment:
        return "VERMELHO"

    ttr_mid = ttr_midpoint(ttr_range)

    if drawdown_pct <= 20 and ttr_mid <= 36:
        return "VERDE"

    if drawdown_pct <= 35 and ttr_mid <= 60:
        return "AMARELO"

    return "VERMELHO"


def classify_stress_summary(max_drawdown, red_count, yellow_count, forced_selling_any):
    if forced_selling_any:
        return 40, "CRITICO"

    if red_count >= 2:
        return 40, "CRITICO"

    if red_count == 1:
        if max_drawdown <= 35:
            return 60, "FRAGIL_COM_RESSALVAS"
        return 55, "FRAGIL"

    if max_drawdown <= 20 and yellow_count == 0:
        return 90, "ROBUSTO"

    if max_drawdown <= 35:
        return 75, "ACEITAVEL_COM_RESSALVAS"

    return 55, "FRAGIL"


def run_stress_engine(
    rebalance,
    monthly_expense_usd=2000,
    survival_assets=None,
):
    timestamp_utc = utc_now()

    if survival_assets is None:
        survival_assets = ["USDT-USD", "TLT", "GLD"]

    positions_df = build_positions_df(rebalance)

    total_value = float(positions_df["valor_atual"].sum())
    weights = dict(zip(positions_df["ativo"], positions_df["peso_atual"]))

    survival_value = float(
        positions_df[
            positions_df["ativo"].isin(survival_assets)
        ]["valor_atual"].sum()
    )

    runway_months = (
        survival_value / monthly_expense_usd
        if monthly_expense_usd > 0
        else 0
    )

    scenarios = {
        "2008_LIKE": {
            "BTC-USD": -0.65,
            "USDT-USD": 0.00,
            "GLD": 0.10,
            "VOO": -0.45,
            "TLT": 0.20,
            "BOTZ": -0.55,
            "INDA": -0.50,
            "ttr": "24-60",
        },
        "2020_LIKE": {
            "BTC-USD": -0.50,
            "USDT-USD": 0.00,
            "GLD": 0.08,
            "VOO": -0.35,
            "TLT": 0.15,
            "BOTZ": -0.45,
            "INDA": -0.40,
            "ttr": "6-18",
        },
        "2022_LIKE": {
            "BTC-USD": -0.60,
            "USDT-USD": 0.00,
            "GLD": -0.05,
            "VOO": -0.25,
            "TLT": -0.30,
            "BOTZ": -0.45,
            "INDA": -0.20,
            "ttr": "12-36",
        },
        "CRIPTO_INVERNO": {
            "BTC-USD": -0.75,
            "USDT-USD": 0.00,
            "GLD": 0.05,
            "VOO": -0.15,
            "TLT": 0.05,
            "BOTZ": -0.25,
            "INDA": -0.15,
            "ttr": "24-60",
        },
        "CHOQUE_REGULATORIO_CRIPTO": {
            "BTC-USD": -0.35,
            "USDT-USD": -0.10,
            "GLD": 0.00,
            "VOO": -0.05,
            "TLT": -0.03,
            "BOTZ": -0.10,
            "INDA": -0.05,
            "ttr": "12-36",
        },
        "CHOQUE_STABLECOIN_CUSTODIA": {
            "BTC-USD": -0.10,
            "USDT-USD": -0.30,
            "GLD": 0.00,
            "VOO": -0.03,
            "TLT": -0.02,
            "BOTZ": -0.05,
            "INDA": -0.03,
            "ttr": "12-36",
        },
    }

    rows = []

    for scenario, shocks in scenarios.items():
        portfolio_return = 0.0

        for asset, weight in weights.items():
            portfolio_return += weight * shocks.get(asset, 0.0)

        drawdown_pct = abs(min(0.0, portfolio_return)) * 100
        ttr_range = shocks["ttr"]

        forced_selling = False
        forced_selling_reason = ""
        permanent_impairment = False

        if runway_months < 12:
            forced_selling = True
            forced_selling_reason = "RUNWAY_INFERIOR_12_MESES"

        if scenario == "CHOQUE_STABLECOIN_CUSTODIA":
            usdt_weight = weights.get("USDT-USD", 0.0)
            tlt_weight = weights.get("TLT", 0.0)
            gld_weight = weights.get("GLD", 0.0)

            survival_weight = usdt_weight + tlt_weight + gld_weight
            stablecoin_survival_ratio = usdt_weight / max(survival_weight, 0.0001)

            if usdt_weight > 0.60 and stablecoin_survival_ratio > 0.80:
                permanent_impairment = True
                ttr_range = "indefinido"

                if runway_months < 12:
                    forced_selling = True
                    forced_selling_reason = "DEPENDENCIA_EXTREMA_DE_STABLECOIN"

        color = classify_color(
            drawdown_pct=drawdown_pct,
            ttr_range=ttr_range,
            forced_selling=forced_selling,
            permanent_impairment=permanent_impairment,
        )

        rows.append({
            "timestamp_utc": timestamp_utc,
            "cenario": scenario,
            "drawdown_pct": round(drawdown_pct, 2),
            "ttr_estimado_meses": ttr_range,
            "forced_selling": forced_selling,
            "forced_selling_reason": forced_selling_reason,
            "permanent_impairment": permanent_impairment,
            "cor": color,
            "runway_meses": round(runway_months, 1),
        })

    stress_results = pd.DataFrame(rows)

    max_drawdown = float(stress_results["drawdown_pct"].max())
    avg_drawdown = float(stress_results["drawdown_pct"].mean())
    red_count = int((stress_results["cor"] == "VERMELHO").sum())
    yellow_count = int((stress_results["cor"] == "AMARELO").sum())
    green_count = int((stress_results["cor"] == "VERDE").sum())
    forced_selling_any = bool(stress_results["forced_selling"].any())

    stress_score, stress_level = classify_stress_summary(
        max_drawdown=max_drawdown,
        red_count=red_count,
        yellow_count=yellow_count,
        forced_selling_any=forced_selling_any,
    )

    stress_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "avg_drawdown_pct": round(avg_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown, 2),
        "green_count": green_count,
        "yellow_count": yellow_count,
        "red_count": red_count,
        "forced_selling_any": forced_selling_any,
        "stress_score": stress_score,
        "stress_level": stress_level,
    }])

    ensure_outputs_dir()

    stress_results.to_csv(
        os.path.join(OUTPUT_DIR, "stress_results_v2.csv"),
        index=False,
    )

    stress_summary.to_csv(
        os.path.join(OUTPUT_DIR, "stress_summary_v2.csv"),
        index=False,
    )

    print("====================================================")
    print("STRESS ENGINE — TTR + FORCED SELLING V7")
    print("====================================================")
    print(f"Data UTC:              {timestamp_utc}")
    print(f"Valor total carteira:  US${total_value:,.2f}")
    print(f"Runway estimado:       {runway_months:.1f} meses")
    print("----------------------------------------------------")
    print(stress_results[[
        "cenario",
        "drawdown_pct",
        "ttr_estimado_meses",
        "forced_selling",
        "permanent_impairment",
        "cor",
    ]].to_string(index=False))
    print("----------------------------------------------------")
    print(f"Stress Score:          {stress_score}")
    print(f"Stress Level:          {stress_level}")
    print(f"Forced Selling:        {forced_selling_any}")
    print("====================================================")

    return {
        "stress_results": stress_results,
        "stress_summary": stress_summary,
    }
