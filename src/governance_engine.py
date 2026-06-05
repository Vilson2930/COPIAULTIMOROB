import os
from datetime import datetime, timezone

import pandas as pd


OUTPUT_DIR = "outputs"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_outputs_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def calculate_operational_score(survival_audit):
    if survival_audit is None or survival_audit.empty:
        return 0

    latest = survival_audit.iloc[-1]

    runway_months = float(latest.get("runway_months", 0))
    bucket_trilhos = int(latest.get("bucket_trilhos", 0))
    bucket_entidades = int(latest.get("bucket_entidades", 0))
    bucket_jurisdicoes = int(latest.get("bucket_jurisdicoes_validas", 0))
    max_concentration = float(latest.get("max_bucket_concentration", 1.0))
    survival_kill_switch = bool(latest.get("survival_kill_switch", True))

    score = 100

    if runway_months < 24:
        score -= 15
    if runway_months < 18:
        score -= 15
    if runway_months < 12:
        score -= 30

    if bucket_trilhos < 2:
        score -= 25

    if bucket_entidades < 2:
        score -= 20

    if bucket_jurisdicoes < 2:
        score -= 20

    if max_concentration > 0.65:
        score -= 10
    if max_concentration > 0.80:
        score -= 15
    if max_concentration > 0.90:
        score -= 25

    score = max(0, min(100, round(score, 2)))

    if survival_kill_switch:
        return min(score, 40)

    return score


def build_audit_logs(
    latest,
    orders,
    total_value,
    gross_turnover_final,
    turnover_status,
    kill_switch,
):
    timestamp_utc = utc_now()

    audit_log = {
        "timestamp_utc": timestamp_utc,
        "regime": latest["regime"],
        "sinal_operacional": latest["sinal_operacional"],
        "macro_conviction": round(float(latest["macro_conviction"]), 2),
        "confidence_score": round(float(latest["confidence_score"]), 2),
        "macro_momentum": round(float(latest["macro_momentum"]), 2),
        "valor_total_usd": round(float(total_value), 2),
        "giro_final": round(float(gross_turnover_final), 4),
        "status_giro": turnover_status,
        "kill_switch": kill_switch,
        "numero_ordens": len(orders),
    }

    audit_log_df = pd.DataFrame([audit_log])
    orders_log = orders.copy()

    if not orders_log.empty:
        orders_log["timestamp_utc"] = timestamp_utc
        orders_log["regime"] = latest["regime"]
        orders_log["sinal_operacional"] = latest["sinal_operacional"]
        orders_log["macro_conviction"] = float(latest["macro_conviction"])
        orders_log["confidence_score"] = float(latest["confidence_score"])

        preferred_cols = [
            "timestamp_utc",
            "regime",
            "sinal_operacional",
            "macro_conviction",
            "confidence_score",
            "acao",
            "quantidade_atual",
            "preco_atual",
            "valor_atual",
            "peso_atual",
            "peso_alvo",
            "desvio_peso",
            "ajuste_usd",
            "quantidade_ajuste",
        ]

        orders_log = orders_log[
            [col for col in preferred_cols if col in orders_log.columns]
        ]

    ensure_outputs_dir()

    audit_log_df.to_csv(
        os.path.join(OUTPUT_DIR, "audit_log_robo_macro.csv"),
        index=False,
    )

    orders_log.to_csv(
        os.path.join(OUTPUT_DIR, "orders_log_robo_macro.csv"),
        index=True,
    )

    return audit_log_df, orders_log


