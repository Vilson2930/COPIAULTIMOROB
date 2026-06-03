import os
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yfinance as yf
from fredapi import Fred


OUTPUT_DIR = "outputs"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_outputs_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_fred_client():
    api_key = os.getenv("FRED_API_KEY")

    if not api_key:
        raise EnvironmentError(
            "FRED_API_KEY não encontrada. Configure em GitHub Secrets."
        )

    return Fred(api_key=api_key)


def get_fred_series_safe(fred, name, code, max_retries=5, base_sleep=8):
    for attempt in range(1, max_retries + 1):
        try:
            series = fred.get_series(code)
            series.name = name
            time.sleep(1.5)
            return series, "OK"

        except Exception as error:
            msg = str(error)

            if "Too Many Requests" in msg or "rate" in msg.lower():
                time.sleep(base_sleep * attempt)
            else:
                time.sleep(3)

    return pd.Series(dtype="float64", name=name), "FALHA"


def load_fred_data(cache_file="outputs/fred_macro_cache.csv"):
    ensure_outputs_dir()

    fred = get_fred_client()

    fred_series = {
        "real_yield_10y": "DFII10",
        "financial_conditions": "NFCI",
        "high_yield_spread": "BAMLH0A0HYM2",
        "core_pce": "PCEPILFE",
        "inflation_5y5y": "T5YIFR",
        "treasury_10y": "DGS10",
        "fed_funds": "FEDFUNDS",
        "fed_assets": "WALCL",
    }

    required_columns = list(fred_series.keys())

    if os.path.exists(cache_file):
        fred_cache = pd.read_csv(cache_file, index_col=0, parse_dates=True)
    else:
        fred_cache = pd.DataFrame()

    downloaded = {}
    quality_log = []

    for name, code in fred_series.items():
        series, status = get_fred_series_safe(fred, name, code)

        if not series.dropna().empty:
            downloaded[name] = series
            source = "FRED"

        elif name in fred_cache.columns:
            downloaded[name] = fred_cache[name]
            source = "CACHE"
            status = "USANDO_CACHE"

        else:
            downloaded[name] = pd.Series(dtype="float64", name=name)
            source = "FALLBACK"
            status = "VAZIO"

        quality_log.append({
            "serie": name,
            "codigo_fred": code,
            "status": status,
            "fonte": source,
        })

    fred_data = pd.concat(downloaded.values(), axis=1)
    fred_data = fred_data.sort_index()

    for col in required_columns:
        if col not in fred_data.columns:
            fred_data[col] = np.nan

    fallbacks_used = []

    if fred_data["fed_funds"].dropna().empty:
        fred_data["fed_funds"] = 4.00
        fallbacks_used.append("fed_funds = 4.00")

    if fred_data["inflation_5y5y"].dropna().empty:
        fred_data["inflation_5y5y"] = 2.25
        fallbacks_used.append("inflation_5y5y = 2.25")

    if fred_data["treasury_10y"].dropna().empty:
        fred_data["treasury_10y"] = fred_data["fed_funds"] + 0.80
        fallbacks_used.append("treasury_10y = fed_funds + 0.80")

    if fred_data["real_yield_10y"].dropna().empty:
        fred_data["real_yield_10y"] = (
            fred_data["treasury_10y"] - fred_data["inflation_5y5y"]
        )
        fallbacks_used.append("real_yield_10y = treasury_10y - inflation_5y5y")

    if fred_data["financial_conditions"].dropna().empty:
        fred_data["financial_conditions"] = 0.00
        fallbacks_used.append("financial_conditions = 0.00")

    if fred_data["high_yield_spread"].dropna().empty:
        fred_data["high_yield_spread"] = 4.00
        fallbacks_used.append("high_yield_spread = 4.00")

    if fred_data["core_pce"].dropna().empty:
        fred_data["core_pce"] = 125.00
        fallbacks_used.append("core_pce = 125.00")

    if fred_data["fed_assets"].dropna().empty:
        fred_data["fed_assets"] = np.nan
        fallbacks_used.append("fed_assets = indisponivel")

    fred_data = fred_data.ffill().bfill()

    fred_data["yield_curve"] = (
        fred_data["treasury_10y"] - fred_data["fed_funds"]
    )

    fred_quality_log = pd.DataFrame(quality_log)

    fred_data.to_csv(cache_file)

    fred_quality_log.to_csv(
        os.path.join(OUTPUT_DIR, "fred_quality_log.csv"),
        index=False,
    )

    return fred_data, fred_quality_log, fallbacks_used


