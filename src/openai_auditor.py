import json
import os
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from openai import OpenAI


OUTPUT_DIR = Path("outputs")

NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
NVIDIA_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"


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
    if not text:
        return None

    cleaned = text.strip()

    # Remove blocos markdown caso o modelo devolva ```json ... ```
    if cleaned.startswith("```"):
        cleaned = cleaned.replace("```json", "", 1)
        cleaned = cleaned.replace("```JSON", "", 1)
        cleaned = cleaned.replace("```", "", 1)

        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]

        cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)

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

    return {
        name: read_latest(path)
        for name, path in files.items()
    }


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

    summary.to_csv(
        "outputs/openai_audit_summary.csv",
        index=False,
    )

    report.to_csv(
        "outputs/openai_audit_report.csv",
        index=False,
    )

    details.to_csv(
        "outputs/openai_audit_details.csv",
        index=False,
    )

    return {
        "openai_audit_summary": summary,
        "openai_audit_details": details,
        "openai_audit_report": report,
    }


def run_openai_auditor():
    OUTPUT_DIR.mkdir(exist_ok=True)

    api_key = os.getenv("NVIDIA_API_KEY")

    if not api_key:
        text = (
            "NVIDIA_API_KEY ausente. "
            "Auditoria NVIDIA Nemotron não executada."
        )

        print(text)

        return fallback_result(
            "NAO_EXECUTADO",
            text,
        )

    payload = build_audit_payload()

    payload_json = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        default=str,
    )

    prompt = f"""
Você é um auditor institucional independente de risco e governança.

Sua função é revisar criticamente a saída de múltiplos motores
determinísticos de um sistema de gestão de portfólio.

OBJETIVO DA AUDITORIA

- Auditar se o robô agiu de forma lógica e coerente.
- Verificar consistência entre os diferentes motores.
- Identificar contradições materiais.
- Identificar concentração de risco.
- Identificar potenciais falsos positivos.
- Identificar potenciais falsos negativos.
- Avaliar se o veredito do Governance Engine é sustentado pelos dados.
- Explicar a principal causa raiz de risco encontrada.

RESTRIÇÕES

- NÃO recomendar ordens específicas de compra.
- NÃO recomendar ordens específicas de venda.
- NÃO substituir o Governance Engine.
- NÃO alterar decisões determinísticas do sistema.
- NÃO inventar dados.
- NÃO utilizar informações externas.
- Basear toda a análise exclusivamente no payload fornecido.

DADOS DOS MOTORES

{payload_json}

Responda APENAS com JSON válido.

Não utilize markdown.
Não utilize blocos ```json.
Não escreva texto antes ou depois do JSON.

Use exatamente esta estrutura:

{{
  "audit_verdict": "COERENTE | INCONSISTENTE | COERENTE_COM_RESSALVAS",
  "audit_score": 0,
  "audit_confidence": 0,
  "severity": "BAIXA | MEDIA | ALTA | CRITICA",
  "root_cause": "texto curto",
  "material_inconsistency": false,
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

  "governance_recommendation":
    "recomendação de governança sem ordem de compra ou venda",

  "final_opinion":
    "parecer final obrigatório em até 80 palavras"
}}

REGRAS DE VALIDAÇÃO

- audit_score deve estar entre 0 e 100.
- audit_confidence deve estar entre 0 e 100.
- material_inconsistency deve ser true ou false.
- Se não houver inconsistência material:
  material_inconsistency = false.
- Se os motores forem coerentes:
  audit_verdict = "COERENTE".
- Se existirem ressalvas sem contradição grave:
  audit_verdict = "COERENTE_COM_RESSALVAS".
- Se existir contradição material:
  audit_verdict = "INCONSISTENTE".
- final_opinion é obrigatório.
- final_opinion nunca pode ser vazio.
- final_opinion nunca pode ser N/D.
- Não invente métricas ausentes.
"""

    try:
        client = OpenAI(
            base_url=NVIDIA_BASE_URL,
            api_key=api_key,
        )

        response = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            temperature=0.0,
            top_p=1.0,
            max_tokens=4096,
            extra_body={
                "chat_template_kwargs": {
                    "enable_thinking": False
                }
            },
        )

        raw_text = (
            response.choices[0]
            .message
            .content
            .strip()
        )

        parsed = safe_json_loads(raw_text)

        if parsed is None:
            return fallback_result(
                "ERRO_PARSE_JSON",
                raw_text,
            )

        if (
            not parsed.get("final_opinion")
            or str(
                parsed.get("final_opinion")
            ).strip().upper()
            in ["N/D", "NONE", "NULL", ""]
        ):
            parsed["final_opinion"] = parsed.get(
                "executive_summary",
                "Parecer final não informado pela auditoria NVIDIA Nemotron.",
            )

        if not parsed.get(
            "governance_recommendation"
        ):
            parsed[
                "governance_recommendation"
            ] = (
                "Revalidar a coerência dos motores "
                "e arquivar as evidências da auditoria."
            )

        timestamp = utc_now()

        summary = pd.DataFrame([{
            "timestamp_utc": timestamp,
            "openai_audit_status": "EXECUTADO",
            "audit_verdict":
                parsed.get(
                    "audit_verdict",
                    "N/D",
                ),
            "audit_score":
                parsed.get(
                    "audit_score",
                    0,
                ),
            "audit_confidence":
                parsed.get(
                    "audit_confidence",
                    0,
                ),
            "severity":
                parsed.get(
                    "severity",
                    "N/D",
                ),
            "root_cause":
                parsed.get(
                    "root_cause",
                    "N/D",
                ),
            "material_inconsistency":
                parsed.get(
                    "material_inconsistency",
                    "N/D",
                ),
            "false_positive_risk":
                parsed.get(
                    "false_positive_risk",
                    "N/D",
                ),
            "false_negative_risk":
                parsed.get(
                    "false_negative_risk",
                    "N/D",
                ),
            "executive_summary":
                parsed.get(
                    "executive_summary",
                    "N/D",
                ),
            "governance_recommendation":
                parsed.get(
                    "governance_recommendation",
                    "N/D",
                ),
            "final_opinion":
                parsed.get(
                    "final_opinion",
                    parsed.get(
                        "executive_summary",
                        (
                            "Parecer final não informado "
                            "pela auditoria NVIDIA Nemotron."
                        ),
                    ),
                ),
        }])

        details = pd.DataFrame([{
            "timestamp_utc": timestamp,

            "engine_consistency":
                json.dumps(
                    parsed.get(
                        "engine_consistency",
                        {},
                    ),
                    ensure_ascii=False,
                ),

            "main_evidences":
                json.dumps(
                    parsed.get(
                        "main_evidences",
                        [],
                    ),
                    ensure_ascii=False,
                ),

            "concerns":
                json.dumps(
                    parsed.get(
                        "concerns",
                        [],
                    ),
                    ensure_ascii=False,
                ),
        }])

        report = pd.DataFrame([{
            "timestamp_utc": timestamp,
            "openai_audit_status": "EXECUTADO",
            "openai_audit_text": raw_text,
        }])

        summary.to_csv(
            "outputs/openai_audit_summary.csv",
            index=False,
        )

        details.to_csv(
            "outputs/openai_audit_details.csv",
            index=False,
        )

        report.to_csv(
            "outputs/openai_audit_report.csv",
            index=False,
        )

        print(
            "===================================================="
        )
        print(
            "NVIDIA NEMOTRON 3 ULTRA — STRUCTURED REVIEW"
        )
        print(
            "===================================================="
        )

        print(
            "Status:              EXECUTADO"
        )

        print(
            f"Audit Verdict:       "
            f"{summary.iloc[-1]['audit_verdict']}"
        )

        print(
            f"Audit Score:         "
            f"{summary.iloc[-1]['audit_score']}"
        )

        print(
            f"Confidence:          "
            f"{summary.iloc[-1]['audit_confidence']}"
        )

        print(
            f"Severity:            "
            f"{summary.iloc[-1]['severity']}"
        )

        print(
            f"Root Cause:          "
            f"{summary.iloc[-1]['root_cause']}"
        )

        print(
            "----------------------------------------------------"
        )

        print(
            summary.iloc[-1][
                "executive_summary"
            ]
        )

        print(
            "----------------------------------------------------"
        )

        print(
            summary.iloc[-1][
                "final_opinion"
            ]
        )

        print(
            "===================================================="
        )

        return {
            "openai_audit_summary":
                summary,

            "openai_audit_details":
                details,

            "openai_audit_report":
                report,
        }

    except Exception as e:
        text = (
            "Falha ao executar NVIDIA Nemotron Auditor: "
            f"{e}"
        )

        print(text)

        return fallback_result(
            "ERRO",
            text,
        )