# ============================================================
# COPIAULTIMOROB
# agent_export.py
# ============================================================
#
# Exportador oficial para o INVESTMENT CIO AGENT.
#
# Este módulo:
# - NÃO recalcula indicadores;
# - NÃO altera decisões;
# - NÃO altera alocação;
# - NÃO substitui nenhum engine;
# - apenas serializa os resultados já produzidos pelo robô.
#
# Output:
# outputs/agent_output_raw.json
#
# ============================================================

import json
import math
from datetime import datetime, timezone
from pathlib import Path

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None


OUTPUT_DIR = Path("outputs")

OUTPUT_FILE = (
    OUTPUT_DIR
    / "agent_output_raw.json"
)

SOURCE_SYSTEM = "COPIAULTIMOROB"

EXPORT_VERSION = "1.0"


# ============================================================
# CONVERSÃO SEGURA PARA JSON
# ============================================================

def _json_safe(value):
    """
    Converte recursivamente objetos produzidos pelos engines
    para tipos compatíveis com JSON.
    """

    if value is None:
        return None

    if isinstance(
        value,
        (
            str,
            bool,
            int,
        ),
    ):
        return value

    if isinstance(value, float):

        if math.isnan(value):
            return None

        if math.isinf(value):
            return None

        return value

    if np is not None:

        if isinstance(value, np.generic):
            return _json_safe(
                value.item()
            )

        if isinstance(value, np.ndarray):
            return [
                _json_safe(item)
                for item in value.tolist()
            ]

    if pd is not None:

        if isinstance(
            value,
            pd.Timestamp,
        ):
            return value.isoformat()

        if isinstance(
            value,
            pd.Series,
        ):
            return {
                str(key): _json_safe(item)
                for key, item
                in value.to_dict().items()
            }

        if isinstance(
            value,
            pd.DataFrame,
        ):
            return [
                {
                    str(key): _json_safe(item)
                    for key, item
                    in row.items()
                }
                for row
                in value.to_dict(
                    orient="records"
                )
            ]

        try:

            if pd.isna(value):
                return None

        except Exception:
            pass

    if isinstance(value, dict):

        return {
            str(key): _json_safe(item)
            for key, item
            in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):

        return [
            _json_safe(item)
            for item in value
        ]

    if hasattr(
        value,
        "isoformat",
    ):

        try:
            return value.isoformat()
        except Exception:
            pass

    if hasattr(
        value,
        "item",
    ):

        try:
            return _json_safe(
                value.item()
            )
        except Exception:
            pass

    return str(value)


# ============================================================
# EXTRAÇÃO SEGURA DE LINHA
# ============================================================

def _last_row(context, key):
    """
    Extrai a última linha de um DataFrame armazenado
    dentro de um contexto.
    """

    try:

        dataframe = context.get(key)

        if (
            dataframe is not None
            and hasattr(
                dataframe,
                "empty",
            )
            and not dataframe.empty
        ):

            return _json_safe(
                dataframe.iloc[-1]
            )

    except Exception:
        pass

    return {}


# ============================================================
# EXPORTADOR PRINCIPAL
# ============================================================

