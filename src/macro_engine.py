from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


OUTPUTS = Path("outputs")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_outputs():
    OUTPUTS.mkdir(exist_ok=True)


def macro_score(series, inverse=False, window=252):
    series = pd.Series(series).astype(float).replace([np.inf, -np.inf], np.nan)

    rolling_min = series.rolling(window=window, min_periods=60).min()
    rolling_max = series.rolling(window=window, min_periods=60).max()

    score = 100 * (series - rolling_min) / (rolling_max - rolling_min)
    score = score.replace([np.inf, -np.inf], np.nan)

    if inverse:
        score = 100 - score

    return score.clip(0, 100)


def build_scores(fred_data, market_data):
    scores = pd.DataFrame(index=fred_data.index)

    fred_data = fred_data.sort_index().ffill().bfill()
    market_data = market_data.sort_index().ffill().bfill()

    market_aligned = market_data.reindex(scores.index).ffill().bfill()

    scores["real_yield_spot"] = macro_score(fred_data["real_yield_10y"], inverse=True)
    scores["real_yield_lag"] = macro_score(fred_data["real_yield_10y"].shift(60), inverse=True)
    scores["real_yield_trend"] = macro_score(fred_data["real_yield_10y"] - fred_data["real_yield_10y"].shift(60), inverse=True)

    real_yield_acceleration = (
        fred_data["real_yield_10y"] - fred_data["real_yield_10y"].shift(30)
    ) - (
        fred_data["real_yield_10y"].shift(30) - fred_data["real_yield_10y"].shift(60)
    )
    scores["real_yield_acceleration"] = macro_score(real_yield_acceleration, inverse=True)

    scores["nfci_spot"] = macro_score(fred_data["financial_conditions"], inverse=True)
    scores["nfci_lag"] = macro_score(fred_data["financial_conditions"].shift(90), inverse=True)
    scores["nfci_trend"] = macro_score(fred_data["financial_conditions"] - fred_data["financial_conditions"].shift(90), inverse=True)

    nfci_acceleration = (
        fred_data["financial_conditions"] - fred_data["financial_conditions"].shift(45)
    ) - (
        fred_data["financial_conditions"].shift(45) - fred_data["financial_conditions"].shift(90)
    )
    scores["nfci_acceleration"] = macro_score(nfci_acceleration, inverse=True)

    scores["dxy_spot"] = macro_score(market_aligned["dxy"], inverse=True)
    scores["dxy_lag"] = macro_score(market_aligned["dxy"].shift(60), inverse=True)
    scores["dxy_trend"] = macro_score(market_aligned["dxy"] - market_aligned["dxy"].shift(60), inverse=True)

    dxy_acceleration = (
        market_aligned["dxy"] - market_aligned["dxy"].shift(30)
    ) - (
        market_aligned["dxy"].shift(30) - market_aligned["dxy"].shift(60)
    )
    scores["dxy_acceleration"] = macro_score(dxy_acceleration, inverse=True)

    scores["liquidity_score"] = (
        scores["real_yield_trend"] * 0.12
        + scores["real_yield_acceleration"] * 0.08
        + scores["nfci_trend"] * 0.06
        + scores["nfci_acceleration"] * 0.04
        + scores["dxy_trend"] * 0.06
        + scores["dxy_acceleration"] * 0.04
        + scores["real_yield_spot"] * 0.15
        + scores["nfci_spot"] * 0.075
        + scores["dxy_spot"] * 0.075
        + scores["real_yield_lag"] * 0.15
        + scores["nfci_lag"] * 0.075
        + scores["dxy_lag"] * 0.075
    )

    scores["growth_score"] = macro_score(fred_data["yield_curve"].shift(120), inverse=False)

    scores["high_yield_spread"] = macro_score(fred_data["high_yield_spread"], inverse=True)
    scores["vix"] = macro_score(market_aligned["vix"], inverse=True)

    scores["stress_score"] = (
        scores["high_yield_spread"] * 0.50
        + scores["vix"] * 0.50
    )

    scores["core_pce"] = macro_score(fred_data["core_pce"].shift(90), inverse=True)
    scores["inflation_5y5y"] = macro_score(fred_data["inflation_5y5y"].shift(60), inverse=True)

    scores["inflation_score"] = (
        scores["core_pce"] * 0.50
        + scores["inflation_5y5y"] * 0.50
    )

    scores["dxy_value"] = market_aligned["dxy"]
    scores["vix_value"] = market_aligned["vix"]

    return scores.sort_index().ffill().bfill()


def classify_regime(score):
    if pd.isna(score):
        return np.nan
    if score >= 80:
        return "EXPANSAO_FORTE"
    if score >= 60:
        return "EXPANSAO_NORMAL"
    if score >= 40:
        return "NEUTRO"
    if score >= 20:
        return "CONTRACAO"
    return "STRESS_SISTEMICO"