def run_stress_test(rebalance):
    timestamp_utc = utc_now()

    positions_df = rebalance.copy().reset_index()

    if "index" in positions_df.columns:
        positions_df = positions_df.rename(columns={"index": "ativo"})

    if "ativo" not in positions_df.columns:
        positions_df = positions_df.rename(columns={positions_df.columns[0]: "ativo"})

    positions_df["peso_atual"] = positions_df["peso_atual"].astype(float)
    weights = dict(zip(positions_df["ativo"], positions_df["peso_atual"]))

    stress_scenarios = {
        "CRISE_LIQUIDEZ_GLOBAL": {
            "BTC-USD": -0.45,
            "USDT-USD": 0.00,
            "GLD": 0.08,
            "VOO": -0.25,
            "TLT": 0.05,
            "BOTZ": -0.35,
            "INDA": -0.30,
        },
        "RECESSAO_GLOBAL": {
            "BTC-USD": -0.35,
            "USDT-USD": 0.00,
            "GLD": 0.10,
            "VOO": -0.30,
            "TLT": 0.18,
            "BOTZ": -0.40,
            "INDA": -0.25,
        },
        "INFLACAO_PERSISTENTE": {
            "BTC-USD": 0.10,
            "USDT-USD": 0.00,
            "GLD": 0.18,
            "VOO": -0.10,
            "TLT": -0.20,
            "BOTZ": -0.12,
            "INDA": 0.05,
        },
        "RISK_OFF_GLOBAL": {
            "BTC-USD": -0.30,
            "USDT-USD": 0.00,
            "GLD": 0.05,
            "VOO": -0.20,
            "TLT": 0.08,
            "BOTZ": -0.25,
            "INDA": -0.18,
        },
        "STRESS_SISTEMICO": {
            "BTC-USD": -0.55,
            "USDT-USD": -0.02,
            "GLD": 0.12,
            "VOO": -0.35,
            "TLT": -0.05,
            "BOTZ": -0.45,
            "INDA": -0.35,
        },
    }

    rows = []

    for scenario, returns in stress_scenarios.items():
        portfolio_return = 0.0

        for asset, weight in weights.items():
            portfolio_return += weight * returns.get(asset, 0.0)

        drawdown = min(0.0, portfolio_return)

        rows.append({
            "timestamp_utc": timestamp_utc,
            "cenario": scenario,
            "retorno_estimado_pct": portfolio_return * 100,
            "drawdown_pct": abs(drawdown) * 100,
        })

    stress_results = pd.DataFrame(rows)

    avg_drawdown = stress_results["drawdown_pct"].mean()
    max_drawdown = stress_results["drawdown_pct"].max()

    if max_drawdown <= 10:
        stress_score = 100
        robustez = "ALTA"
    elif max_drawdown <= 20:
        stress_score = 80
        robustez = "ACEITAVEL"
    elif max_drawdown <= 30:
        stress_score = 60
        robustez = "FRAGIL"
    else:
        stress_score = 40
        robustez = "CRITICA"

    stress_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "avg_drawdown_pct": avg_drawdown,
        "max_drawdown_pct": max_drawdown,
        "stress_score": stress_score,
        "robustez": robustez,
        "stress_level": robustez,
        "forced_selling_any": False,
    }])

    ensure_outputs_dir()

    stress_results.to_csv(
        os.path.join(OUTPUT_DIR, "stress_results.csv"),
        index=False,
    )

    stress_summary.to_csv(
        os.path.join(OUTPUT_DIR, "stress_summary.csv"),
        index=False,
    )

    return stress_results, stress_summary


def run_committee_audit(
    latest,
    market_audit,
    rebalance,
    survival_audit,
    gross_turnover_final,
):
    timestamp_utc = utc_now()

    macro_conviction = float(latest["macro_conviction"])
    confidence_score = float(latest["confidence_score"])
    macro_score = float(latest["macro_score"])

    macro_engine_score = (
        macro_score * 0.50
        + confidence_score * 0.30
        + macro_conviction * 0.20
    )

    latest_market_audit = market_audit.iloc[-1]

    market_data_score = float(latest_market_audit.get("market_data_score", 100))
    market_quality_score = float(latest_market_audit.get("market_quality_score", 100))

    market_engine_score = (
        market_data_score * 0.50
        + market_quality_score * 0.50
    )

    turnover_pct = float(gross_turnover_final * 100)

    if turnover_pct <= 10:
        rebalance_score = 100
    elif turnover_pct <= 25:
        rebalance_score = 90
    elif turnover_pct <= 35:
        rebalance_score = 70
    else:
        rebalance_score = 40

    operational_score = calculate_operational_score(survival_audit)

    latest_survival = survival_audit.iloc[-1]

    survival_score = float(latest_survival["survival_score"])
    survival_status = str(latest_survival["survival_status"])
    ruin_risk = str(latest_survival["ruin_risk"])
    survival_kill_switch = bool(latest_survival["survival_kill_switch"])

    committee_score = (
        macro_engine_score * 0.30
        + market_engine_score * 0.20
        + rebalance_score * 0.15
        + operational_score * 0.15
        + survival_score * 0.20
    )

    if committee_score >= 85:
        committee_level = "INSTITUCIONAL"
    elif committee_score >= 70:
        committee_level = "ACEITAVEL"
    elif committee_score >= 55:
        committee_level = "RESSALVAS"
    else:
        committee_level = "CRITICO"

    if survival_kill_switch:
        committee_action = "REPROVAR_E_CORRIGIR_BUCKET"
        final_verdict = "REPROVADO_OPERACIONALMENTE"
    elif committee_score >= 85:
        committee_action = "APROVAR"
        final_verdict = "APROVADO"
    elif committee_score >= 70:
        committee_action = "APROVAR_COM_RESSALVAS"
        final_verdict = "APROVADO_COM_RESSALVAS"
    else:
        committee_action = "REPROVAR"
        final_verdict = "REPROVADO"

    committee_audit = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "macro_engine_score": macro_engine_score,
        "market_engine_score": market_engine_score,
        "rebalance_score": rebalance_score,
        "operational_score": operational_score,
        "survival_score": survival_score,
        "survival_status": survival_status,
        "ruin_risk": ruin_risk,
        "survival_kill_switch": survival_kill_switch,
        "committee_score": committee_score,
        "committee_level": committee_level,
        "committee_action": committee_action,
        "final_verdict": final_verdict,
    }])

    ensure_outputs_dir()

    committee_audit.to_csv(
        os.path.join(OUTPUT_DIR, "committee_audit.csv"),
        index=False,
    )

    return committee_audit


