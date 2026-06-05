# src/risk_budget_engine.py

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


def get_vol_proxy():
    return {
        "BTC-USD": 0.75,
        "USDT-USD": 0.02,
        "GLD": 0.18,
        "VOO": 0.20,
        "TLT": 0.18,
        "BOTZ": 0.30,
        "INDA": 0.25,
    }


def classify_risk_budget(max_risk_contribution):
    if max_risk_contribution <= 0.35:
        return 90, "ROBUSTO"

    if max_risk_contribution <= 0.50:
        return 75, "ACEITAVEL"

    if max_risk_contribution <= 0.65:
        return 55, "CONCENTRADO"

    return 35, "CRITICO"


def run_risk_budget_engine(rebalance):
    timestamp_utc = utc_now()

    positions_df = build_positions_df(rebalance)
    vol_proxy = get_vol_proxy()

    positions_df["vol_proxy"] = positions_df["ativo"].map(vol_proxy).fillna(0.25)

    positions_df["risk_units"] = (
        positions_df["peso_atual"].abs()
        * positions_df["vol_proxy"]
    )

    total_risk_units = positions_df["risk_units"].sum()

    if total_risk_units > 0:
        positions_df["risk_contribution_pct"] = (
            positions_df["risk_units"] / total_risk_units
        )
    else:
        positions_df["risk_contribution_pct"] = 0.0

    positions_df = positions_df.sort_values(
        "risk_contribution_pct",
        ascending=False,
    )

    max_risk_contribution = float(
        positions_df["risk_contribution_pct"].max()
    )

    top_asset = str(
        positions_df.iloc[0]["ativo"]
        if not positions_df.empty
        else "N/D"
    )

    risk_budget_score, risk_budget_level = classify_risk_budget(
        max_risk_contribution
    )

    risk_budget = positions_df[[
        "ativo",
        "valor_atual",
        "peso_atual",
        "vol_proxy",
        "risk_units",
        "risk_contribution_pct",
    ]].copy()

    risk_budget["timestamp_utc"] = timestamp_utc

    risk_budget_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "risk_budget_score": risk_budget_score,
        "risk_budget_level": risk_budget_level,
        "max_risk_contribution_pct": round(max_risk_contribution * 100, 2),
        "top_risk_asset": top_asset,
        "total_risk_units": round(float(total_risk_units), 6),
    }])

    ensure_outputs_dir()

    risk_budget.to_csv(
        os.path.join(OUTPUT_DIR, "risk_budget.csv"),
        index=False,
    )

    risk_budget_summary.to_csv(
        os.path.join(OUTPUT_DIR, "risk_budget_summary.csv"),
        index=False,
    )

    print("====================================================")
    print("RISK BUDGET ENGINE")
    print("====================================================")
    print(f"Data UTC:              {timestamp_utc}")
    print(f"Top Risk Asset:        {top_asset}")
    print(f"Max Risk Contribution: {max_risk_contribution:.2%}")
    print(f"Risk Budget Score:     {risk_budget_score}")
    print(f"Risk Budget Level:     {risk_budget_level}")
    print("----------------------------------------------------")
    print(risk_budget[[
        "ativo",
        "peso_atual",
        "vol_proxy",
        "risk_contribution_pct",
    ]].to_string(index=False))
    print("====================================================")

    return {
        "risk_budget": risk_budget,
        "risk_budget_summary": risk_budget_summary,
    }