def load_market_data():
    market_tickers = {
        "btc": "BTC-USD",
        "gld": "GLD",
        "voo": "VOO",
        "tlt": "TLT",
        "botz": "BOTZ",
        "inda": "INDA",
        "dxy": "DX-Y.NYB",
        "vix": "^VIX",
    }

    required_assets = list(market_tickers.keys())

    raw_market = yf.download(
        list(market_tickers.values()),
        start="2015-01-01",
        auto_adjust=True,
        progress=False,
        threads=False,
    )

    if isinstance(raw_market.columns, pd.MultiIndex):
        market_data = raw_market["Close"].copy()
    else:
        market_data = raw_market.copy()

    market_data = market_data.rename(
        columns={v: k for k, v in market_tickers.items()}
    )

    market_data = market_data.sort_index()

    missing_assets = [
        asset for asset in required_assets
        if asset not in market_data.columns
    ]

    for asset in missing_assets:
        market_data[asset] = np.nan

    market_data = market_data[required_assets]
    market_data = market_data.ffill().bfill()

    total_cells = market_data[required_assets].shape[0] * len(required_assets)
    missing_values = market_data[required_assets].isna().sum().sum()

    if total_cells == 0:
        market_quality_score = 0
    else:
        market_quality_score = round(
            100 * (1 - missing_values / total_cells),
            0,
        )

    if market_quality_score >= 95:
        market_quality_status = "ALTA"
    elif market_quality_score >= 80:
        market_quality_status = "ACEITAVEL"
    else:
        market_quality_status = "FRAGIL"

    latest_market = market_data.dropna(how="all").iloc[-1]

    latest_date = market_data.dropna(how="all").index[-1]
    days_delay = (pd.Timestamp.utcnow().tz_localize(None) - pd.Timestamp(latest_date)).days

    if days_delay <= 3:
        freshness_status = "ATUALIZADO"
    elif days_delay <= 7:
        freshness_status = "ATRASO_MODERADO"
    else:
        freshness_status = "DESATUALIZADO"

    coverage_missing = [
        asset for asset in required_assets
        if pd.isna(latest_market.get(asset, np.nan))
    ]

    if len(coverage_missing) == 0:
        coverage_status = "COMPLETO"
    elif len(coverage_missing) <= 2:
        coverage_status = "PARCIAL"
    else:
        coverage_status = "FRAGIL"

    market_alerts = []

    if coverage_status != "COMPLETO":
        market_alerts.append("COBERTURA_INCOMPLETA")

    if freshness_status != "ATUALIZADO":
        market_alerts.append("DADOS_DESATUALIZADOS")

    if market_quality_score < 80:
        market_alerts.append("QUALIDADE_FRAGIL")

    outlier_status = "OK"

    try:
        returns = market_data.pct_change(fill_method=None).tail(10)
        max_abs_return = returns.abs().max().max()

        if max_abs_return > 0.35:
            outlier_status = "ALERTA_OUTLIER"
            market_alerts.append("OUTLIER_EXTREMO")
    except Exception:
        outlier_status = "NAO_AVALIADO"

    market_data_score = 100

    if freshness_status == "ATRASO_MODERADO":
        market_data_score -= 10
    elif freshness_status == "DESATUALIZADO":
        market_data_score -= 25

    if coverage_status == "PARCIAL":
        market_data_score -= 10
    elif coverage_status == "FRAGIL":
        market_data_score -= 25

    if market_quality_score < 95:
        market_data_score -= 10

    if outlier_status == "ALERTA_OUTLIER":
        market_data_score -= 10

    market_data_score = max(0, market_data_score)

    if market_data_score >= 90:
        market_data_status = "INSTITUCIONAL"
    elif market_data_score >= 75:
        market_data_status = "ACEITAVEL"
    elif market_data_score >= 60:
        market_data_status = "FRAGIL"
    else:
        market_data_status = "CRITICO"

    market_audit = pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "market_data_score": market_data_score,
        "market_data_status": market_data_status,
        "market_quality_score": market_quality_score,
        "market_quality_status": market_quality_status,
        "freshness_status": freshness_status,
        "days_delay": days_delay,
        "coverage_status": coverage_status,
        "coverage_missing": " | ".join(coverage_missing),
        "outlier_status": outlier_status,
        "market_alerts": " | ".join(market_alerts),
        "dxy_proxy": latest_market.get("dxy", np.nan),
        "vix": latest_market.get("vix", np.nan),
    }])

    ensure_outputs_dir()

    market_data.to_csv(
        os.path.join(OUTPUT_DIR, "market_data.csv"),
    )

    market_audit.to_csv(
        os.path.join(OUTPUT_DIR, "market_audit.csv"),
        index=False,
    )

    market_audit.to_csv(
        os.path.join(OUTPUT_DIR, "market_data_audit.csv"),
        index=False,
    )

    return market_data, latest_market, market_audit