def extract_optional_score(summary, column, default=100):
    if summary is None or summary.empty:
        return default

    latest = summary.iloc[-1]

    if column not in latest:
        return default

    try:
        return float(latest[column])
    except Exception:
        return default


def extract_optional_text(summary, column, default="N/D"):
    if summary is None or summary.empty:
        return default

    latest = summary.iloc[-1]

    if column not in latest:
        return default

    try:
        return str(latest[column])
    except Exception:
        return default


def run_integrated_risk_committee(
    committee_audit,
    stress_summary,
    deterioration_audit,
    liquidity_forecast,
    survival_audit,
    risk_budget_summary=None,
    liquidity_summary=None,
    counterparty_summary=None,
):
    timestamp_utc = utc_now()

    committee_latest = committee_audit.iloc[-1]
    stress_latest = stress_summary.iloc[-1]
    deterioration_latest = deterioration_audit.iloc[-1]
    liquidity_latest = liquidity_forecast.iloc[-1]
    survival_latest = survival_audit.iloc[-1]

    committee_score = float(committee_latest["committee_score"])
    stress_score = float(stress_latest["stress_score"])
    deterioration_score = float(deterioration_latest["deterioration_score"])
    future_liquidity_score = float(liquidity_latest["future_liquidity_score"])
    survival_score = float(survival_latest["survival_score"])

    risk_budget_score = extract_optional_score(
        risk_budget_summary,
        "risk_budget_score",
        default=100,
    )

    risk_budget_level = extract_optional_text(
        risk_budget_summary,
        "risk_budget_level",
        default="N/D",
    )

    top_risk_contribution = extract_optional_score(
        risk_budget_summary,
        "max_risk_contribution_pct",
        default=0,
    )

    top_risk_asset = extract_optional_text(
        risk_budget_summary,
        "top_risk_asset",
        default="N/D",
    )

    liquidity_score = extract_optional_score(
        liquidity_summary,
        "liquidity_score",
        default=100,
    )

    counterparty_score = extract_optional_score(
        counterparty_summary,
        "counterparty_score",
        default=100,
    )

    survival_kill_switch = bool(survival_latest["survival_kill_switch"])
    ruin_risk = str(survival_latest["ruin_risk"])
    future_regime = str(liquidity_latest["future_regime"])
    early_warning = bool(deterioration_latest["early_warning"])

    stress_level = str(
        stress_latest.get("stress_level", stress_latest.get("robustez", ""))
    )

    forced_selling_any = bool(
        stress_latest.get("forced_selling_any", False)
    )

    integrated_risk_score = (
        committee_score * 0.10
        + stress_score * 0.20
        + survival_score * 0.15
        + deterioration_score * 0.10
        + future_liquidity_score * 0.10
        + risk_budget_score * 0.20
        + liquidity_score * 0.075
        + counterparty_score * 0.075
    )

    critical_flags = []

    if survival_kill_switch:
        critical_flags.append("SURVIVAL_KILL_SWITCH")

    if ruin_risk == "ALTO":
        critical_flags.append("RUIN_RISK_ALTO")

    if early_warning:
        critical_flags.append("EARLY_WARNING_MACRO")

    if future_regime in ["CONTRACAO", "NEUTRO_FRAGIL"]:
        critical_flags.append("LIQUIDEZ_PROSPECTIVA_FRAGIL")

    if stress_score < 70:
        critical_flags.append("STRESS_MODERADO_OU_FRAGIL")

    if stress_level in ["CRITICO", "CRITICA"]:
        critical_flags.append("STRESS_CRITICO")

    if forced_selling_any:
        critical_flags.append("FORCED_SELLING_STRESS")

    if top_risk_contribution >= 80:
        critical_flags.append("DOMINANCIA_DE_RISCO")

    if risk_budget_score <= 40 or risk_budget_level == "CRITICO":
        critical_flags.append("RISK_BUDGET_CRITICO")

    elif risk_budget_score < 60 or risk_budget_level == "CONCENTRADO":
        critical_flags.append("RISK_BUDGET_CONCENTRADO")

    if liquidity_score < 60:
        critical_flags.append("LIQUIDITY_FRAGIL")

    if counterparty_score < 60:
        critical_flags.append("COUNTERPARTY_FRAGIL")

    hard_failure = (
        survival_kill_switch
        or ruin_risk == "ALTO"
    )

    hard_elevated = (
        forced_selling_any
        or stress_level in ["CRITICO", "CRITICA"]
        or liquidity_score < 50
        or counterparty_score < 50
    )

    risk_budget_critical = (
        risk_budget_score <= 40
        or risk_budget_level == "CRITICO"
        or top_risk_contribution >= 80
    )

    risk_budget_concentrated = (
        risk_budget_score < 60
        or risk_budget_level == "CONCENTRADO"
        or top_risk_contribution >= 65
    )

    concentration_with_fragility = (
        risk_budget_concentrated
        and (
            stress_score < 70
            or liquidity_score < 70
            or counterparty_score < 70
            or future_liquidity_score < 60
        )
    )

    if hard_failure:
        integrated_risk_level = "CRITICO"

    elif hard_elevated:
        integrated_risk_level = "ELEVADO"

    elif risk_budget_critical:
        integrated_risk_level = "ELEVADO"

    elif concentration_with_fragility:
        integrated_risk_level = "ELEVADO"

    elif risk_budget_concentrated:
        integrated_risk_level = "MODERADO"

    elif integrated_risk_score >= 85:
        integrated_risk_level = "BAIXO"

    elif integrated_risk_score >= 70:
        integrated_risk_level = "MODERADO"

    elif integrated_risk_score >= 55:
        integrated_risk_level = "ELEVADO"

    else:
        integrated_risk_level = "CRITICO"

    if integrated_risk_level == "CRITICO":
        committee_action = "BLOQUEAR_RISCO_E_CORRIGIR_OPERACIONAL"

    elif integrated_risk_level == "ELEVADO":
        if risk_budget_critical:
            committee_action = "REDUZIR_CONCENTRACAO_DE_RISCO_E_REVALIDAR"
        else:
            committee_action = "REDUZIR_RISCO_E_REVALIDAR"

    elif integrated_risk_level == "MODERADO":
        if risk_budget_concentrated:
            committee_action = "MANTER_COM_RESSALVAS_E_MONITORAR_CONCENTRACAO"
        else:
            committee_action = "MANTER_COM_RESSALVAS"

    else:
        committee_action = "MANTER_APROVADO"

    if survival_kill_switch:
        final_verdict = "REPROVADO_OPERACIONALMENTE"

    elif integrated_risk_level == "CRITICO":
        final_verdict = "REPROVADO"

    elif integrated_risk_level == "ELEVADO":
        final_verdict = "APROVADO_COM_RESSALVAS_CRITICAS"

    elif integrated_risk_level == "MODERADO":
        final_verdict = "APROVADO_COM_RESSALVAS"

    else:
        final_verdict = "APROVADO"

    risk_committee_integrated = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "committee_score": committee_score,
        "stress_score": stress_score,
        "deterioration_score": deterioration_score,
        "future_liquidity_score": future_liquidity_score,
        "survival_score": survival_score,
        "risk_budget_score": risk_budget_score,
        "risk_budget_level": risk_budget_level,
        "top_risk_asset": top_risk_asset,
        "top_risk_contribution_pct": top_risk_contribution,
        "liquidity_score": liquidity_score,
        "counterparty_score": counterparty_score,
        "integrated_risk_score": integrated_risk_score,
        "integrated_risk_level": integrated_risk_level,
        "committee_action": committee_action,
        "final_verdict": final_verdict,
        "critical_flags": " | ".join(critical_flags),
    }])

    ensure_outputs_dir()

    risk_committee_integrated.to_csv(
        os.path.join(OUTPUT_DIR, "risk_committee_integrated.csv"),
        index=False,
    )

    return risk_committee_integrated


