from pathlib import Path
from datetime import datetime, timezone

import pandas as pd


OUTPUT_DIR = Path("outputs")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def classify_alignment(score):
    if score >= 85:
        return "ALINHADO_AO_MODELO"

    if score >= 70:
        return "MODERADAMENTE_ALINHADO"

    if score >= 50:
        return "DESALINHADO_COM_RESSALVAS"

    return "MUITO_DISTANTE_DO_ALVO"


def classify_action(delta_weight, min_delta=0.02):
    if delta_weight > min_delta:
        return "AUMENTAR"
    if delta_weight < -min_delta:
        return "REDUZIR"
    return "MANTER"


def classify_priority(abs_delta_weight):
    if abs_delta_weight >= 0.15:
        return "CRITICA"

    if abs_delta_weight >= 0.08:
        return "ALTA"

    if abs_delta_weight >= 0.04:
        return "MEDIA"

    if abs_delta_weight >= 0.02:
        return "BAIXA"

    return "RESIDUAL"


def reason_for_asset(asset, delta_weight, action):
    if action == "MANTER":
        return "Peso atual próximo ao alvo operacional."

    if asset == "USDT-USD":
        if action == "REDUZIR":
            return (
                "Excesso de caixa/stablecoin em relação ao alvo do regime atual; "
                "avaliar redução sem comprometer o bucket de sobrevivência."
            )
        return (
            "Necessidade de recompor liquidez operacional e proteção de runway."
        )

    if asset == "BTC-USD":
        if action == "REDUZIR":
            return (
                "Reduzir concentração de risco e volatilidade dominante no orçamento de risco."
            )
        return (
            "Aumentar exposição a risco assimétrico conforme alvo macro, respeitando Risk Budget."
        )

    if asset == "VOO":
        if action == "REDUZIR":
            return "Reduzir exposição a bolsa americana acima do alvo operacional."
        return "Reforçar núcleo de equity global/americana conforme regime macro."

    if asset == "TLT":
        if action == "REDUZIR":
            return "Reduzir duration acima do alvo, preservando piso defensivo."
        return "Reforçar proteção defensiva e convexidade de carteira."

    if asset == "GLD":
        if action == "REDUZIR":
            return "Reduzir ouro acima do alvo, mantendo função de redundância sistêmica."
        return "Reforçar redundância sistêmica e diversificação anti-fragilidade."

    if asset == "BOTZ":
        if action == "REDUZIR":
            return "Reduzir exposição temática acima do alvo operacional."
        return "Reforçar exposição temática de crescimento conforme regime macro."

    if asset == "INDA":
        if action == "REDUZIR":
            return "Reduzir exposição a emergentes acima do alvo operacional."
        return "Reforçar diversificação internacional/emergente conforme regime macro."

    return "Ajuste recomendado para aproximar carteira do alvo operacional."


