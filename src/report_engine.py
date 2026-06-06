from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


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


def read_csv_safe(path):
    p = Path(path)
    if not p.exists() or not p.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(p)
    except Exception:
        return pd.DataFrame()


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
        return f"{float(value):,.{decimals}f}"
    except Exception:
        return default


def is_true(value):
    return str(value).upper().strip() in ["TRUE", "1", "SIM", "YES"]


def status_color(value):
    v = str(value).upper()
    if any(x in v for x in [
        "REPROVADO", "CRITICO", "CRÍTICO", "ALTO", "FAIL",
        "BLOQUEAR", "CRITICA", "CRÍTICA", "CRITICA"
    ]):
        return "#ef4444"

    if any(x in v for x in [
        "RESSALVA", "MEDIO", "MÉDIO", "MODERADO", "ATENCAO",
        "ATENÇÃO", "FRAGIL", "FRÁGIL", "MEDIA", "MÉDIA",
        "DESALINHADO", "DISTANTE"
    ]):
        return "#facc15"

    if any(x in v for x in [
        "APROVADO", "VALIDADO", "BAIXO", "NORMAL", "OK",
        "INSTITUCIONAL", "ROBUSTO", "ACEITAVEL", "ACEITÁVEL",
        "COERENTE", "ALINHADO"
    ]):
        return "#22c55e"

    return "#38bdf8"


def card(title, value, subtitle="", color="#38bdf8"):
    return f"""
    <td style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:18px;width:33%;vertical-align:top;">
        <div style="font-size:12px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;">{title}</div>
        <div style="font-size:22px;color:{color};font-weight:700;margin-top:8px;">{value}</div>
        <div style="font-size:12px;color:#9ca3af;margin-top:6px;">{subtitle}</div>
    </td>
    """


def flag_row(label, active):
    color = "#ef4444" if active else "#22c55e"
    mark = "X" if active else " "
    return f"""
    <tr>
        <td style="padding:10px;border-bottom:1px solid #1f2937;color:#d1d5db;">[{mark}] {label}</td>
        <td style="padding:10px;border-bottom:1px solid #1f2937;color:{color};font-weight:bold;">
            {"ACIONADO" if active else "OK"}
        </td>
    </tr>
    """


def engine_row(name, status, score="N/D"):
    return f"""
    <tr>
        <td style="padding:10px;border-bottom:1px solid #1f2937;color:#d1d5db;">{name}</td>
        <td style="padding:10px;border-bottom:1px solid #1f2937;color:{status_color(status)};font-weight:bold;">{status}</td>
        <td style="padding:10px;border-bottom:1px solid #1f2937;color:#f9fafb;">{score}</td>
    </tr>
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

    if is_true(early_warning):
        conclusion = "Conclusão: ambiente exige cautela; há sinais de deterioração antecipada."
    else:
        conclusion = "Conclusão: ambiente macro compatível com manutenção de risco, condicionado à governança operacional."

    items = "".join(f"<li>{x}</li>" for x in comments)

    return f"""
    <ul style="margin:0;padding-left:18px;color:#d1d5db;line-height:1.7;">
        {items}
    </ul>
    <p style="margin-top:16px;color:#f9fafb;font-weight:700;">{conclusion}</p>
    """


def build_allocation_table(allocation_rows):
    if allocation_rows.empty:
        return """
        <tr>
            <td colspan="6" style="padding:10px;color:#d1d5db;">
                Allocation Advisor não disponível.
            </td>
        </tr>
        """

    rows = ""

    for _, row in allocation_rows.head(10).iterrows():
        priority = row.get("prioridade_modelo", "N/D")
        rows += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #1f2937;color:#d1d5db;">{row.get("ativo", "N/D")}</td>
            <td style="padding:10px;border-bottom:1px solid #1f2937;color:#f9fafb;">{fmt(row.get("peso_atual_pct"))}%</td>
            <td style="padding:10px;border-bottom:1px solid #1f2937;color:#f9fafb;">{fmt(row.get("peso_alvo_pct"))}%</td>
            <td style="padding:10px;border-bottom:1px solid #1f2937;color:{status_color(priority)};font-weight:bold;">{fmt(row.get("desvio_pct"))}%</td>
            <td style="padding:10px;border-bottom:1px solid #1f2937;color:{status_color(priority)};font-weight:bold;">{row.get("acao_modelo", "N/D")}</td>
            <td style="padding:10px;border-bottom:1px solid #1f2937;color:#d1d5db;">{priority}</td>
        </tr>
        """

    return rows