def enrich_fred_with_market(fred_data, market_data):
    fred_data = fred_data.copy()
    market_aligned = market_data.reindex(fred_data.index).ffill().bfill()

    if "dxy" in market_aligned.columns:
        fred_data["dxy_proxy"] = market_aligned["dxy"]

    if "vix" in market_aligned.columns:
        fred_data["vix"] = market_aligned["vix"]

    fred_data = fred_data.ffill().bfill()

    fred_data.to_csv(
        os.path.join(OUTPUT_DIR, "fred_macro_cache.csv"),
    )

    return fred_data


def build_data_snapshot(fred_data, latest_market, market_audit):
    latest_fred = fred_data.iloc[-1]

    snapshot = pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "real_yield_10y": latest_fred.get("real_yield_10y", np.nan),
        "financial_conditions": latest_fred.get("financial_conditions", np.nan),
        "high_yield_spread": latest_fred.get("high_yield_spread", np.nan),
        "core_pce": latest_fred.get("core_pce", np.nan),
        "inflation_5y5y": latest_fred.get("inflation_5y5y", np.nan),
        "treasury_10y": latest_fred.get("treasury_10y", np.nan),
        "fed_funds": latest_fred.get("fed_funds", np.nan),
        "fed_assets": latest_fred.get("fed_assets", np.nan),
        "yield_curve": latest_fred.get("yield_curve", np.nan),
        "dxy_proxy": latest_fred.get("dxy_proxy", np.nan),
        "vix": latest_fred.get("vix", np.nan),
        "btc": latest_market.get("btc", np.nan),
        "gld": latest_market.get("gld", np.nan),
        "voo": latest_market.get("voo", np.nan),
        "tlt": latest_market.get("tlt", np.nan),
        "botz": latest_market.get("botz", np.nan),
        "inda": latest_market.get("inda", np.nan),
        "market_data_score": market_audit.iloc[-1].get("market_data_score", np.nan),
        "market_data_status": market_audit.iloc[-1].get("market_data_status", np.nan),
    }])

    snapshot.to_csv(
        os.path.join(OUTPUT_DIR, "data_snapshot.csv"),
        index=False,
    )

    return snapshot


def run_data_engine():
    ensure_outputs_dir()

    fred_data, fred_quality_log, fallbacks_used = load_fred_data()

    market_data, latest_market, market_audit = load_market_data()

    fred_data = enrich_fred_with_market(
        fred_data=fred_data,
        market_data=market_data,
    )

    data_snapshot = build_data_snapshot(
        fred_data=fred_data,
        latest_market=latest_market,
        market_audit=market_audit,
    )

    print("====================================================")
    print("DATA ENGINE FINALIZADO")
    print("====================================================")
    print(f"Linhas FRED:          {len(fred_data)}")
    print(f"Linhas Mercado:       {len(market_data)}")
    print(f"Market Status:        {market_audit.iloc[-1]['market_data_status']}")
    print(f"Market Score:         {market_audit.iloc[-1]['market_data_score']}")
    print(f"DXY Proxy:            {data_snapshot.iloc[-1]['dxy_proxy']}")
    print(f"VIX:                  {data_snapshot.iloc[-1]['vix']}")
    print(f"Fed Assets:           {data_snapshot.iloc[-1]['fed_assets']}")
    print("====================================================")

    return {
        "fred_data": fred_data,
        "fred_quality_log": fred_quality_log,
        "fallbacks_used": fallbacks_used,
        "market_data": market_data,
        "latest_market": latest_market,
        "market_audit": market_audit,
        "data_snapshot": data_snapshot,
    }
