# src/operational_risk.py

import os
from datetime import datetime, timezone

import pandas as pd


OUTPUT_DIR = "outputs"
ACCESS_MAP_PATH = "config/access_map.csv"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def load_access_map(path=ACCESS_MAP_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Arquivo obrigatório ausente: {path}")

    return pd.read_csv(path)


def normalize_bool_column(series):
    return (
        series.astype(str)
        .str.upper()
        .str.strip()
        .isin(["TRUE", "1", "SIM", "YES"])
    )


def normalize_access_map(access_map):
    access_map = access_map.copy()

    required_columns = [
        "ativo",
        "trilho",
        "entidade",
        "jurisdicao",
        "status",
        "criticidade",
        "bucket_sobrevivencia",
        "jurisdicao_valida",
    ]

    missing = [col for col in required_columns if col not in access_map.columns]

    if missing:
        raise ValueError(f"access_map com colunas ausentes: {missing}")

    access_map["bucket_sobrevivencia"] = normalize_bool_column(
        access_map["bucket_sobrevivencia"]
    )

    access_map["jurisdicao_valida"] = normalize_bool_column(
        access_map["jurisdicao_valida"]
    )

    access_map["status"] = access_map["status"].astype(str).str.upper().str.strip()
    access_map["ativo"] = access_map["ativo"].astype(str).str.strip()
    access_map["trilho"] = access_map["trilho"].astype(str).str.strip()
    access_map["entidade"] = access_map["entidade"].astype(str).str.strip()
    access_map["jurisdicao"] = access_map["jurisdicao"].astype(str).str.strip()

    return access_map


def build_positions_df(rebalance):
    positions_df = rebalance.copy().reset_index()

    if "index" in positions_df.columns:
        positions_df = positions_df.rename(columns={"index": "ativo"})

    if "ativo" not in positions_df.columns:
        positions_df = positions_df.rename(columns={positions_df.columns[0]: "ativo"})

    required_columns = ["ativo", "valor_atual", "peso_atual"]

    missing = [col for col in required_columns if col not in positions_df.columns]

    if missing:
        raise ValueError(f"rebalance com colunas ausentes: {missing}")

    positions_df["ativo"] = positions_df["ativo"].astype(str).str.strip()
    positions_df["valor_atual"] = positions_df["valor_atual"].astype(float)
    positions_df["peso_atual"] = positions_df["peso_atual"].astype(float)

    return positions_df


def calculate_runway_score(runway_months):
    if runway_months >= 36:
        return 100
    if runway_months >= 24:
        return 90
    if runway_months >= 18:
        return 75
    if runway_months >= 12:
        return 60
    return 20


def calculate_concentration_score(max_concentration):
    if max_concentration <= 0.50:
        return 100
    if max_concentration <= 0.65:
        return 80
    if max_concentration <= 0.80:
        return 60
    if max_concentration <= 0.90:
        return 40
    return 20


def calculate_jurisdiction_score(bucket_jurisdicoes_validas):
    """
    Jurisdição agora é penalidade graduada, não Kill Switch absoluto.

    Critério:
    - 3+ jurisdições válidas: excelente redundância operacional
    - 2 jurisdições válidas: adequado
    - 1 jurisdição válida: aceitável com ressalvas
    - 0 jurisdições válidas: frágil
    """

    if bucket_jurisdicoes_validas >= 3:
        return 100
    if bucket_jurisdicoes_validas == 2:
        return 80
    if bucket_jurisdicoes_validas == 1:
        return 40
    return 0


def classify_survival(metrics):
    kill_reasons = []
    required_evidence = []

    if metrics["runway_months"] < 12:
        kill_reasons.append("RUNWAY_INFERIOR_A_12_MESES")
        required_evidence.append(
            "Aumentar bucket de sobrevivência para no mínimo 12 meses."
        )

    if metrics["bucket_trilhos"] < 2:
        kill_reasons.append("MENOS_DE_2_TRILHOS")
        required_evidence.append(
            "Adicionar segundo trilho independente ao bucket de sobrevivência."
        )

    if metrics["bucket_entidades"] < 2:
        kill_reasons.append("MENOS_DE_2_ENTIDADES")
        required_evidence.append(
            "Distribuir bucket entre no mínimo 2 entidades jurídicas."
        )

    # Ajuste de calibração:
    # Antes, menos de 2 jurisdições válidas acionava Kill Switch.
    # Agora, jurisdição única gera ressalva operacional, mas não reprovação automática.
    if metrics["bucket_jurisdicoes_validas"] < 2:
        required_evidence.append(
            "Adicionar segunda jurisdição válida para aumentar redundância operacional."
        )

    if metrics["max_bucket_concentration"] > 0.90:
        kill_reasons.append("CONCENTRACAO_BUCKET_ACIMA_DE_90")
        required_evidence.append(
            "Reduzir concentração dominante do bucket abaixo de 90%."
        )

    survival_kill_switch = len(kill_reasons) > 0

    if survival_kill_switch:
        survival_status = "REPROVADO"
        ruin_risk = "ALTO"

    elif metrics["survival_score"] >= 85:
        survival_status = "APROVADO"
        ruin_risk = "BAIXO"

    elif metrics["survival_score"] >= 70:
        survival_status = "APROVADO_COM_RESSALVAS"
        ruin_risk = "MEDIO"

    else:
        survival_status = "REPROVADO"
        ruin_risk = "ALTO"
        survival_kill_switch = True
        kill_reasons.append("SURVIVAL_SCORE_INSUFICIENTE")
        required_evidence.append(
            "Elevar survival_score para no mínimo 70 antes de nova aprovação."
        )

    if not required_evidence:
        required_evidence.append(
            "Manter teste operacional periódico de acesso aos trilhos."
        )

    return {
        "survival_status": survival_status,
        "ruin_risk": ruin_risk,
        "survival_kill_switch": survival_kill_switch,
        "kill_reasons": kill_reasons,
        "required_evidence": required_evidence,
    }


def run_operational_risk(
    rebalance,
    access_map_path=ACCESS_MAP_PATH,
    monthly_expense_usd=2000,
):
    timestamp_utc = utc_now()

    access_map = load_access_map(access_map_path)
    access_map = normalize_access_map(access_map)

    positions_df = build_positions_df(rebalance)

    total_portfolio_value = positions_df["valor_atual"].sum()

    active_access_map = access_map[
        access_map["status"] == "ATIVO"
    ].copy()

    survival_assets = active_access_map[
        active_access_map["bucket_sobrevivencia"] == True
    ].copy()

    bucket_positions = positions_df[
        positions_df["ativo"].isin(survival_assets["ativo"])
    ].copy()

    bucket_value = bucket_positions["valor_atual"].sum()

    runway_months = (
        bucket_value / monthly_expense_usd
        if monthly_expense_usd > 0
        else 0
    )

    bucket_trilhos = survival_assets["trilho"].nunique()
    bucket_entidades = survival_assets["entidade"].nunique()

    bucket_jurisdicoes_validas = survival_assets[
        survival_assets["jurisdicao_valida"] == True
    ]["jurisdicao"].nunique()

    bucket_detail = bucket_positions.merge(
        survival_assets,
        on="ativo",
        how="left",
    )

    if bucket_value > 0 and not bucket_detail.empty:
        max_trilho_concentration = float(
            (bucket_detail.groupby("trilho")["valor_atual"].sum() / bucket_value).max()
        )

        max_entidade_concentration = float(
            (bucket_detail.groupby("entidade")["valor_atual"].sum() / bucket_value).max()
        )

        max_jurisdiction_concentration = float(
            (bucket_detail.groupby("jurisdicao")["valor_atual"].sum() / bucket_value).max()
        )

        max_bucket_concentration = max(
            max_trilho_concentration,
            max_entidade_concentration,
            max_jurisdiction_concentration,
        )

    else:
        max_trilho_concentration = 1.0
        max_entidade_concentration = 1.0
        max_jurisdiction_concentration = 1.0
        max_bucket_concentration = 1.0

    runway_score = calculate_runway_score(runway_months)
    trilho_score = 100 if bucket_trilhos >= 2 else 0
    entidade_score = 100 if bucket_entidades >= 2 else 0
    jurisdicao_score = calculate_jurisdiction_score(bucket_jurisdicoes_validas)
    concentration_score = calculate_concentration_score(max_bucket_concentration)

    survival_score = (
        runway_score * 0.35
        + trilho_score * 0.20
        + entidade_score * 0.15
        + jurisdicao_score * 0.15
        + concentration_score * 0.15
    )

    metrics = {
        "runway_months": runway_months,
        "bucket_trilhos": bucket_trilhos,
        "bucket_entidades": bucket_entidades,
        "bucket_jurisdicoes_validas": bucket_jurisdicoes_validas,
        "max_bucket_concentration": max_bucket_concentration,
        "survival_score": survival_score,
    }

    classification = classify_survival(metrics)

    survival_status = classification["survival_status"]
    ruin_risk = classification["ruin_risk"]
    survival_kill_switch = classification["survival_kill_switch"]
    kill_reasons = classification["kill_reasons"]
    required_evidence = classification["required_evidence"]

    bucket_ok = not survival_kill_switch

    survival_audit = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,
        "total_portfolio_value_usd": total_portfolio_value,
        "bucket_value_usd": bucket_value,
        "monthly_expense_usd": monthly_expense_usd,
        "runway_months": runway_months,
        "bucket_trilhos": bucket_trilhos,
        "bucket_entidades": bucket_entidades,
        "bucket_jurisdicoes_validas": bucket_jurisdicoes_validas,
        "max_trilho_concentration": max_trilho_concentration,
        "max_entidade_concentration": max_entidade_concentration,
        "max_jurisdiction_concentration": max_jurisdiction_concentration,
        "max_bucket_concentration": max_bucket_concentration,
        "bucket_ok": bucket_ok,
        "runway_score": runway_score,
        "trilho_score": trilho_score,
        "entidade_score": entidade_score,
        "jurisdicao_score": jurisdicao_score,
        "concentration_score": concentration_score,
        "survival_score": survival_score,
        "survival_status": survival_status,
        "ruin_risk": ruin_risk,
        "survival_kill_switch": survival_kill_switch,
        "kill_reasons": " | ".join(kill_reasons),
        "required_evidence": " | ".join(required_evidence),
    }])

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    survival_audit.to_csv(
        os.path.join(OUTPUT_DIR, "survival_audit.csv"),
        index=False,
    )

    print("====================================================")
    print("OPERATIONAL RISK ENGINE — SURVIVAL V2")
    print("====================================================")
    print(f"Data UTC:                   {timestamp_utc}")
    print(f"Valor total carteira:       US${total_portfolio_value:,.2f}")
    print(f"Valor bucket sobrevivência: US${bucket_value:,.2f}")
    print(f"Runway estimado:            {runway_months:.1f} meses")
    print("----------------------------------------------------")
    print(f"Bucket trilhos:             {bucket_trilhos}")
    print(f"Bucket entidades:           {bucket_entidades}")
    print(f"Bucket jurisdições válidas: {bucket_jurisdicoes_validas}")
    print(f"Concentração máxima bucket: {max_bucket_concentration:.2%}")
    print("----------------------------------------------------")
    print(f"Survival Score:             {survival_score:.2f}")
    print(f"Status:                     {survival_status}")
    print(f"Risco de Ruína:             {ruin_risk}")
    print(f"Kill Switch:                {survival_kill_switch}")
    print("====================================================")

    return {
        "access_map": access_map,
        "positions_df": positions_df,
        "survival_assets": survival_assets,
        "bucket_positions": bucket_positions,
        "survival_audit": survival_audit,
        "survival_kill_switch": survival_kill_switch,
        "kill_reasons": kill_reasons,
        "required_evidence": required_evidence,
    }