def build_allocation_advisor(rebalance):
    OUTPUT_DIR.mkdir(exist_ok=True)

    df = rebalance.copy().reset_index()

    if "index" in df.columns:
        df = df.rename(columns={"index": "ativo"})

    if "ativo" not in df.columns:
        df = df.rename(columns={df.columns[0]: "ativo"})

    required = [
        "ativo",
        "valor_atual",
        "peso_atual",
        "peso_alvo",
        "valor_alvo",
        "desvio_peso",
        "ajuste_usd",
        "acao",
        "motivo_execucao",
    ]

    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(f"rebalance sem colunas obrigatórias: {missing}")

    df["ativo"] = df["ativo"].astype(str).str.strip()
    df["valor_atual"] = df["valor_atual"].astype(float)
    df["peso_atual"] = df["peso_atual"].astype(float)
    df["peso_alvo"] = df["peso_alvo"].astype(float)
    df["valor_alvo"] = df["valor_alvo"].astype(float)
    df["desvio_peso"] = df["desvio_peso"].astype(float)
    df["ajuste_usd"] = df["ajuste_usd"].astype(float)

    df["desvio_abs"] = df["desvio_peso"].abs()

    df["acao_modelo"] = df["desvio_peso"].apply(classify_action)
    df["prioridade_modelo"] = df["desvio_abs"].apply(classify_priority)

    df["motivo_modelo"] = df.apply(
        lambda row: reason_for_asset(
            row["ativo"],
            row["desvio_peso"],
            row["acao_modelo"],
        ),
        axis=1,
    )

    total_drift = float(df["desvio_abs"].sum() / 2)
    alignment_score = round(max(0, 100 * (1 - total_drift)), 2)
    alignment_level = classify_alignment(alignment_score)

    total_value = float(df["valor_atual"].sum())
    total_adjustment_abs = float(df["ajuste_usd"].abs().sum())
    turnover_recommended = (
        total_adjustment_abs / total_value
        if total_value > 0
        else 0
    )

    df["peso_atual_pct"] = (df["peso_atual"] * 100).round(2)
    df["peso_alvo_pct"] = (df["peso_alvo"] * 100).round(2)
    df["desvio_pct"] = (df["desvio_peso"] * 100).round(2)
    df["desvio_abs_pct"] = (df["desvio_abs"] * 100).round(2)

    df["timestamp_utc"] = utc_now()

    advisor = df[[
        "timestamp_utc",
        "ativo",
        "valor_atual",
        "valor_alvo",
        "peso_atual_pct",
        "peso_alvo_pct",
        "desvio_pct",
        "desvio_abs_pct",
        "acao_modelo",
        "prioridade_modelo",
        "ajuste_usd",
        "acao",
        "motivo_execucao",
        "motivo_modelo",
    ]].copy()

    advisor = advisor.sort_values(
        ["desvio_abs_pct", "ativo"],
        ascending=[False, True],
    )

    top_gap_asset = (
        str(advisor.iloc[0]["ativo"])
        if not advisor.empty
        else "N/D"
    )

    top_gap_pct = (
        float(advisor.iloc[0]["desvio_abs_pct"])
        if not advisor.empty
        else 0.0
    )

    summary = pd.DataFrame([{
        "timestamp_utc": utc_now(),
        "allocation_alignment_score": alignment_score,
        "allocation_alignment_level": alignment_level,
        "total_model_drift_pct": round(total_drift * 100, 2),
        "turnover_recommended_pct": round(turnover_recommended * 100, 2),
        "top_gap_asset": top_gap_asset,
        "top_gap_abs_pct": top_gap_pct,
        "critical_gaps_count": int(
            (advisor["prioridade_modelo"] == "CRITICA").sum()
        ),
        "high_gaps_count": int(
            (advisor["prioridade_modelo"] == "ALTA").sum()
        ),
        "medium_gaps_count": int(
            (advisor["prioridade_modelo"] == "MEDIA").sum()
        ),
    }])

    advisor.to_csv(
        OUTPUT_DIR / "allocation_advisor.csv",
        index=False,
    )

    summary.to_csv(
        OUTPUT_DIR / "allocation_advisor_summary.csv",
        index=False,
    )

    print("====================================================")
    print("ALLOCATION ADVISOR — TARGET VS CURRENT")
    print("====================================================")
    print(f"Alignment Score:        {alignment_score}")
    print(f"Alignment Level:        {alignment_level}")
    print(f"Total Model Drift:      {total_drift:.2%}")
    print(f"Turnover Recommended:   {turnover_recommended:.2%}")
    print(f"Top Gap Asset:          {top_gap_asset}")
    print(f"Top Gap Abs:            {top_gap_pct:.2f}%")
    print("----------------------------------------------------")
    print(
        advisor[[
            "ativo",
            "peso_atual_pct",
            "peso_alvo_pct",
            "desvio_pct",
            "acao_modelo",
            "prioridade_modelo",
        ]].to_string(index=False)
    )
    print("====================================================")

    return {
        "allocation_advisor": advisor,
        "allocation_advisor_summary": summary,
    }
