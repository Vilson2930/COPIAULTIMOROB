from pathlib import Path
from datetime import datetime, timezone
import pandas as pd


OUTPUT_DIR = Path("outputs")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def read_latest(path):
    p = Path(path)
    if not p.exists():
        return {}
    try:
        df = pd.read_csv(p)
        if df.empty:
            return {}
        return df.iloc[-1].to_dict()
    except Exception:
        return {}


def as_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def as_bool(value):
    return str(value).upper().strip() in ["TRUE", "1", "SIM", "YES"]


def ok_fail(condition):
    return "OK" if condition else "FALHA"


def run_ai_auditor():
    OUTPUT_DIR.mkdir(exist_ok=True)

    survival = read_latest("outputs/survival_audit.csv")
    stress = read_latest("outputs/stress_summary_v2.csv")
    risk_budget = read_latest("outputs/risk_budget_summary.csv")
    liquidity = read_latest("outputs/liquidity_summary.csv")
    counterparty = read_latest("outputs/counterparty_summary.csv")
    committee = read_latest("outputs/risk_committee_integrated.csv")

    final_verdict = str(committee.get("final_verdict", "N/D"))
    committee_action = str(committee.get("committee_action", "N/D"))

    runway = as_float(survival.get("runway_months"))
    ruin_risk = str(survival.get("ruin_risk", "N/D"))
    survival_kill_switch = as_bool(survival.get("survival_kill_switch"))

    stress_score = as_float(stress.get("stress_score"))
    stress_level = str(stress.get("stress_level", stress.get("robustez", "N/D")))
    forced_selling = as_bool(stress.get("forced_selling_any"))

    risk_budget_score = as_float(risk_budget.get("risk_budget_score"))
    risk_budget_level = str(risk_budget.get("risk_budget_level", "N/D"))
    top_risk_asset = str(risk_budget.get("top_risk_asset", "N/D"))
    max_risk_contribution = as_float(risk_budget.get("max_risk_contribution_pct"))

    liquidity_score = as_float(liquidity.get("liquidity_score"))
    liquidity_level = str(liquidity.get("liquidity_level", "N/D"))

    counterparty_score = as_float(counterparty.get("counterparty_score"))
    counterparty_level = str(counterparty.get("counterparty_level", "N/D"))

    tests = []

    survival_failure = survival_kill_switch or runway < 12 or ruin_risk == "ALTO"

    tests.append({
        "teste": "Survival domina governança",
        "resultado": ok_fail(
            not survival_failure
            or final_verdict == "REPROVADO_OPERACIONALMENTE"
        ),
        "observacao": "Falha operacional deve gerar reprovação operacional.",
    })

    tests.append({
        "teste": "Runway mínimo",
        "resultado": ok_fail(
            not runway < 12
            or survival_kill_switch
        ),
        "observacao": f"Runway atual: {runway:.2f} meses.",
    })

    tests.append({
        "teste": "Forced Selling",
        "resultado": ok_fail(
            not forced_selling
            or stress_level in ["CRITICO", "CRITICA"]
            or stress_score <= 40
        ),
        "observacao": "Forced Selling deve elevar severidade do Stress Engine.",
    })

    tests.append({
        "teste": "Risk Budget crítico",
        "resultado": ok_fail(
            risk_budget_level != "CRITICO"
            or final_verdict in [
                "REPROVADO",
                "REPROVADO_OPERACIONALMENTE",
                "APROVADO_COM_RESSALVAS_CRITICAS",
            ]
            or "CONCENTRACAO" in committee_action
        ),
        "observacao": f"{top_risk_asset}: {max_risk_contribution:.2f}% do risco.",
    })

    tests.append({
        "teste": "Liquidez operacional",
        "resultado": ok_fail(
            liquidity_score >= 55
            or liquidity_level in ["FRAGIL", "CRITICO", "CRÍTICO"]
        ),
        "observacao": f"Liquidity Score: {liquidity_score:.2f}.",
    })

    tests.append({
        "teste": "Contraparte",
        "resultado": ok_fail(
            counterparty_score >= 60
            or counterparty_level in ["CRITICO", "CRÍTICO"]
        ),
        "observacao": f"Counterparty Score: {counterparty_score:.2f}.",
    })

    failures = [t for t in tests if t["resultado"] == "FALHA"]

    if failures:
        audit_status = "FALHA_DE_COHERENCIA"
        audit_score = max(0, 100 - len(failures) * 20)
    else:
        audit_status = "COERENTE"
        audit_score = 100

    if survival_failure:
        root_cause = "RISCO_OPERACIONAL_DE_SOBREVIVENCIA"
    elif forced_selling:
        root_cause = "FORCED_SELLING"
    elif risk_budget_level == "CRITICO":
        root_cause = "CONCENTRACAO_DE_RISCO"
    elif liquidity_score < 55:
        root_cause = "LIQUIDEZ_OPERACIONAL_FRAGIL"
    elif counterparty_score < 60:
        root_cause = "CONTRAPARTE_FRAGIL"
    else:
        root_cause = "SEM_FALHA_CRITICA_PRIMARIA"

    summary = pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "ai_audit_status": audit_status,
        "ai_audit_score": audit_score,
        "root_cause": root_cause,
        "final_verdict": final_verdict,
        "committee_action": committee_action,
        "runway_months": runway,
        "survival_kill_switch": survival_kill_switch,
        "ruin_risk": ruin_risk,
        "forced_selling": forced_selling,
        "stress_level": stress_level,
        "risk_budget_level": risk_budget_level,
        "top_risk_asset": top_risk_asset,
        "max_risk_contribution_pct": max_risk_contribution,
        "liquidity_level": liquidity_level,
        "liquidity_score": liquidity_score,
        "counterparty_level": counterparty_level,
        "counterparty_score": counterparty_score,
    }])

    details = pd.DataFrame(tests)

    summary.to_csv("outputs/ai_audit_summary.csv", index=False)
    details.to_csv("outputs/ai_audit_details.csv", index=False)

    print("====================================================")
    print("AI AUDITOR — DETERMINISTIC GOVERNANCE CHECK")
    print("====================================================")
    print(f"Audit Status:   {audit_status}")
    print(f"Audit Score:    {audit_score}")
    print(f"Root Cause:     {root_cause}")
    print("====================================================")

    return {
        "ai_audit_summary": summary,
        "ai_audit_details": details,
    }
