# src/counterparty_engine.py

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

    return positions_df


def get_counterparty_map():

    return {
        "BTC-USD": ("BINANCE", 70),
        "USDT-USD": ("TETHER", 65),
        "VOO": ("BLACKROCK", 98),
        "TLT": ("BLACKROCK", 98),
        "GLD": ("STATE_STREET", 95),
        "BOTZ": ("GLOBAL_X", 85),
        "INDA": ("BLACKROCK", 98),
    }


def classify_counterparty_score(score):

    if score >= 90:
        return "ROBUSTO"

    if score >= 75:
        return "ACEITAVEL"

    if score >= 60:
        return "CONCENTRADO"

    return "CRITICO"


def run_counterparty_engine(rebalance):

    timestamp_utc = utc_now()

    positions_df = build_positions_df(rebalance)

    cp_map = get_counterparty_map()

    positions_df["counterparty"] = positions_df["ativo"].apply(
        lambda x: cp_map.get(x, ("OUTROS", 75))[0]
    )

    positions_df["counterparty_score"] = positions_df["ativo"].apply(
        lambda x: cp_map.get(x, ("OUTROS", 75))[1]
    )

    total_value = positions_df["valor_atual"].sum()

    cp_exposure = (
        positions_df.groupby("counterparty", as_index=False)
        .agg(
            exposure_usd=("valor_atual", "sum"),
            avg_score=("counterparty_score", "mean"),
        )
    )

    cp_exposure["exposure_pct"] = (
        cp_exposure["exposure_usd"] / total_value
    )

    weighted_score = (
        cp_exposure["avg_score"]
        * cp_exposure["exposure_pct"]
    ).sum()

    counterparty_score = round(float(weighted_score), 2)

    counterparty_level = classify_counterparty_score(
        counterparty_score
    )

    largest_cp = cp_exposure.sort_values(
        "exposure_pct",
        ascending=False,
    ).iloc[0]["counterparty"]

    counterparty_audit = cp_exposure.copy()

    counterparty_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "counterparty_score": counterparty_score,
        "counterparty_level": counterparty_level,
        "largest_counterparty": largest_cp,
    }])

    ensure_outputs_dir()

    counterparty_audit.to_csv(
        os.path.join(
            OUTPUT_DIR,
            "counterparty_audit.csv",
        ),
        index=False,
    )

    counterparty_summary.to_csv(
        os.path.join(
            OUTPUT_DIR,
            "counterparty_summary.csv",
        ),
        index=False,
    )

    print("====================================================")
    print("COUNTERPARTY ENGINE")
    print("====================================================")
    print(f"Data UTC:               {timestamp_utc}")
    print(f"Counterparty Score:     {counterparty_score}")
    print(f"Counterparty Level:     {counterparty_level}")
    print(f"Maior Contraparte:      {largest_cp}")
    print("----------------------------------------------------")
    print(cp_exposure.to_string(index=False))
    print("====================================================")

    return {
        "counterparty_audit": counterparty_audit,
        "counterparty_summary": counterparty_summary,
    }