def run_final_opinion(
    risk_committee_integrated,
    committee_audit,
    survival_audit,
    stress_summary,
    deterioration_audit,
    liquidity_forecast,
):
    timestamp_utc = utc_now()

    risk_latest = risk_committee_integrated.iloc[-1]
    survival_latest = survival_audit.iloc[-1]
    stress_latest = stress_summary.iloc[-1]
    deterioration_latest = deterioration_audit.iloc[-1]
    liquidity_latest = liquidity_forecast.iloc[-1]

    final_verdict = str(risk_latest["final_verdict"])
    committee_action = str(risk_latest["committee_action"])
    integrated_risk_level = str(risk_latest["integrated_risk_level"])
    integrated_risk_score = float(risk_latest["integrated_risk_score"])

    survival_status = str(survival_latest["survival_status"])
    ruin_risk = str(survival_latest["ruin_risk"])
    survival_kill_switch = bool(survival_latest["survival_kill_switch"])

    stress_score = float(stress_latest["stress_score"])
    robustez = str(stress_latest.get("robustez", stress_latest.get("stress_level", "N/D")))
    forced_selling_any = bool(stress_latest.get("forced_selling_any", False))

    deterioration_score = float(deterioration_latest["deterioration_score"])
    early_warning = bool(deterioration_latest["early_warning"])

    future_liquidity_score = float(liquidity_latest["future_liquidity_score"])
    future_regime = str(liquidity_latest["future_regime"])

    if final_verdict == "APROVADO":
        executive_status = "APROVADO"
    elif final_verdict in [
        "APROVADO_COM_RESSALVAS",
        "APROVADO_COM_RESSALVAS_CRITICAS",
    ]:
        executive_status = "APROVADO_COM_RESSALVAS"
    elif final_verdict == "REPROVADO_OPERACIONALMENTE":
        executive_status = "REPROVADO_OPERACIONALMENTE"
    else:
        executive_status = "REPROVADO"

    required_evidence = []

    if survival_kill_switch:
        required_evidence.append(
            "Formalizar bucket de sobrevivência com mínimo 2 trilhos, 2 entidades e 2 jurisdições válidas."
        )

    if ruin_risk == "ALTO":
        required_evidence.append(
            "Reduzir risco de ruína operacional antes de nova aprovação."
        )

    if forced_selling_any:
        required_evidence.append(
            "Reduzir risco de forced selling identificado no stress test."
        )

    if future_regime in ["NEUTRO_FRAGIL", "CONTRACAO"]:
        required_evidence.append(
            "Monitorar liquidez prospectiva antes de aumentar risco adicional."
        )

    if stress_score < 70:
        required_evidence.append(
            "Revalidar stress test após qualquer aumento relevante de risco."
        )

    if early_warning:
        required_evidence.append(
            "Ativar revisão macro extraordinária por deterioração antecipada."
        )

    if committee_action == "REDUZIR_CONCENTRACAO_DE_RISCO_E_REVALIDAR":
        required_evidence.append(
            "Reduzir dominância de risco do ativo principal e revalidar o risk budget."
        )

    if not required_evidence:
        required_evidence.append(
            "Manter rotina de revalidação periódica e logs de auditoria."
        )

    ruin_risk_before = ruin_risk

    if survival_kill_switch:
        ruin_risk_after = "BAIXO_CONDICIONADO_A_CORRECAO_DO_BUCKET"
        revalidation_deadline_days = 7
    elif forced_selling_any:
        ruin_risk_after = "MEDIO_CONDICIONADO_A_REDUCAO_DE_FORCED_SELLING"
        revalidation_deadline_days = 14
    elif committee_action == "REDUZIR_CONCENTRACAO_DE_RISCO_E_REVALIDAR":
        ruin_risk_after = "MEDIO_CONDICIONADO_A_REDUCAO_DE_CONCENTRACAO"
        revalidation_deadline_days = 14
    else:
        ruin_risk_after = ruin_risk
        revalidation_deadline_days = 30

    final_opinion = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "executive_status": executive_status,
        "final_verdict": final_verdict,
        "committee_action": committee_action,
        "integrated_risk_score": integrated_risk_score,
        "integrated_risk_level": integrated_risk_level,
        "survival_status": survival_status,
        "ruin_risk_before": ruin_risk_before,
        "ruin_risk_after": ruin_risk_after,
        "survival_kill_switch": survival_kill_switch,
        "stress_score": stress_score,
        "robustez": robustez,
        "forced_selling_any": forced_selling_any,
        "deterioration_score": deterioration_score,
        "early_warning": early_warning,
        "future_liquidity_score": future_liquidity_score,
        "future_regime": future_regime,
        "required_evidence": " | ".join(required_evidence),
        "revalidation_deadline_days": revalidation_deadline_days,
    }])

    ensure_outputs_dir()

    final_opinion.to_csv(
        os.path.join(OUTPUT_DIR, "final_opinion.csv"),
        index=False,
    )

    return final_opinion


