# src/liquidity_engine.py

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

    positions_df["ativo"] = positions_df["ativo"].astype(str)
    positions_df["valor_atual"] = positions_df["valor_atual"].astype(float)
    positions_df["peso_atual"] = positions_df["peso_atual"].astype(float)

    return positions_df


def get_haircuts():
    return {
        "USDT-USD": 0.02,
        "TLT": 0.03,
        "GLD": 0.03,
        "VOO": 0.02,
        "INDA": 0.05,
        "BOTZ": 0.08,
        "BTC-USD": 0.10,
    }


def classify_liquidity_score(haircut_pct):
    if haircut_pct <= 5:
        return 90, "ROBUSTO"

    if haircut_pct <= 10:
        return 75, "ACEITAVEL"

    if haircut_pct <= 15:
        return 55, "FRAGIL"

    return 35, "CRITICO"


def run_liquidity_engine(rebalance):

    timestamp_utc = utc_now()

    positions_df = build_positions_df(rebalance)

    haircuts = get_haircuts()

    positions_df["haircut_pct"] = (
        positions_df["ativo"]
        .map(haircuts)
        .fillna(0.10)
    )

    positions_df["valor_liquido"] = (
        positions_df["valor_atual"]
        * (1 - positions_df["haircut_pct"])
    )

    gross_value = float(
        positions_df["valor_atual"].sum()
    )

    liquid_value = float(
        positions_df["valor_liquido"].sum()
    )

    aggregate_haircut_pct = (
        (gross_value - liquid_value)
        / gross_value
        if gross_value > 0
        else 0
    )

    liquidity_score, liquidity_level = (
        classify_liquidity_score(
            aggregate_haircut_pct * 100
        )
    )

    liquidity_audit = positions_df[[
        "ativo",
        "valor_atual",
        "haircut_pct",
        "valor_liquido",
    ]].copy()

    liquidity_audit["timestamp_utc"] = timestamp_utc

    liquidity_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "gross_value": round(gross_value, 2),
        "liquid_value": round(liquid_value, 2),
        "aggregate_haircut_pct": round(
            aggregate_haircut_pct * 100,
            2,
        ),
        "liquidity_score": liquidity_score,
        "liquidity_level": liquidity_level,
    }])

    ensure_outputs_dir()

    liquidity_audit.to_csv(
        os.path.join(
            OUTPUT_DIR,
            "liquidity_audit.csv",
        ),
        index=False,
    )

    liquidity_summary.to_csv(
        os.path.join(
            OUTPUT_DIR,
            "liquidity_summary.csv",
        ),
        index=False,
    )

    print("====================================================")
    print("LIQUIDITY ENGINE")
    print("====================================================")
    print(f"Valor Bruto:      US${gross_value:,.2f}")
    print(f"Valor Liquido:    US${liquid_value:,.2f}")
    print(f"Haircut Agregado: {aggregate_haircut_pct:.2%}")
    print(f"Liquidity Score:  {liquidity_score}")
    print(f"Liquidity Level:  {liquidity_level}")
    print("====================================================")

    return {
        "liquidity_audit": liquidity_audit,
        "liquidity_summary": liquidity_summary,
    }
