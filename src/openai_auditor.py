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

    payload = {}

    for name, path in files.items():
        payload[name] = read_latest(path)

    return payload


def run_openai_auditor():
    OUTPUT_DIR.mkdir(exist_ok=True)

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        text = "OPENAI_API_KEY ausente. Auditoria OpenAI não executada."
        result = pd.DataFrame([{
            "timestamp_utc": utc_now(),
            "openai_audit_status": "NAO_EXECUTADO",
            "openai_audit_text": text,
        }])
        result.to_csv("outputs/openai_audit_report.csv", index=False)
        print(text)
        return {"openai_audit_report": result}

    payload = build_audit_payload()

    prompt = f"""
Você é um auditor institucional de risco e governança.

Sua função é avaliar se o robô de investimentos agiu de forma coerente.
Você NÃO deve recomendar ordens de compra ou venda.
Você NÃO deve substituir o Governance Engine.
Você deve apenas auditar a decisão e explicar a causa raiz.

Dados dos motores:
{payload}

Responda em português, com estrutura:

1. VEREDITO DA AUDITORIA
2. CAUSA RAIZ
3. COERÊNCIA ENTRE MOTORES
4. POSSÍVEIS INCONSISTÊNCIAS
5. RISCO DE FALSO POSITIVO OU FALSO NEGATIVO
6. RECOMENDAÇÃO DE GOVERNANÇA
7. CONCLUSÃO FINAL

Se não houver inconsistências, diga explicitamente:
"Nenhuma inconsistência material identificada."

Se houver falha operacional, explique se ela decorre de runway, kill switch,
forced selling, liquidez, contraparte ou risk budget.
"""

    try:
        client = OpenAI(api_key=api_key)

        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
            temperature=0.1,
        )

        text = response.output_text
        status = "EXECUTADO"

    except Exception as e:
        text = f"Falha ao executar OpenAI Auditor: {e}"
        status = "ERRO"

    result = pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "openai_audit_status": status,
        "openai_audit_text": text,
    }])

    result.to_csv("outputs/openai_audit_report.csv", index=False)

    print("====================================================")
    print("OPENAI AUDITOR — QUALITATIVE REVIEW")
    print("====================================================")
    print(f"Status: {status}")
    print(text[:1500])
    print("====================================================")

    return {
        "openai_audit_report": result,
    }
