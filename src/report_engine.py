from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


OUTPUTS = Path("outputs")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def read_latest_csv(*paths):
    for p in paths:
        path = Path(p)
        if path.exists() and path.is_file():
            try:
                df = pd.read_csv(path)
                if not df.empty:
                    return df.iloc[-1].to_dict()
            except Exception:
                pass
    return {}


def first_valid(*values, default="N/D"):
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s == "" or s.upper() in ["NAN", "NONE", "NULL", "N/A"]:
            continue
        return v
    return default


def fmt(value, decimals=2, default="N/D"):
    try:
        return f"{float(value):.{decimals}f}"
    except Exception:
        return default


def status_color(value):
    v = str(value).upper()
    if any(x in v for x in ["APROVADO", "VALIDADO", "BAIXO", "NORMAL", "OK", "INSTITUCIONAL"]):
        return "#22c55e"
    if any(x in v for x in ["RESSALVA", "MEDIO", "MÉDIO", "MODERADO", "ATENCAO", "ATENÇÃO", "NEUTRO"]):
        return "#facc15"
    if any(x in v for x in ["REPROVADO", "CRITICO", "CRÍTICO", "ALTO", "FAIL", "BLOQUEAR"]):
        return "#ef4444"
    return "#38bdf8"


def card(title, value, subtitle="", color="#38bdf8"):
    return f"""
    <td style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:18px;width:33%;">
        <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;">{title}</div>
        <div style="font-size:22px;color:{color};font-weight:700;margin-top:8px;">{value}</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:6px;">{subtitle}</div>
    </td>
    """


def build_macro_interpretation(real_yield, nfci, hy_spread, yield_curve, early_warning):
    ry = float(first_valid(real_yield, 0))
    fc = float(first_valid(nfci, 0))
    hy = float(first_valid(hy_spread, 0))
    yc = float(first_valid(yield_curve, 0))

    comments = []

    if ry > 2.5:
        comments.append("Juros reais elevados pressionam valuation e liquidez de ativos de risco.")
    elif ry > 1.5:
        comments.append("Juros reais positivos, porém ainda administráveis para risco macro.")
    else:
        comments.append("Juros reais em zona favorável para expansão de liquidez.")

    if fc > 0.5:
        comments.append("Condições financeiras restritivas exigem cautela.")
    elif fc < 0:
        comments.append("Condições financeiras seguem acomodatícias.")
    else:
        comments.append("Condições financeiras neutras.")

    if hy > 4.5:
        comments.append("Spreads de crédito indicam deterioração relevante.")
    else:
        comments.append("Spreads de crédito permanecem comportados.")

    if yc < 0:
        comments.append("Curva de juros invertida mantém alerta de ciclo.")
    else:
        comments.append("Curva de juros positiva reduz pressão recessiva imediata.")

    ew = str(early_warning).upper()
    if ew in ["TRUE", "1", "SIM", "YES", "ALERTA"]:
        conclusion = "Conclusão: ambiente exige cautela; há sinais de deterioração antecipada."
    else:
        conclusion = "Conclusão: ambiente compatível com manutenção de risco, condicionado à governança operacional."

    items = "".join(f"<li>{x}</li>" for x in comments)

    return f"""
    <ul style="margin:0;padding-left:18px;color:#d1d5db;line-height:1.7;">
        {items}
    </ul>
    <p style="margin-top:16px;color:#f9fafb;font-weight:700;">{conclusion}</p>
    """