def export_agent_output(
    data_context,
    macro_context,
    portfolio_context,
    allocation_advisor_context,
    risk_context,
    stress_context,
    risk_budget_context,
    liquidity_context,
    counterparty_context,
    governance_context,
    ai_audit_context,
    openai_audit_context,
):
    """
    Cria o output bruto oficial do COPIAULTIMOROB
    para consumo pelo INVESTMENT CIO AGENT.
    """

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ========================================================
    # MACRO
    # ========================================================

    latest = _json_safe(
        macro_context.get(
            "latest",
            {},
        )
    )

    deterioration = _last_row(
        macro_context,
        "deterioration_audit",
    )

    liquidity_forecast = _last_row(
        macro_context,
        "liquidity_forecast",
    )

    macro_engine_audit = _last_row(
        macro_context,
        "macro_engine_audit",
    )

    # ========================================================
    # PORTFÓLIO
    # ========================================================

    rebalance = _json_safe(
        portfolio_context.get(
            "rebalance",
            {},
        )
    )

    orders = _json_safe(
        portfolio_context.get(
            "orders",
            {},
        )
    )

    portfolio = {

        "total_value": _json_safe(
            portfolio_context.get(
                "total_value"
            )
        ),

        "gross_turnover_final": _json_safe(
            portfolio_context.get(
                "gross_turnover_final"
            )
        ),

        "turnover_status": _json_safe(
            portfolio_context.get(
                "turnover_status"
            )
        ),

        "kill_switch": _json_safe(
            portfolio_context.get(
                "kill_switch"
            )
        ),

        "rebalance": rebalance,

        "orders": orders,
    }

    # ========================================================
    # ALLOCATION ADVISOR
    # ========================================================

    allocation_summary = _last_row(
        allocation_advisor_context,
        "allocation_advisor_summary",
    )

    allocation_details = _json_safe(
        allocation_advisor_context.get(
            "allocation_advisor",
            {},
        )
    )

    # ========================================================
    # SURVIVAL / OPERATIONAL RISK
    # ========================================================

    survival = _last_row(
        risk_context,
        "survival_audit",
    )

    # ========================================================
    # STRESS
    # ========================================================

    stress = _last_row(
        stress_context,
        "stress_summary",
    )

    # ========================================================
    # RISK BUDGET
    # ========================================================

    risk_budget = _last_row(
        risk_budget_context,
        "risk_budget_summary",
    )

    # ========================================================
    # LIQUIDITY
    # ========================================================

    liquidity = _last_row(
        liquidity_context,
        "liquidity_summary",
    )

    # ========================================================
    # COUNTERPARTY
    # ========================================================

    counterparty = _last_row(
        counterparty_context,
        "counterparty_summary",
    )

    # ========================================================
    # GOVERNANCE
    # ========================================================

    governance = _last_row(
        governance_context,
        "risk_committee_integrated",
    )

    # ========================================================
    # AI AUDIT
    # ========================================================

    ai_audit = _last_row(
        ai_audit_context,
        "ai_audit_summary",
    )

    # ========================================================
    # NVIDIA / SECOND AUDITOR
    # ========================================================

    external_ai_audit = _last_row(
        openai_audit_context,
        "openai_audit_summary",
    )

    # ========================================================
    # DATA QUALITY
    # ========================================================

    market_audit = _json_safe(
        data_context.get(
            "market_audit",
            {},
        )
    )

    # ========================================================
    # PAYLOAD FINAL
    # ========================================================

    payload = {

        "source_system": (
            SOURCE_SYSTEM
        ),

        "export_version": (
            EXPORT_VERSION
        ),

        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),

        # ----------------------------------------------------
        # MACRO
        # ----------------------------------------------------

        "macro": {

            "latest": latest,

            "macro_engine_audit": (
                macro_engine_audit
            ),

            "deterioration_audit": (
                deterioration
            ),

            "liquidity_forecast": (
                liquidity_forecast
            ),
        },

        # ----------------------------------------------------
        # PORTFÓLIO
        # ----------------------------------------------------

        "portfolio": portfolio,

        # ----------------------------------------------------
        # ALLOCATION ADVISOR
        # ----------------------------------------------------

        "allocation": {

            "summary": (
                allocation_summary
            ),

            "details": (
                allocation_details
            ),
        },

        # ----------------------------------------------------
        # RISCOS
        # ----------------------------------------------------

        "risk": {

            "survival": survival,

            "stress": stress,

            "risk_budget": (
                risk_budget
            ),

            "liquidity": liquidity,

            "counterparty": (
                counterparty
            ),
        },

        # ----------------------------------------------------
        # GOVERNANÇA
        # ----------------------------------------------------

        "governance": governance,

        # ----------------------------------------------------
        # AUDITORIAS DE IA
        # ----------------------------------------------------

        "ai_audit": ai_audit,

        "external_ai_audit": (
            external_ai_audit
        ),

        # ----------------------------------------------------
        # QUALIDADE DOS DADOS
        # ----------------------------------------------------

        "data_quality": {

            "market_audit": (
                market_audit
            ),
        },
    }

    # ========================================================
    # NORMALIZAÇÃO FINAL
    # ========================================================

    payload = _json_safe(
        payload
    )

    # ========================================================
    # GRAVAÇÃO
    # ========================================================

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            payload,
            file,
            ensure_ascii=False,
            indent=2,
        )

    return str(
        OUTPUT_FILE
    )
