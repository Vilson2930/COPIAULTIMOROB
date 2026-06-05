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

    required_columns = ["ativo", "valor_atual"]
    missing = [col for col in required_columns if col not in positions_df.columns]

    if missing:
        raise ValueError(f"rebalance com colunas ausentes: {missing}")

    positions_df["ativo"] = positions_df["ativo"].astype(str).str.strip()
    positions_df["valor_atual"] = positions_df["valor_atual"].astype(float)

    return positions_df


def get_counterparty_map():
    """
    Mapa de contraparte/custódia.

    Observação importante:
    - BTC-USD foi alterado de BINANCE para SELF_CUSTODY.
    - Isso corrige o risco de contraparte/custódia.
    - Isso NÃO altera o risco de mercado do BTC no Risk Budget Engine.
    """

    return {
        "BTC-USD": ("SELF_CUSTODY", 95),
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


def classify_concentration(max_exposure_pct):
    if max_exposure_pct <= 0.35:
        return "ROBUSTA"

    if max_exposure_pct <= 0.50:
        return "ACEITAVEL"

    if max_exposure_pct <= 0.65:
        return "CONCENTRADA"

    return "CRITICA"


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

    total_value = float(positions_df["valor_atual"].sum())

    if total_value <= 0:
        raise ValueError("Valor total da carteira inválido para Counterparty Engine.")

    counterparty_audit = (
        positions_df.groupby("counterparty", as_index=False)
        .agg(
            exposure_usd=("valor_atual", "sum"),
            avg_score=("counterparty_score", "mean"),
        )
    )

    counterparty_audit["exposure_pct"] = (
        counterparty_audit["exposure_usd"] / total_value
    )

    counterparty_audit["weighted_score"] = (
        counterparty_audit["avg_score"]
        * counterparty_audit["exposure_pct"]
    )

    counterparty_score = round(
        float(counterparty_audit["weighted_score"].sum()),
        2,
    )

    counterparty_level = classify_counterparty_score(counterparty_score)

    counterparty_audit = counterparty_audit.sort_values(
        "exposure_pct",
        ascending=False,
    )

    largest_counterparty = str(counterparty_audit.iloc[0]["counterparty"])
    largest_counterparty_exposure_pct = float(
        counterparty_audit.iloc[0]["exposure_pct"]
    )

    concentration_level = classify_concentration(
        largest_counterparty_exposure_pct
    )

    critical_flags = []

    if counterparty_score < 60:
        critical_flags.append("COUNTERPARTY_SCORE_CRITICO")

    if largest_counterparty_exposure_pct > 0.50:
        critical_flags.append("CONCENTRACAO_CONTRAPARTE_ACIMA_50")

    if largest_counterparty_exposure_pct > 0.65:
        critical_flags.append("CONCENTRACAO_CONTRAPARTE_ACIMA_65")

    counterparty_audit["timestamp_utc"] = timestamp_utc

    counterparty_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "counterparty_score": counterparty_score,
        "counterparty_level": counterparty_level,
        "largest_counterparty": largest_counterparty,
        "largest_counterparty_exposure_pct": round(
            largest_counterparty_exposure_pct * 100,
            2,
        ),
        "concentration_level": concentration_level,
        "critical_flags": " | ".join(critical_flags),
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
    print(f"Data UTC:                  {timestamp_utc}")
    print(f"Counterparty Score:        {counterparty_score}")
    print(f"Counterparty Level:        {counterparty_level}")
    print(f"Maior Contraparte:         {largest_counterparty}")
    print(f"Exposição Maior Contrap.:  {largest_counterparty_exposure_pct:.2%}")
    print(f"Concentration Level:       {concentration_level}")

    if critical_flags:
        print(f"Critical Flags:            {' | '.join(critical_flags)}")
    else:
        print("Critical Flags:            Nenhuma")

    print("----------------------------------------------------")
    print(counterparty_audit[[
        "counterparty",
        "exposure_usd",
        "avg_score",
        "exposure_pct",
        "weighted_score",
    ]].to_string(index=False))
    print("====================================================")

    return {
        "counterparty_audit": counterparty_audit,
        "counterparty_summary": counterparty_summary,
    }