def build_institutional_report():
    dashboard = read_latest_csv("outputs/executive_dashboard.csv", "executive_dashboard.csv")
    macro = read_latest_csv("outputs/macro_engine_audit.csv", "macro_engine_audit.csv")
    market = read_latest_csv("outputs/market_data_audit.csv", "outputs/market_audit.csv", "market_audit.csv")
    risk = read_latest_csv("outputs/risk_committee_integrated.csv", "risk_committee_integrated.csv")
    survival = read_latest_csv("outputs/survival_audit.csv", "survival_audit.csv")
    stress = read_latest_csv("outputs/stress_summary_v2.csv", "outputs/stress_summary.csv")
    risk_budget = read_latest_csv("outputs/risk_budget_summary.csv")
    liquidity = read_latest_csv("outputs/liquidity_summary.csv")
    counterparty = read_latest_csv("outputs/counterparty_summary.csv")
    deterioration = read_latest_csv("outputs/deterioration_audit.csv")
    fred = read_latest_csv("outputs/fred_macro_cache.csv", "fred_macro_cache.csv")

    ai_audit = read_latest_csv("outputs/ai_audit_summary.csv")
    openai_audit = read_latest_csv("outputs/openai_audit_summary.csv")

    allocation_summary = read_latest_csv("outputs/allocation_advisor_summary.csv")
    allocation_rows = read_csv_safe("outputs/allocation_advisor.csv")

    regime = first_valid(dashboard.get("regime"), macro.get("regime"))
    signal = first_valid(dashboard.get("sinal"), dashboard.get("sinal_operacional"), macro.get("sinal_operacional"))
    macro_conviction = first_valid(dashboard.get("macro_conviction"), macro.get("macro_conviction"))
    macro_score = first_valid(macro.get("macro_score"), macro_conviction)

    final_verdict = first_valid(dashboard.get("final_verdict"), risk.get("final_verdict"))
    committee_action = first_valid(dashboard.get("committee_action"), risk.get("committee_action"))

    ruin_risk = first_valid(dashboard.get("ruin_risk"), survival.get("ruin_risk"))
    survival_status = first_valid(dashboard.get("survival_status"), survival.get("survival_status"))
    survival_score = first_valid(survival.get("survival_score"))
    runway_months = first_valid(survival.get("runway_months"))
    survival_kill_switch = first_valid(survival.get("survival_kill_switch"), False)

    stress_level = first_valid(stress.get("stress_level"), stress.get("robustez"))
    stress_score = first_valid(stress.get("stress_score"))
    max_drawdown = first_valid(stress.get("max_drawdown_pct"))
    forced_selling = first_valid(stress.get("forced_selling_any"), False)

    risk_budget_level = first_valid(risk_budget.get("risk_budget_level"))
    risk_budget_score = first_valid(risk_budget.get("risk_budget_score"))
    top_risk_asset = first_valid(risk_budget.get("top_risk_asset"))
    top_risk_contribution = first_valid(risk_budget.get("max_risk_contribution_pct"))

    liquidity_level = first_valid(liquidity.get("liquidity_level"))
    liquidity_score = first_valid(liquidity.get("liquidity_score"))
    haircut = first_valid(liquidity.get("aggregate_haircut_pct"), liquidity.get("aggregate_operational_haircut_pct"))
    liquid_value = first_valid(liquidity.get("liquid_value"), liquidity.get("operational_liquid_value"))

    counterparty_level = first_valid(counterparty.get("counterparty_level"))
    counterparty_score = first_valid(counterparty.get("counterparty_score"))
    largest_counterparty = first_valid(counterparty.get("largest_counterparty"))

    market_status = first_valid(market.get("market_status"), market.get("market_data_status"), "INSTITUCIONAL")
    market_score = first_valid(market.get("market_score"), market.get("market_data_score"), "100")

    early_warning = first_valid(deterioration.get("early_warning"), False)

    ai_status = first_valid(ai_audit.get("ai_audit_status"))
    ai_score = first_valid(ai_audit.get("ai_audit_score"))

    openai_status = first_valid(openai_audit.get("openai_audit_status"))
    openai_verdict = first_valid(openai_audit.get("audit_verdict"))
    openai_score = first_valid(openai_audit.get("audit_score"))
    openai_confidence = first_valid(openai_audit.get("audit_confidence"))
    openai_severity = first_valid(openai_audit.get("severity"))
    openai_root_cause = first_valid(openai_audit.get("root_cause"))
    openai_material_inconsistency = first_valid(openai_audit.get("material_inconsistency"))
    openai_false_positive = first_valid(openai_audit.get("false_positive_risk"))
    openai_false_negative = first_valid(openai_audit.get("false_negative_risk"))
    openai_summary = first_valid(openai_audit.get("executive_summary"))
    openai_governance = first_valid(openai_audit.get("governance_recommendation"))
    openai_final = first_valid(
        openai_audit.get("final_opinion"),
        openai_audit.get("executive_summary"),
        default="Parecer final não informado pela auditoria OpenAI.",
    )

    allocation_score = first_valid(allocation_summary.get("allocation_alignment_score"))
    allocation_level = first_valid(allocation_summary.get("allocation_alignment_level"))
    model_drift = first_valid(allocation_summary.get("total_model_drift_pct"))
    turnover_recommended = first_valid(allocation_summary.get("turnover_recommended_pct"))
    top_gap_asset = first_valid(allocation_summary.get("top_gap_asset"))
    top_gap_abs = first_valid(allocation_summary.get("top_gap_abs_pct"))

    real_yield = first_valid(fred.get("real_yield_10y"), fred.get("DFII10"))
    nfci = first_valid(fred.get("nfci"), fred.get("financial_conditions"))
    hy_spread = first_valid(fred.get("hy_spread"), fred.get("high_yield_spread"))
    yield_curve = first_valid(fred.get("yield_curve_10y_3m"), fred.get("yield_curve"))
    dxy_proxy = first_valid(fred.get("dxy_proxy"), fred.get("DTWEXBGS"))
    vix = first_valid(fred.get("vix"), fred.get("VIXCLS"))
    fed_assets = first_valid(fred.get("fed_assets"), fred.get("WALCL"))

    runway_fail = False
    try:
        runway_fail = float(runway_months) < 12
    except Exception:
        pass

    survival_ks = is_true(survival_kill_switch)
    forced_sell = is_true(forced_selling)
    liquidity_critical = str(liquidity_level).upper() in ["CRITICO", "CRÍTICO"]
    counterparty_fail = str(counterparty_level).upper() in ["CRITICO", "CRÍTICO"]
    macro_fail = str(regime).upper() in ["STRESS_SISTEMICO", "CONTRACAO"]

    if survival_ks or runway_fail:
        primary_cause = "INSUFICIÊNCIA DO BUCKET DE SOBREVIVÊNCIA"
        decision_type = "REPROVAÇÃO OPERACIONAL"
    elif forced_sell:
        primary_cause = "RISCO DE FORCED SELLING EM CENÁRIOS DE ESTRESSE"
        decision_type = "REPROVAÇÃO POR ESTRESSE"
    elif liquidity_critical:
        primary_cause = "LIQUIDEZ OPERACIONAL CRÍTICA"
        decision_type = "RESTRIÇÃO DE LIQUIDEZ"
    elif counterparty_fail:
        primary_cause = "FRAGILIDADE DE CONTRAPARTE"
        decision_type = "RESTRIÇÃO DE CONTRAPARTE"
    elif macro_fail:
        primary_cause = "DETERIORAÇÃO MACROECONÔMICA"
        decision_type = "RESTRIÇÃO MACRO"
    else:
        primary_cause = "SEM FALHA CRÍTICA PRIMÁRIA"
        decision_type = "APROVAÇÃO OU APROVAÇÃO CONDICIONAL"

    macro_text = build_macro_interpretation(real_yield, nfci, hy_spread, yield_curve, early_warning)
    verdict_color = status_color(final_verdict)
    allocation_table_rows = build_allocation_table(allocation_rows)

    return f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#0b0f14;font-family:Arial,Helvetica,sans-serif;color:#e5e7eb;">