def operational_signal(row):
    if pd.isna(row["macro_conviction"]):
        return np.nan

    if row["confidence_score"] < 45:
        return "SINAL_FRACO"

    if row["macro_conviction"] >= 60 and row["macro_momentum"] > 0:
        return "RISCO_ON_VALIDADO"

    if row["macro_conviction"] >= 60 and row["macro_momentum"] <= 0:
        return "RISCO_ON_COM_CAUTELA"

    if row["macro_conviction"] < 40:
        return "DEFENSIVO_VALIDADO"

    return "NEUTRO"


def calculate_quality_score(df, columns):
    total_cells = df[columns].shape[0] * len(columns)
    if total_cells == 0:
        return 0
    missing_cells = df[columns].isna().sum().sum()
    return round(100 * (1 - missing_cells / total_cells), 0)


def build_macro_engine(scores):
    macro_engine = pd.DataFrame(index=scores.index)

    macro_engine["liquidez"] = scores["liquidity_score"]
    macro_engine["crescimento"] = scores["growth_score"]
    macro_engine["stress"] = scores["stress_score"]
    macro_engine["inflacao"] = scores["inflation_score"]

    macro_engine = macro_engine.ffill().bfill()

    macro_engine["macro_score"] = (
        macro_engine["liquidez"] * 0.45
        + macro_engine["crescimento"] * 0.25
        + macro_engine["stress"] * 0.20
        + macro_engine["inflacao"] * 0.10
    )

    macro_engine["momentum_30d"] = macro_engine["macro_score"] - macro_engine["macro_score"].shift(30)
    macro_engine["momentum_60d"] = macro_engine["macro_score"] - macro_engine["macro_score"].shift(60)
    macro_engine["momentum_90d"] = macro_engine["macro_score"] - macro_engine["macro_score"].shift(90)

    macro_engine["macro_momentum"] = (
        macro_engine["momentum_30d"] * 0.50
        + macro_engine["momentum_60d"] * 0.30
        + macro_engine["momentum_90d"] * 0.20
    ).fillna(0)

    macro_engine["macro_momentum_score"] = (50 + macro_engine["macro_momentum"]).clip(0, 100)

    factor_cols = ["liquidez", "crescimento", "stress", "inflacao"]

    macro_engine["factor_dispersion"] = macro_engine[factor_cols].std(axis=1)

    macro_engine["confidence_score"] = (100 - macro_engine["factor_dispersion"]).clip(0, 100)

    macro_engine["macro_conviction"] = (
        macro_engine["macro_score"] * 0.70
        + macro_engine["macro_momentum_score"] * 0.20
        + macro_engine["confidence_score"] * 0.10
    )

    macro_engine["regime"] = macro_engine["macro_conviction"].apply(classify_regime)
    macro_engine["sinal_operacional"] = macro_engine.apply(operational_signal, axis=1)

    valid_macro = macro_engine.dropna(
        subset=["macro_score", "macro_conviction", "regime", "sinal_operacional"]
    )

    if valid_macro.empty:
        raise ValueError("macro_engine não possui linha válida.")

    latest = valid_macro.iloc[-1]

    quality_score = calculate_quality_score(
        macro_engine,
        ["liquidez", "crescimento", "stress", "inflacao", "macro_score", "macro_conviction", "confidence_score"],
    )

    if quality_score >= 95:
        quality_status = "ALTA"
    elif quality_score >= 80:
        quality_status = "ACEITAVEL"
    else:
        quality_status = "FRAGIL"

    audit = pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "liquidez": float(latest["liquidez"]),
        "crescimento": float(latest["crescimento"]),
        "stress": float(latest["stress"]),
        "inflacao": float(latest["inflacao"]),
        "macro_score": float(latest["macro_score"]),
        "macro_momentum": float(latest["macro_momentum"]),
        "macro_momentum_score": float(latest["macro_momentum_score"]),
        "confidence_score": float(latest["confidence_score"]),
        "macro_conviction": float(latest["macro_conviction"]),
        "regime": latest["regime"],
        "sinal_operacional": latest["sinal_operacional"],
        "data_quality_score": quality_score,
        "data_quality_status": quality_status,
    }])

    return macro_engine, latest, audit


