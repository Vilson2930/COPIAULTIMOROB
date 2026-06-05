# src/risk_budget_engine.py

import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd


OUTPUT_DIR = "outputs"
LOOKBACK_DAYS = 252


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


def asset_column_map():
    return {
        "BTC-USD": ["BTC-USD", "btc", "BTC", "bitcoin"],
        "USDT-USD": ["USDT-USD", "usdt", "USDT"],
        "GLD": ["GLD", "gld"],
        "VOO": ["VOO", "voo"],
        "TLT": ["TLT", "tlt"],
        "BOTZ": ["BOTZ", "botz"],
        "INDA": ["INDA", "inda"],
    }


def get_vol_fallback():
    return {
        "BTC-USD": 0.75,
        "USDT-USD": 0.02,
        "GLD": 0.18,
        "VOO": 0.20,
        "TLT": 0.18,
        "BOTZ": 0.30,
        "INDA": 0.25,
    }


def get_corr_fallback():
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


def build_covariance_fallback(assets):
    vol = get_vol_fallback()
    corr = get_corr_fallback()
    n = len(assets)
    cov = np.zeros((n, n))

    for i, a in enumerate(assets):
        for j, b in enumerate(assets):
            vol_a = vol.get(a, 0.25)
            vol_b = vol.get(b, 0.25)

            if a == b:
                c = 1.0
            else:
                c = corr.get((a, b), corr.get((b, a), 0.25))

            cov[i, j] = vol_a * vol_b * c

    return cov, {a: vol.get(a, 0.25) for a in assets}, "COVARIANCE_FALLBACK_PROXY"


def extract_price_matrix(market_data, assets):
    if market_data is None or market_data.empty:
        return None

    df = market_data.copy()
    col_map = asset_column_map()
    prices = pd.DataFrame(index=df.index)

    lower_cols = {str(c).lower(): c for c in df.columns}

    for asset in assets:
        found_col = None

        for candidate in col_map.get(asset, [asset]):
            if candidate in df.columns:
                found_col = candidate
                break

            if candidate.lower() in lower_cols:
                found_col = lower_cols[candidate.lower()]
                break

        if found_col is not None:
            prices[asset] = pd.to_numeric(df[found_col], errors="coerce")

    if prices.empty:
        return None

    prices = prices.replace([np.inf, -np.inf], np.nan)
    prices = prices.dropna(how="all")
    prices = prices.ffill().dropna()

    valid_assets = [asset for asset in assets if asset in prices.columns]

    if len(valid_assets) < 2:
        return None

    return prices[valid_assets]


def build_covariance_real(market_data, assets):
    prices = extract_price_matrix(market_data, assets)

    if prices is None or prices.empty:
        return build_covariance_fallback(assets)

    returns = prices.pct_change().replace([np.inf, -np.inf], np.nan).dropna()

    if len(returns) < 60:
        return build_covariance_fallback(assets)

    returns = returns.tail(LOOKBACK_DAYS)

    realized_cov = returns.cov() * 252
    realized_vol = returns.std() * np.sqrt(252)

    cov = pd.DataFrame(
        0.0,
        index=assets,
        columns=assets,
    )

    vol_fallback = get_vol_fallback()
    corr_fallback = get_corr_fallback()

    for a in assets:
        for b in assets:
            if a in realized_cov.index and b in realized_cov.columns:
                value = realized_cov.loc[a, b]

                if pd.notna(value):
                    cov.loc[a, b] = float(value)
                    continue

            vol_a = vol_fallback.get(a, 0.25)
            vol_b = vol_fallback.get(b, 0.25)

            if a == b:
                c = 1.0
            else:
                c = corr_fallback.get((a, b), corr_fallback.get((b, a), 0.25))

            cov.loc[a, b] = vol_a * vol_b * c

    vol_used = {}

    for asset in assets:
        if asset in realized_vol.index and pd.notna(realized_vol.loc[asset]):
            vol_used[asset] = float(realized_vol.loc[asset])
        else:
            vol_used[asset] = vol_fallback.get(asset, 0.25)

    return cov.to_numpy(dtype=float), vol_used, "COVARIANCE_REAL_252D"


def classify_risk_budget(max_abs_contribution):
    if max_abs_contribution <= 0.25:
        return 95, "EXCELENTE"

    if max_abs_contribution <= 0.40:
        return 85, "ROBUSTO"

    if max_abs_contribution <= 0.55:
        return 70, "ACEITAVEL"

    if max_abs_contribution <= 0.75:
        return 55, "CONCENTRADO"

    return 35, "CRITICO"


def run_risk_budget_engine(rebalance, market_data=None):
    timestamp_utc = utc_now()

    positions_df = build_positions_df(rebalance)

    assets = positions_df["ativo"].tolist()
    weights = positions_df["peso_atual"].to_numpy(dtype=float)

    covariance_matrix, vol_used, method = build_covariance_real(
        market_data=market_data,
        assets=assets,
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

    hedge_flag = risk_contribution_raw < 0

    positions_df["vol_realizada_ou_proxy"] = positions_df["ativo"].map(vol_used).fillna(0.25)
    positions_df["marginal_risk"] = marginal_risk
    positions_df["risk_contribution_raw"] = risk_contribution_raw
    positions_df["risk_contribution_abs_pct"] = risk_contribution_abs_pct
    positions_df["hedge_flag"] = hedge_flag

    positions_df = positions_df.sort_values(
        "risk_contribution_abs_pct",
        ascending=False,
    )

    max_risk_contribution = float(positions_df["risk_contribution_abs_pct"].max())

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
        "vol_realizada_ou_proxy",
        "marginal_risk",
        "risk_contribution_raw",
        "risk_contribution_abs_pct",
        "hedge_flag",
    ]].copy()

    risk_budget["timestamp_utc"] = timestamp_utc
    risk_budget["method"] = method

    risk_budget_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "portfolio_volatility_proxy": round(portfolio_volatility, 6),
        "portfolio_variance_proxy": round(portfolio_variance, 6),
        "risk_budget_score": risk_budget_score,
        "risk_budget_level": risk_budget_level,
        "max_risk_contribution_pct": round(max_risk_contribution * 100, 2),
        "top_risk_asset": top_asset,
        "method": method,
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
    print("RISK BUDGET ENGINE — REAL COVARIANCE V4")
    print("====================================================")
    print(f"Data UTC:              {timestamp_utc}")
    print(f"Metodo:                {method}")
    print(f"Portfolio Vol:         {portfolio_volatility:.2%}")
    print(f"Top Risk Asset:        {top_asset}")
    print(f"Max Risk Contribution: {max_risk_contribution:.2%}")
    print(f"Risk Budget Score:     {risk_budget_score}")
    print(f"Risk Budget Level:     {risk_budget_level}")
    print("----------------------------------------------------")
    print(risk_budget[[
        "ativo",
        "peso_atual",
        "vol_realizada_ou_proxy",
        "risk_contribution_raw",
        "risk_contribution_abs_pct",
        "hedge_flag",
    ]].to_string(index=False))
    print("====================================================")

    return {
        "risk_budget": risk_budget,
        "risk_budget_summary": risk_budget_summary,
    }