<div style="max-width:960px;margin:28px auto;background:#111827;border:1px solid #1f2937;border-radius:22px;padding:34px;">

    <div style="border-bottom:1px solid #1f2937;padding-bottom:22px;margin-bottom:26px;">
        <h1 style="margin:0;color:#60a5fa;font-size:34px;letter-spacing:.03em;">ULTIMOROBO</h1>
        <p style="margin:8px 0 0 0;color:#d1d5db;font-size:15px;">Relatório Institucional — Comitê Macro Global</p>
        <p style="margin:8px 0 0 0;color:#9ca3af;font-size:13px;">Gerado em: {utc_now()}</p>
    </div>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:18px;padding:24px;margin-bottom:22px;">
        <div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;">Veredito Executivo</div>
        <div style="font-size:30px;color:{verdict_color};font-weight:800;margin-top:8px;">{final_verdict}</div>
        <div style="font-size:14px;color:#d1d5db;margin-top:10px;">Ação do Comitê: <b>{committee_action}</b></div>
        <div style="font-size:14px;color:#f9fafb;margin-top:14px;">
            Tipo de decisão: <b>{decision_type}</b><br>
            Motivo primário: <b>{primary_cause}</b>
        </div>
    </div>

    <div style="background:#1e1b4b;border:1px solid #3730a3;border-radius:16px;padding:20px;margin-bottom:26px;">
        <h2 style="margin:0 0 10px 0;color:#ffffff;font-size:20px;">Diagnóstico da Decisão</h2>
        <p style="color:#d1d5db;line-height:1.7;margin:0;">
            O ambiente macroeconômico foi classificado como <b>{regime}</b>, com sinal <b>{signal}</b>.
            Entretanto, o veredito final é determinado pela hierarquia de risco do sistema.
            No cenário atual, a decisão foi conduzida principalmente por <b>{primary_cause}</b>.
        </p>
    </div>

    <table style="width:100%;border-spacing:12px;margin-bottom:20px;">
        <tr>
            {card("Regime Macro", regime, "Classificação do ciclo", status_color(regime))}
            {card("Sinal Operacional", signal, "Direção tática", status_color(signal))}
            {card("Risco de Ruína", ruin_risk, "Governança de sobrevivência", status_color(ruin_risk))}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">1. Gatilhos de Decisão</h2>

    <table style="width:100%;border-collapse:collapse;background:#020617;border:1px solid #1f2937;border-radius:14px;overflow:hidden;">
        {flag_row("Runway inferior a 12 meses", runway_fail)}
        {flag_row("Survival Kill Switch acionado", survival_ks)}
        {flag_row("Forced Selling identificado", forced_sell)}
        {flag_row("Liquidez operacional crítica", liquidity_critical)}
        {flag_row("Fragilidade de contraparte", counterparty_fail)}
        {flag_row("Disfunção macro extrema", macro_fail)}
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">2. Matriz dos Motores</h2>

    <table style="width:100%;border-collapse:collapse;background:#020617;border:1px solid #1f2937;border-radius:14px;overflow:hidden;">
        <tr>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Motor</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Status</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Score / Métrica</th>
        </tr>
        {engine_row("Macro Engine", regime, fmt(macro_conviction))}
        {engine_row("Market Data Engine", market_status, fmt(market_score))}
        {engine_row("Allocation Advisor", allocation_level, fmt(allocation_score))}
        {engine_row("Survival Engine", survival_status, fmt(survival_score))}
        {engine_row("Stress Engine", stress_level, fmt(stress_score))}
        {engine_row("Risk Budget Engine", risk_budget_level, fmt(risk_budget_score))}
        {engine_row("Liquidity Engine", liquidity_level, fmt(liquidity_score))}
        {engine_row("Counterparty Engine", counterparty_level, fmt(counterparty_score))}
        {engine_row("Governance Engine", final_verdict, committee_action)}
        {engine_row("AI Auditor Determinístico", ai_status, fmt(ai_score))}
        {engine_row("OpenAI Auditor", openai_verdict, fmt(openai_score))}
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">3. Alinhamento da Carteira ao Modelo</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("Allocation Score", fmt(allocation_score), "Aderência ao alvo operacional", status_color(allocation_level))}
            {card("Allocation Level", allocation_level, "Classificação de alinhamento", status_color(allocation_level))}
            {card("Model Drift", f"{fmt(model_drift)}%", "Distância total ao modelo", status_color(allocation_level))}
        </tr>
    </table>

    <table style="width:100%;border-spacing:12px;margin-top:8px;">
        <tr>
            {card("Top Gap Asset", top_gap_asset, "Maior desvio individual", "#38bdf8")}
            {card("Top Gap", f"{fmt(top_gap_abs)}%", "Desvio absoluto", status_color(allocation_level))}
            {card("Turnover Recomendado", f"{fmt(turnover_recommended)}%", "Execução sujeita ao limite de giro", "#38bdf8")}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">4. Alvo Operacional Recomendado</h2>

    <table style="width:100%;border-collapse:collapse;background:#020617;border:1px solid #1f2937;border-radius:14px;overflow:hidden;">
        <tr>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Ativo</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Atual</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Alvo</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Desvio</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Ação</th>
            <th style="padding:10px;color:#9ca3af;text-align:left;">Prioridade</th>
        </tr>
        {allocation_table_rows}
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">5. Sobrevivência Operacional</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("Runway", fmt(runway_months), "Política mínima: 12 meses", status_color("CRITICO" if runway_fail else "OK"))}
            {card("Survival Score", fmt(survival_score), survival_status, status_color(survival_status))}
            {card("Kill Switch", survival_kill_switch, "Controle anti-ruína", status_color("CRITICO" if survival_ks else "OK"))}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">6. Estresse, Liquidez e Risco</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("Max Drawdown", f"{fmt(max_drawdown)}%", f"Stress: {stress_level}", status_color(stress_level))}
            {card("Forced Selling", forced_selling, "Venda forçada em stress", status_color("CRITICO" if forced_sell else "OK"))}
            {card("Risk Budget", risk_budget_level, f"{top_risk_asset} / {fmt(top_risk_contribution)}%", status_color(risk_budget_level))}
        </tr>
    </table>

    <table style="width:100%;border-spacing:12px;margin-top:8px;">
        <tr>
            {card("Liquidity", liquidity_level, f"Haircut: {fmt(haircut)}%", status_color(liquidity_level))}
            {card("Valor Líquido Operacional", f"US${fmt(liquid_value)}", "Após haircuts operacionais", "#38bdf8")}
            {card("Counterparty", counterparty_level, f"Maior: {largest_counterparty}", status_color(counterparty_level))}
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">7. Painel Macroeconômico</h2>

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
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(dxy_proxy)}</td>
            <td style="padding:12px;color:#9ca3af;">VIX</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(vix)}</td>
        </tr>
        <tr>
            <td style="padding:12px;color:#9ca3af;">Fed Assets</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(fed_assets)}</td>
            <td style="padding:12px;color:#9ca3af;">Macro Score</td>
            <td style="padding:12px;color:#ffffff;font-weight:bold;">{fmt(macro_score)}</td>
        </tr>
    </table>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">8. Interpretação Macro</h2>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:20px;">
        {macro_text}
    </div>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">9. Condições para Revalidação</h2>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:20px;color:#d1d5db;line-height:1.7;">
        <ol style="margin:0;padding-left:22px;">
            <li>Manter runway operacional acima de 12 meses.</li>
            <li>Confirmar Survival Kill Switch = False.</li>
            <li>Confirmar ausência de Forced Selling nos cenários de stress.</li>
            <li>Reduzir desalinhamento material contra o Allocation Advisor.</li>
            <li>Revalidar Risk Budget, Liquidity e Counterparty após ajustes.</li>
            <li>Arquivar novo relatório executivo e logs de auditoria.</li>
        </ol>
    </div>

    <h2 style="color:#f9fafb;font-size:22px;margin:28px 0 14px 0;">10. Auditoria Independente de IA</h2>

    <table style="width:100%;border-spacing:12px;">
        <tr>
            {card("AI Determinística", ai_status, f"Score: {fmt(ai_score)}", status_color(ai_status))}
            {card("OpenAI Verdict", openai_verdict, f"Status: {openai_status}", status_color(openai_verdict))}
            {card("OpenAI Score", fmt(openai_score), f"Confiança: {fmt(openai_confidence)}", status_color(openai_verdict))}
        </tr>
    </table>

    <table style="width:100%;border-spacing:12px;margin-top:8px;">
        <tr>
            {card("Severity", openai_severity, "Severidade do risco", status_color(openai_severity))}
            {card("False Positive", openai_false_positive, "Risco de falso positivo", status_color(openai_false_positive))}
            {card("False Negative", openai_false_negative, "Risco de falso negativo", status_color(openai_false_negative))}
        </tr>
    </table>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:20px;margin-top:14px;">
        <h3 style="margin-top:0;color:#60a5fa;">Causa Raiz Identificada</h3>
        <p style="color:#d1d5db;line-height:1.7;">{openai_root_cause}</p>

        <h3 style="color:#60a5fa;">Resumo Executivo da IA</h3>
        <p style="color:#d1d5db;line-height:1.7;">{openai_summary}</p>

        <h3 style="color:#60a5fa;">Risco de Inconsistência Material</h3>
        <p style="color:#d1d5db;line-height:1.7;">Material inconsistency: <b>{openai_material_inconsistency}</b></p>

        <h3 style="color:#60a5fa;">Recomendação de Governança</h3>
        <p style="color:#d1d5db;line-height:1.7;">{openai_governance}</p>

        <h3 style="color:#60a5fa;">Parecer Final</h3>
        <p style="color:#d1d5db;line-height:1.7;">{openai_final}</p>
    </div>

    <div style="background:#020617;border:1px solid #1f2937;border-radius:14px;padding:20px;margin-top:26px;">
        <h2 style="margin:0 0 12px 0;color:#f9fafb;font-size:20px;">Conclusão do Comitê</h2>
        <p style="color:#d1d5db;line-height:1.7;margin:0;">
            O sistema classificou o ambiente macro como <b>{regime}</b>, com sinal operacional
            <b>{signal}</b>. A decisão final do comitê é
            <b style="color:{verdict_color};">{final_verdict}</b>, pois o fator determinante foi
            <b>{primary_cause}</b>. A ação recomendada é <b>{committee_action}</b>.
            O Allocation Advisor classificou a carteira como <b>{allocation_level}</b>,
            com score <b>{fmt(allocation_score)}</b> e drift de modelo de
            <b>{fmt(model_drift)}%</b>. O maior desvio identificado foi em
            <b>{top_gap_asset}</b>, com gap de <b>{fmt(top_gap_abs)}%</b>.
            A auditoria independente de IA classificou o parecer como
            <b>{openai_verdict}</b>, com score <b>{fmt(openai_score)}</b>
            e severidade <b>{openai_severity}</b>.
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
