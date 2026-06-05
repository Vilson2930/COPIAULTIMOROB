import json
import os
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from openai import OpenAI


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


def safe_json_loads(text):
    try:
        return json.loads(text)
    except Exception:
        return None


def build_audit_payload():
    files = {
        "committee": "outputs/risk_committee_integrated.csv",
        "survival": "outputs/survival_audit.csv",
        "stress": "outputs/stress_summary_v2.csv",
        "risk_budget": "outputs/risk_budget_summary.csv",
        "liquidity": "outputs/liquidity_summary.csv",
        "counterparty": "outputs/counterparty_summary.csv",
        "ai_audit": "outputs/ai_audit_summary.csv",
    }

    return {name: read_latest(path) for name, path in files.items()}


def fallback_result(status, text):
    timestamp = utc_now()

    summary = pd.DataFrame([{
        "timestamp_utc": timestamp,
        "openai_audit_status": status,
        "audit_verdict": "N/D",
        "audit_score": 0,
        "audit_confidence": 0,
        "severity": "N/D",
        "root_cause": "N/D",
        "material_inconsistency": "N/D",
        "false_positive_risk": "N/D",
        "false_negative_risk": "N/D",
        "executive_summary": text,
        "governance_recommendation": "N/D",
        "final_opinion": text,
    }])

    report = pd.DataFrame([{
        "timestamp_utc": timestamp,
        "openai_audit_status": status,
        "openai_audit_text": text,
    }])

    details = pd.DataFrame([{
        "timestamp_utc": timestamp,
        "engine_consistency": "{}",
        "main_evidences": "[]",
        "concerns": "[]",
    }])

    summary.to_csv("outputs/openai_audit_summary.csv", index=False)
    report.to_csv("outputs/openai_audit_report.csv", index=False)
    details.to_csv("outputs/openai_audit_details.csv", index=False)

    return {
        "openai_audit_summary": summary,
        "openai_audit_details": details,
        "openai_audit_report": report,
    }