def run_deterioration_detector(fred_data):
    latest = fred_data.iloc[-1]

    real_yield = float(latest["real_yield_10y"])
    financial_conditions = float(latest["financial_conditions"])
    hy_spread = float(latest["high_yield_spread"])
    inflation = float(latest["inflation_5y5y"])
    yield_curve = float(latest["yield_curve"])

    signals = {
        "real_yield_alert": real_yield > 2.50,
        "financial_conditions_alert": financial_conditions > 0.50,
        "high_yield_alert": hy_spread > 4.50,
        "inflation_alert": inflation > 3.25,
        "yield_curve_alert": yield_curve < 0,
    }

    alert_count = sum(signals.values())

    if alert_count == 0:
        deterioration_score = 100
        deterioration_status = "SEM_DETERIORACAO"
    elif alert_count == 1:
        deterioration_score = 80
        deterioration_status = "ATENCAO"
    elif alert_count == 2:
        deterioration_score = 60
        deterioration_status = "DETERIORACAO_INICIAL"
    elif alert_count == 3:
        deterioration_score = 40
        deterioration_status = "DETERIORACAO_RELEVANTE"
    else:
        deterioration_score = 20
        deterioration_status = "DETERIORACAO_SEVERA"

    return pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "real_yield_10y": real_yield,
        "financial_conditions": financial_conditions,
        "high_yield_spread": hy_spread,
        "inflation_5y5y": inflation,
        "yield_curve": yield_curve,
        "alerts": alert_count,
        "deterioration_score": deterioration_score,
        "deterioration_status": deterioration_status,
        "early_warning": deterioration_score <= 60,
    }])


def run_liquidity_forecast(scores, macro_engine_audit=None, latest=None):
    liquidity_series = scores["liquidity_score"].astype(float).dropna()

    current_liquidity = float(liquidity_series.iloc[-1])
    lag_30 = float(liquidity_series.tail(min(30, len(liquidity_series))).mean())
    lag_60 = float(liquidity_series.tail(min(60, len(liquidity_series))).mean())
    lag_90 = float(liquidity_series.tail(min(90, len(liquidity_series))).mean())
    lag_120 = float(liquidity_series.tail(min(120, len(liquidity_series))).mean())

    future_liquidity_score = (
        current_liquidity * 0.40
        + lag_30 * 0.25
        + lag_60 * 0.15
        + lag_90 * 0.10
        + lag_120 * 0.10
    )

    liquidity_momentum = current_liquidity - lag_60
    liquidity_acceleration = (lag_30 - lag_60) - (lag_60 - lag_90)

    expansion_probability = np.clip(
        future_liquidity_score
        + max(liquidity_momentum, 0) * 0.20
        + max(liquidity_acceleration, 0) * 0.10,
        0,
        100,
    )

    if expansion_probability >= 70:
        future_regime = "EXPANSAO"
    elif expansion_probability >= 55:
        future_regime = "NEUTRO_POSITIVO"
    elif expansion_probability >= 40:
        future_regime = "NEUTRO_FRAGIL"
    else:
        future_regime = "CONTRACAO"

    asset_signal = "POSITIVO" if future_regime in ["EXPANSAO", "NEUTRO_POSITIVO"] else "NEUTRO_NEGATIVO"

    return pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "current_liquidity": current_liquidity,
        "lag_30": lag_30,
        "lag_60": lag_60,
        "lag_90": lag_90,
        "lag_120": lag_120,
        "future_liquidity_score": future_liquidity_score,
        "liquidity_momentum": liquidity_momentum,
        "liquidity_acceleration": liquidity_acceleration,
        "expansion_probability": expansion_probability,
        "future_regime": future_regime,
        "btc_signal": asset_signal,
        "voo_signal": asset_signal,
        "botz_signal": asset_signal,
        "inda_signal": asset_signal,
    }])


def run_macro_engine(fred_data, market_data):
    ensure_outputs()

    scores = build_scores(fred_data=fred_data, market_data=market_data)

    macro_engine, latest, macro_engine_audit = build_macro_engine(scores)

    deterioration_audit = run_deterioration_detector(fred_data)

    liquidity_forecast = run_liquidity_forecast(
        scores=scores,
        macro_engine_audit=macro_engine_audit,
        latest=latest,
    )

    macro_engine_audit.to_csv("outputs/macro_engine_audit.csv", index=False)
    deterioration_audit.to_csv("outputs/deterioration_audit.csv", index=False)
    liquidity_forecast.to_csv("outputs/liquidity_forecast_log.csv", index=False)

    scores.tail(1).to_csv("outputs/macro_scores_latest.csv")
    macro_engine.tail(1).to_csv("outputs/macro_engine_latest.csv")

    print("====================================================")
    print("MACRO ENGINE FINALIZADO")
    print("====================================================")
    print(f"Regime:             {latest['regime']}")
    print(f"Sinal:              {latest['sinal_operacional']}")
    print(f"Macro Conviction:   {latest['macro_conviction']:.2f}")
    print(f"Macro Momentum:     {latest['macro_momentum']:.2f}")
    print(f"Confidence Score:   {latest['confidence_score']:.2f}")
    print("====================================================")

    return {
        "scores": scores,
        "macro_engine": macro_engine,
        "latest": latest,
        "macro_engine_audit": macro_engine_audit,
        "deterioration_audit": deterioration_audit,
        "liquidity_forecast": liquidity_forecast,
    }