def build_executive_dashboard(
    macro_engine_audit,
    risk_committee_integrated,
    survival_audit,
    liquidity_forecast,
):
    timestamp_utc = utc_now()

    macro_latest = macro_engine_audit.iloc[-1]
    risk_latest = risk_committee_integrated.iloc[-1]
    survival_latest = survival_audit.iloc[-1]
    liquidity_latest = liquidity_forecast.iloc[-1]

    dashboard = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "regime": macro_latest["regime"],
        "sinal": macro_latest["sinal_operacional"],
        "macro_conviction": round(float(macro_latest["macro_conviction"]), 2),
        "confidence": round(float(macro_latest["confidence_score"]), 2),
        "future_regime": liquidity_latest["future_regime"],
        "survival_status": survival_latest["survival_status"],
        "ruin_risk": survival_latest["ruin_risk"],
        "committee_level": risk_latest["integrated_risk_level"],
        "committee_action": risk_latest["committee_action"],
        "final_verdict": risk_latest["final_verdict"],
    }])

    ensure_outputs_dir()

    dashboard.to_csv(
        os.path.join(OUTPUT_DIR, "executive_dashboard.csv"),
        index=False,
    )

    return dashboard


def run_governance_engine(
    latest,
    macro_engine_audit,
    market_audit,
    rebalance,
    orders,
    total_value,
    gross_turnover_final,
    turnover_status,
    kill_switch,
    survival_audit,
    deterioration_audit,
    liquidity_forecast,
    stress_summary_override=None,
    risk_budget_summary=None,
    liquidity_summary=None,
    counterparty_summary=None,
):
    audit_log_df, orders_log = build_audit_logs(
        latest=latest,
        orders=orders,
        total_value=total_value,
        gross_turnover_final=gross_turnover_final,
        turnover_status=turnover_status,
        kill_switch=kill_switch,
    )

    stress_results, stress_summary_default = run_stress_test(
        rebalance=rebalance,
    )

    if stress_summary_override is not None:
        stress_summary = stress_summary_override
    else:
        stress_summary = stress_summary_default

    committee_audit = run_committee_audit(
        latest=latest,
        market_audit=market_audit,
        rebalance=rebalance,
        survival_audit=survival_audit,
        gross_turnover_final=gross_turnover_final,
    )

    risk_committee_integrated = run_integrated_risk_committee(
        committee_audit=committee_audit,
        stress_summary=stress_summary,
        deterioration_audit=deterioration_audit,
        liquidity_forecast=liquidity_forecast,
        survival_audit=survival_audit,
        risk_budget_summary=risk_budget_summary,
        liquidity_summary=liquidity_summary,
        counterparty_summary=counterparty_summary,
    )

    final_opinion = run_final_opinion(
        risk_committee_integrated=risk_committee_integrated,
        committee_audit=committee_audit,
        survival_audit=survival_audit,
        stress_summary=stress_summary,
        deterioration_audit=deterioration_audit,
        liquidity_forecast=liquidity_forecast,
    )

    executive_dashboard = build_executive_dashboard(
        macro_engine_audit=macro_engine_audit,
        risk_committee_integrated=risk_committee_integrated,
        survival_audit=survival_audit,
        liquidity_forecast=liquidity_forecast,
    )

    print("====================================================")
    print("GOVERNANCE ENGINE FINALIZADO")
    print("====================================================")
    print(f"Final Verdict: {risk_committee_integrated.iloc[-1]['final_verdict']}")
    print(f"Dashboard:     outputs/executive_dashboard.csv")
    print("====================================================")

    return {
        "audit_log": audit_log_df,
        "orders_log": orders_log,
        "stress_results": stress_results,
        "stress_summary": stress_summary,
        "committee_audit": committee_audit,
        "risk_committee_integrated": risk_committee_integrated,
        "final_opinion": final_opinion,
        "executive_dashboard": executive_dashboard,
    }