def run_openai_auditor():
    OUTPUT_DIR.mkdir(exist_ok=True)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        text = "OPENAI_API_KEY ausente. Auditoria OpenAI não executada."
        print(text)
        return fallback_result("NAO_EXECUTADO", text)

    payload = build_audit_payload()

    prompt = f"""
Você é um auditor institucional de risco e governança.

Sua função:
- Auditar se o robô agiu de forma coerente.
- NÃO recomendar ordens de compra ou venda.
- NÃO substituir o Governance Engine.
- Procurar inconsistências entre motores.
- Explicar causa raiz e risco de falso positivo/falso negativo.

Dados dos motores:
{payload}

Responda APENAS em JSON válido, sem markdown, no formato exato:

{{
  "audit_verdict": "COERENTE | INCONSISTENTE | COERENTE_COM_RESSALVAS",
  "audit_score": 0,
  "audit_confidence": 0,
  "severity": "BAIXA | MEDIA | ALTA | CRITICA",
  "root_cause": "texto curto",
  "material_inconsistency": true,
  "false_positive_risk": "BAIXO | MEDIO | ALTO",
  "false_negative_risk": "BAIXO | MEDIO | ALTO",
  "executive_summary": "resumo executivo em até 120 palavras",
  "engine_consistency": {{
    "survival": "comentário curto",
    "stress": "comentário curto",
    "risk_budget": "comentário curto",
    "liquidity": "comentário curto",
    "counterparty": "comentário curto",
    "governance": "comentário curto"
  }},
  "main_evidences": [
    "evidência 1",
    "evidência 2",
    "evidência 3"
  ],
  "concerns": [
    "preocupação 1",
    "preocupação 2"
  ],
  "governance_recommendation": "recomendação de governança, sem ordem de compra/venda",
  "final_opinion": "parecer final obrigatório em até 80 palavras. Nunca use N/D."
}}

Regras:
- audit_score deve ser de 0 a 100.
- audit_confidence deve ser de 0 a 100.
- Se não houver inconsistência material, material_inconsistency deve ser false.
- Se os motores estiverem coerentes, use audit_verdict = "COERENTE".
- final_opinion é obrigatório e nunca pode ser vazio, N/D ou null.
- Não invente dados que não estejam no payload.
"""

    try:
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0.0,
        )

        raw_text = response.output_text.strip()
        parsed = safe_json_loads(raw_text)

        if parsed is None:
            return fallback_result("ERRO_PARSE_JSON", raw_text)

        if not parsed.get("final_opinion") or str(parsed.get("final_opinion")).strip().upper() in ["N/D", "NONE", "NULL", ""]:
            parsed["final_opinion"] = parsed.get(
                "executive_summary",
                "Parecer final não informado pela auditoria OpenAI."
            )

        if not parsed.get("governance_recommendation"):
            parsed["governance_recommendation"] = (
                "Revalidar a coerência dos motores e arquivar evidências de auditoria."
            )

        timestamp = utc_now()

        summary = pd.DataFrame([{
            "timestamp_utc": timestamp,
            "openai_audit_status": "EXECUTADO",
            "audit_verdict": parsed.get("audit_verdict", "N/D"),
            "audit_score": parsed.get("audit_score", 0),
            "audit_confidence": parsed.get("audit_confidence", 0),
            "severity": parsed.get("severity", "N/D"),
            "root_cause": parsed.get("root_cause", "N/D"),
            "material_inconsistency": parsed.get("material_inconsistency", "N/D"),
            "false_positive_risk": parsed.get("false_positive_risk", "N/D"),
            "false_negative_risk": parsed.get("false_negative_risk", "N/D"),
            "executive_summary": parsed.get("executive_summary", "N/D"),
            "governance_recommendation": parsed.get(
                "governance_recommendation",
                "N/D",
            ),
            "final_opinion": parsed.get(
                "final_opinion",
                parsed.get("executive_summary", "Parecer final não informado pela auditoria OpenAI."),
            ),
        }])

        details = pd.DataFrame([{
            "timestamp_utc": timestamp,
            "engine_consistency": json.dumps(
                parsed.get("engine_consistency", {}),
                ensure_ascii=False,
            ),
            "main_evidences": json.dumps(
                parsed.get("main_evidences", []),
                ensure_ascii=False,
            ),
            "concerns": json.dumps(
                parsed.get("concerns", []),
                ensure_ascii=False,
            ),
        }])

        report = pd.DataFrame([{
            "timestamp_utc": timestamp,
            "openai_audit_status": "EXECUTADO",
            "openai_audit_text": raw_text,
        }])

        summary.to_csv("outputs/openai_audit_summary.csv", index=False)
        details.to_csv("outputs/openai_audit_details.csv", index=False)
        report.to_csv("outputs/openai_audit_report.csv", index=False)

        print("====================================================")
        print("OPENAI AUDITOR — STRUCTURED REVIEW")
        print("====================================================")
        print("Status:              EXECUTADO")
        print(f"Audit Verdict:       {summary.iloc[-1]['audit_verdict']}")
        print(f"Audit Score:         {summary.iloc[-1]['audit_score']}")
        print(f"Confidence:          {summary.iloc[-1]['audit_confidence']}")
        print(f"Severity:            {summary.iloc[-1]['severity']}")
        print(f"Root Cause:          {summary.iloc[-1]['root_cause']}")
        print("----------------------------------------------------")
        print(summary.iloc[-1]["executive_summary"])
        print("----------------------------------------------------")
        print(summary.iloc[-1]["final_opinion"])
        print("====================================================")

        return {
            "openai_audit_summary": summary,
            "openai_audit_details": details,
            "openai_audit_report": report,
        }

    except Exception as e:
        text = f"Falha ao executar OpenAI Auditor: {e}"
        print(text)
        return fallback_result("ERRO", text)