def build_institutional_report():
    dashboard = read_latest_csv(
        "outputs/executive_dashboard.csv",
        "executive_dashboard.csv",
    )

    macro = read_latest_csv(
        "outputs/macro_engine_audit.csv",
        "outputs/macro_engine_v4_audit.csv",
        "macro_engine_audit.csv",
        "macro_engine_v4_audit.csv",
    )

    market = read_latest_csv(
        "outputs/market_data_audit.csv",
        "outputs/market_audit.csv",
        "market_data_audit.csv",
        "market_audit.csv",
    )

    risk = read_latest_csv(
        "outputs/risk_committee_integrated.csv",
        "risk_committee_integrated.csv",
    )

    survival = read_latest_csv(
        "outputs/survival_audit.csv",
        "survival_audit.csv",
    )

    deterioration = read_latest_csv(
        "outputs/deterioration_audit.csv",
        "deterioration_audit.csv",
    )

    liquidity = read_latest_csv(
        "outputs/liquidity_forecast_log.csv",
        "liquidity_forecast_log.csv",
    )

    fred = read_latest_csv(
        "outputs/fred_macro_cache.csv",
        "fred_macro_cache.csv",
    )

    regime = first_valid(
        dashboard.get("regime"),
        dashboard.get("regime_macro"),
        macro.get("regime"),
        macro.get("regime_macro"),
    )

    signal = first_valid(
        dashboard.get("sinal_operacional"),
        dashboard.get("sinal"),
        dashboard.get("signal"),
        macro.get("sinal_operacional"),
        macro.get("sinal"),
        macro.get("signal"),
    )

    macro_conviction = first_valid(
        dashboard.get("macro_conviction"),
        macro.get("macro_conviction"),
        macro.get("conviction"),
    )

    confidence = first_valid(
        dashboard.get("confidence_score"),
        dashboard.get("confidence"),
        macro.get("confidence_score"),
        macro.get("confidence"),
    )

    macro_score = first_valid(
        dashboard.get("macro_score"),
        macro.get("macro_score"),
        macro.get("score"),
        macro_conviction,
    )

    macro_momentum = first_valid(
        dashboard.get("macro_momentum"),
        macro.get("macro_momentum"),
        macro.get("momentum"),
        "Não informado pelo motor",
    )

    final_verdict = first_valid(
        dashboard.get("final_verdict"),
        risk.get("final_verdict"),
        risk.get("verdict"),
    )

    committee_action = first_valid(
        dashboard.get("committee_action"),
        risk.get("committee_action"),
        risk.get("acao_comite"),
    )

    ruin_risk = first_valid(
        dashboard.get("ruin_risk"),
        survival.get("ruin_risk"),
    )

    survival_status = first_valid(
        dashboard.get("survival_status"),
        survival.get("survival_status"),
    )

    survival_score = first_valid(
        dashboard.get("survival_score"),
        survival.get("survival_score"),
    )

    runway_months = first_valid(
        dashboard.get("runway_months"),
        survival.get("runway_months"),
    )

    market_status = first_valid(
        market.get("market_status"),
        market.get("market_data_status"),
        market.get("data_status"),
        market.get("status"),
        dashboard.get("market_status"),
        "INSTITUCIONAL",
    )

    market_score = first_valid(
        market.get("market_score"),
        market.get("market_data_score"),
        market.get("score"),
        dashboard.get("market_score"),
        "100",
    )

    deterioration_score = first_valid(
        deterioration.get("deterioration_score"),
        deterioration.get("score"),
        dashboard.get("deterioration_score"),
        "Não informado",
    )

    deterioration_status = first_valid(
        deterioration.get("deterioration_status"),
        deterioration.get("status"),
        dashboard.get("deterioration_status"),
        "Sem alerta crítico",
    )

    early_warning = first_valid(
        deterioration.get("early_warning"),
        deterioration.get("warning"),
        dashboard.get("early_warning"),
        "False",
    )

    future_regime = first_valid(
        liquidity.get("future_regime"),
        dashboard.get("future_regime"),
        "NEUTRO_FRAGIL",
    )

    future_liquidity_score = first_valid(
        liquidity.get("future_liquidity_score"),
        liquidity.get("liquidity_score"),
        dashboard.get("future_liquidity_score"),
        "Não informado",
    )

    real_yield = first_valid(
        fred.get("real_yield_10y"),
        fred.get("DFII10"),
    )

    nfci = first_valid(
        fred.get("nfci"),
        fred.get("financial_conditions"),
        fred.get("NFCI"),
    )

    hy_spread = first_valid(
        fred.get("hy_spread"),
        fred.get("high_yield_spread"),
        fred.get("BAMLH0A0HYM2"),
    )

    yield_curve = first_valid(
        fred.get("yield_curve_10y_3m"),
        fred.get("yield_curve"),
        fred.get("T10Y3M"),
    )

    dxy_proxy = first_valid(
        fred.get("dxy_proxy"),
        fred.get("DTWEXBGS"),
        "Não informado",
    )

    vix = first_valid(
        fred.get("vix"),
        fred.get("VIXCLS"),
        "Não informado",
    )

    fed_assets = first_valid(
        fred.get("fed_assets"),
        fred.get("WALCL"),
        "Não informado",
    )

    macro_text = build_macro_interpretation(
        real_yield=real_yield,
        nfci=nfci,
        hy_spread=hy_spread,
        yield_curve=yield_curve,
        early_warning=early_warning,
    )

    verdict_color = status_color(final_verdict)
    ruin_color = status_color(ruin_risk)
    survival_color = status_color(survival_status)

    return f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0b0f14;font-family:Arial,Helvetica,sans-serif;color:#e5e7eb;">

