# src/risk_budget_engine.py

import os
from datetime import datetime, timezone

import numpy as np
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


def get_correlation_proxy():
    return {
        ("BTC-USD", "USDT-USD"): 0.00,
        ("BTC-USD", "GLD"): 0.10,
        ("BTC-USD", "VOO"): 0.45,
        ("BTC-USD", "TLT"): -0.15,
        ("BTC-USD", "BOTZ"): 0.55,
        ("BTC-USD", "INDA"): 0.35,

        ("USDT-USD", "GLD"): 0.00,
        ("USDT-USD", "VOO"): 0.00,
        ("USDT-USD", "TLT"): 0.00,
        ("USDT-USD", "BOTZ"): 0.00,
        ("USDT-USD", "INDA"): 0.00,

        ("GLD", "VOO"): -0.10,
        ("GLD", "TLT"): 0.25,
        ("GLD", "BOTZ"): -0.05,
        ("GLD", "INDA"): -0.05,

        ("VOO", "TLT"): -0.25,
        ("VOO", "BOTZ"): 0.75,
        ("VOO", "INDA"): 0.65,

        ("TLT", "BOTZ"): -0.15,
        ("TLT", "INDA"): -0.20,

        ("BOTZ", "INDA"): 0.55,
    }


def build_covariance_matrix(assets, vol_proxy, corr_proxy):
    n = len(assets)
    cov = np.zeros((n, n))

    for i, a in enumerate(assets):
        for j, b in enumerate(assets):
            vol_a = vol_proxy.get(a, 0.25)
            vol_b = vol_proxy.get(b, 0.25)

            if a == b:
                corr = 1.0
            else:
                corr = corr_proxy.get((a, b), corr_proxy.get((b, a), 0.25))

            cov[i, j] = vol_a * vol_b * corr

    return cov


def classify_risk_budget(max_abs_contribution):
    if max_abs_contribution <= 0.35:
        return 90, "ROBUSTO"

    if max_abs_contribution <= 0.50:
        return 75, "ACEITAVEL"

    if max_abs_contribution <= 0.65:
        return 55, "CONCENTRADO"

    return 35, "CRITICO"


def run_risk_budget_engine(rebalance):
    timestamp_utc = utc_now()

    positions_df = build_positions_df(rebalance)

    vol_proxy = get_vol_proxy()
    corr_proxy = get_correlation_proxy()

    assets = positions_df["ativo"].tolist()
    weights = positions_df["peso_atual"].to_numpy(dtype=float)

    covariance_matrix = build_covariance_matrix(
        assets=assets,
        vol_proxy=vol_proxy,
        corr_proxy=corr_proxy,
    )

    portfolio_variance = float(weights.T @ covariance_matrix @ weights)
    portfolio_volatility = portfolio_variance ** 0.5 if portfolio_variance > 0 else 0.0

    marginal_risk = covariance_matrix @ weights

    if portfolio_variance > 0:
        risk_contribution_raw = weights * marginal_risk / portfolio_variance
    else:
        risk_contribution_raw = np.zeros(len(weights))

    abs_contribution = np.abs(risk_contribution_raw)
    abs_sum = abs_contribution.sum()

    if abs_sum > 0:
        risk_contribution_abs_pct = abs_contribution / abs_sum
    else:
        risk_contribution_abs_pct = np.zeros(len(weights))

    positive_contribution = np.maximum(risk_contribution_raw, 0)
    positive_sum = positive_contribution.sum()

    if positive_sum > 0:
        risk_contribution_positive_pct = positive_contribution / positive_sum
    else:
        risk_contribution_positive_pct = np.zeros(len(weights))

    hedge_flag = risk_contribution_raw < 0

    positions_df["vol_proxy"] = positions_df["ativo"].map(vol_proxy).fillna(0.25)
    positions_df["marginal_risk"] = marginal_risk
    positions_df["risk_contribution_raw"] = risk_contribution_raw
    positions_df["risk_contribution_abs_pct"] = risk_contribution_abs_pct
    positions_df["risk_contribution_positive_pct"] = risk_contribution_positive_pct
    positions_df["hedge_flag"] = hedge_flag

    positions_df = positions_df.sort_values(
        "risk_contribution_abs_pct",
        ascending=False,
    )

    max_risk_contribution = float(
        positions_df["risk_contribution_abs_pct"].max()
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
        "marginal_risk",
        "risk_contribution_raw",
        "risk_contribution_abs_pct",
        "risk_contribution_positive_pct",
        "hedge_flag",
    ]].copy()

    risk_budget["timestamp_utc"] = timestamp_utc

    risk_budget_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "portfolio_volatility_proxy": round(portfolio_volatility, 6),
        "portfolio_variance_proxy": round(portfolio_variance, 6),
        "risk_budget_score": risk_budget_score,
        "risk_budget_level": risk_budget_level,
        "max_risk_contribution_pct": round(max_risk_contribution * 100, 2),
        "top_risk_asset": top_asset,
        "method": "COVARIANCE_ABS_CONTRIBUTION",
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
    print("RISK BUDGET ENGINE — COVARIANCE ABS CONTRIBUTION")
    print("====================================================")
    print(f"Data UTC:              {timestamp_utc}")
    print(f"Metodo:                COVARIANCE_ABS_CONTRIBUTION")
    print(f"Portfolio Vol Proxy:   {portfolio_volatility:.2%}")
    print(f"Top Risk Asset:        {top_asset}")
    print(f"Max Risk Contribution: {max_risk_contribution:.2%}")
    print(f"Risk Budget Score:     {risk_budget_score}")
    print(f"Risk Budget Level:     {risk_budget_level}")
    print("----------------------------------------------------")
    print(risk_budget[[
        "ativo",
        "peso_atual",
        "vol_proxy",
        "risk_contribution_raw",
        "risk_contribution_abs_pct",
        "hedge_flag",
    ]].to_string(index=False))
    print("====================================================")

    return {
        "risk_budget": risk_budget,
        "risk_budget_summary": risk_budget_summary,
    }