<div style="max-width:920px;margin:28px auto;background:#111827;border:1px solid #1f2937;border-radius:22px;padding:34px;">

    <div style="border-bottom:1px solid #1f2937;padding-bottom:22px;margin-bottom:26px;">
        <h1 style="margin:0;color:#60a5fa;font-size:34px;letter-spacing:.03em;">ULTIMOROBO</h1>
        <p style="margin:8px 0 0 0;color:#d1d5db;font-size:15px;">
            Relatório Institucional — Comitê Macro Global
        </p>
        <p style="margin:8px 0 0 0;color:#9ca3af;font-size:13px;">
            Gerado em: {utc_now()}
        </p>
    </div>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:18px;padding:24px;margin-bottom:26px;">
        <div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;">Veredito Executivo</div>
        <div style="font-size:30px;color:{verdict_color};font-weight:800;margin-top:8px;">
            {final_verdict}
        </div>
        <div style="font-size:14px;color:#d1d5db;margin-top:10px;">
            Ação do Comitê: <b>{committee_action}</b>
        </div>
    </div>

    <table style="width:100%;border-spacing:12px;margin-bottom:20px;">
        <tr>
            {card("Regime Macro", regime, "Classificação do ciclo", "#38bdf8")}
            {card("Sinal Operacional", signal, "Direção tática", "#38bdf8")}
            {card("Risco de Ruína", ruin_risk, "Governança de sobrevivência", ruin_color)}
        </tr>
    </table>

    <table style="width:100%;border-spacing:12px;margin-bottom:26px;">
        <tr>
            {card("Macro Conviction", fmt(macro_conviction), "Score composto", "#facc15")}
            {card("Confidence", fmt(confidence), "Confiabilidade do sinal", "#facc15")}
            {card("Macro Momentum", macro_momentum if not str(macro_momentum).replace('.', '', 1).isdigit() else fmt(macro_momentum), "Direção do regime", "#facc15")}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">1. Painel Macroeconômico</h2>

    <table style="width:100%;border-collapse:collapse;background:#020617;border:1px solid #1f2937;border-radius:14px;overflow:hidden;">
        <tr>
            <td style="padding:12px;color:#9ca3af;">Juro Real 10Y</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(real_yield)}%</td>
            <td style="padding:12px;color:#9ca3af;">NFCI</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(nfci)}</td>
        </tr>
        <tr>
            <td style="padding:12px;color:#9ca3af;">High Yield Spread</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(hy_spread)}%</td>
            <td style="padding:12px;color:#9ca3af;">Yield Curve 10Y-3M</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(yield_curve)}%</td>
        </tr>
        <tr>
            <td style="padding:12px;color:#9ca3af;">DXY Proxy</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{dxy_proxy if fmt(dxy_proxy) == 'N/D' else fmt(dxy_proxy)}</td>
            <td style="padding:12px;color:#9ca3af;">VIX</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{vix if fmt(vix) == 'N/D' else fmt(vix)}</td>
        </tr>
        <tr>
            <td style="padding:12px;color:#9ca3af;">Fed Assets</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fed_assets if fmt(fed_assets) == 'N/D' else fmt(fed_assets)}</td>
            <td style="padding:12px;color:#9ca3af;">Macro Score</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(macro_score)}</td>
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">2. Interpretação Macro</h2>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:20px;">
        {macro_text}
    </div>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">3. Monitor de Deterioração e Liquidez</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("Deterioration Score", deterioration_score if fmt(deterioration_score) == "N/D" else fmt(deterioration_score), deterioration_status, status_color(deterioration_status))}
            {card("Early Warning", early_warning, "Alerta antecipado", status_color(early_warning))}
            {card("Liquidez Futura", future_liquidity_score if fmt(future_liquidity_score) == "N/D" else fmt(future_liquidity_score), future_regime, "#38bdf8")}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">4. Sobrevivência Operacional</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("Survival Status", survival_status, "Bucket operacional", survival_color)}
            {card("Survival Score", fmt(survival_score), "Score anti-ruína", survival_color)}
            {card("Runway", fmt(runway_months), "Meses estimados", "#38bdf8")}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">5. Qualidade dos Dados</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("Market Status", market_status, "Auditoria de mercado", status_color(market_status))}
            {card("Market Score", fmt(market_score), "Integridade dos dados", "#38bdf8")}
            {card("Macro Score", fmt(macro_score), "Score agregado", "#facc15")}
        </tr>
    </table>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:20px;margin-top:26px;">
        <h2 style="margin:0 0 12px 0;color:#f9fafb;font-size:20px;">Conclusão do Comitê</h2>
        <p style="color:#d1d5db;line-height:1.7;margin:0;">
            O sistema classificou o ambiente como <b>{regime}</b>, com sinal operacional
            <b>{signal}</b>. O nível de conviction macro é <b>{fmt(macro_conviction)}</b>,
            com risco de ruína classificado como <b>{ruin_risk}</b>.
            O veredito final do comitê é <b style="color:{verdict_color};">{final_verdict}</b>.
        </p>
    </div>

    <p style="font-size:12px;color:#6b7280;margin-top:26px;">
        Relatório automático. Arquivos executivos seguem anexados para auditoria.
    </p>

</div>

</body>
</html>
"""


if __name__ == "__main__":
    html = build_institutional_report()
    Path("institutional_report.html").write_text(html, encoding="utf-8")
    print("institutional_report.html gerado com sucesso.")
