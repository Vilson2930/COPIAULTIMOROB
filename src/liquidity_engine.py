
import os
from datetime import datetime, timezone

import pandas as pd


OUTPUT_DIR = "outputs"
ACCESS_MAP_PATH = "config/access_map.csv"


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def ensure_outputs_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def normalize_bool(series):
    return (
        series.astype(str)
        .str.upper()
        .str.strip()
        .isin(["TRUE", "1", "SIM", "YES"])
    )


def build_positions_df(rebalance):
    df = rebalance.copy().reset_index()

    if "index" in df.columns:
        df = df.rename(columns={"index": "ativo"})

    if "ativo" not in df.columns:
        df = df.rename(columns={df.columns[0]: "ativo"})

    required = ["ativo", "valor_atual", "peso_atual"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(f"rebalance com colunas ausentes: {missing}")

    df["ativo"] = df["ativo"].astype(str).str.strip()
    df["valor_atual"] = df["valor_atual"].astype(float)
    df["peso_atual"] = df["peso_atual"].astype(float)

    return df


def load_access_map(path=ACCESS_MAP_PATH):
    if not os.path.exists(path):
        raise FileNotFoundError(f"Arquivo obrigatório ausente: {path}")

    access = pd.read_csv(path)

    required = [
        "ativo",
        "trilho",
        "entidade",
        "jurisdicao",
        "status",
        "criticidade",
        "bucket_sobrevivencia",
        "jurisdicao_valida",
    ]

    missing = [c for c in required if c not in access.columns]

    if missing:
        raise ValueError(f"access_map com colunas ausentes: {missing}")

    access["ativo"] = access["ativo"].astype(str).str.strip()
    access["trilho"] = access["trilho"].astype(str).str.strip()
    access["entidade"] = access["entidade"].astype(str).str.strip()
    access["jurisdicao"] = access["jurisdicao"].astype(str).str.strip()
    access["status"] = access["status"].astype(str).str.upper().str.strip()
    access["criticidade"] = access["criticidade"].astype(str).str.upper().str.strip()
    access["bucket_sobrevivencia"] = normalize_bool(access["bucket_sobrevivencia"])
    access["jurisdicao_valida"] = normalize_bool(access["jurisdicao_valida"])

    return access


def financial_haircuts():
    return {
        "USDT-USD": 0.02,
        "TLT": 0.03,
        "GLD": 0.05,
        "VOO": 0.03,
        "INDA": 0.07,
        "BOTZ": 0.10,
        "BTC-USD": 0.12,
    }


def entity_haircuts():
    return {
        "SELF_CUSTODY": 0.05,
        "BLACKROCK": 0.01,
        "STATE_STREET": 0.01,
        "GLOBAL_X": 0.03,
        "TETHER": 0.12,
    }


def rail_haircut(trilho):
    t = str(trilho).upper()

    if "AUTOCUST" in t or "SELF" in t or "COLD" in t:
        return 0.05

    if "BANK" in t or "BANCO" in t:
        return 0.03

    if "BROKER" in t or "CORRETORA" in t:
        return 0.04

    if "EXCHANGE" in t:
        return 0.10

    if "ETF" in t:
        return 0.02

    return 0.05


def status_penalty(status):
    s = str(status).upper()

    if s == "ATIVO":
        return 0.00

    if s in ["LIMITADO", "RESTRITO", "ATENCAO", "ATENÇÃO"]:
        return 0.25

    if s in ["BLOQUEADO", "SUSPENSO", "INATIVO"]:
        return 1.00

    return 0.15


def criticidade_penalty(criticidade):
    c = str(criticidade).upper()

    if c in ["BAIXA", "LOW"]:
        return 0.00

    if c in ["MEDIA", "MÉDIA", "MEDIUM"]:
        return 0.03

    if c in ["ALTA", "HIGH"]:
        return 0.08

    if c in ["CRITICA", "CRÍTICA", "CRITICAL"]:
        return 0.15

    return 0.03


def jurisdiction_penalty(jurisdicao_valida):
    return 0.00 if bool(jurisdicao_valida) else 0.15


def classify_liquidity_score(score):
    if score >= 85:
        return "ROBUSTO"

    if score >= 70:
        return "ACEITAVEL"

    if score >= 55:
        return "FRAGIL"

    return "CRITICO"


def classify_access_level(access_score):
    if access_score >= 90:
        return "ACESSO_PLENO"

    if access_score >= 75:
        return "ACESSO_FUNCIONAL"

    if access_score >= 55:
        return "ACESSO_FRAGIL"

    return "ACESSO_CRITICO"


def run_liquidity_engine(rebalance, access_map_path=ACCESS_MAP_PATH):
    timestamp_utc = utc_now()

    positions = build_positions_df(rebalance)
    access = load_access_map(access_map_path)

    df = positions.merge(
        access,
        on="ativo",
        how="left",
    )

    df["status"] = df["status"].fillna("DESCONHECIDO")
    df["trilho"] = df["trilho"].fillna("DESCONHECIDO")
    df["entidade"] = df["entidade"].fillna("DESCONHECIDO")
    df["jurisdicao"] = df["jurisdicao"].fillna("DESCONHECIDO")
    df["criticidade"] = df["criticidade"].fillna("MEDIA")
    df["jurisdicao_valida"] = df["jurisdicao_valida"].fillna(False)

    fh = financial_haircuts()
    eh = entity_haircuts()

    df["financial_haircut_pct"] = df["ativo"].map(fh).fillna(0.10)

    df["entity_haircut_pct"] = (
        df["entidade"]
        .astype(str)
        .str.upper()
        .map(eh)
        .fillna(0.05)
    )

    df["rail_haircut_pct"] = df["trilho"].apply(rail_haircut)
    df["jurisdiction_haircut_pct"] = df["jurisdicao_valida"].apply(
        jurisdiction_penalty
    )
    df["status_penalty_pct"] = df["status"].apply(status_penalty)
    df["criticidade_penalty_pct"] = df["criticidade"].apply(criticidade_penalty)

    df["total_haircut_pct"] = (
        df["financial_haircut_pct"]
        + df["entity_haircut_pct"]
        + df["rail_haircut_pct"]
        + df["jurisdiction_haircut_pct"]
        + df["status_penalty_pct"]
        + df["criticidade_penalty_pct"]
    ).clip(0, 1)

    df["valor_liquido_operacional"] = (
        df["valor_atual"] * (1 - df["total_haircut_pct"])
    )

    df["access_score"] = (100 * (1 - df["total_haircut_pct"])).round(2)
    df["access_level"] = df["access_score"].apply(classify_access_level)

    gross_value = float(df["valor_atual"].sum())
    liquid_value = float(df["valor_liquido_operacional"].sum())

    aggregate_haircut_pct = (
        (gross_value - liquid_value) / gross_value
        if gross_value > 0
        else 1
    )

    liquidity_score = round(100 * (1 - aggregate_haircut_pct), 2)
    liquidity_level = classify_liquidity_score(liquidity_score)

    blocked_value = float(
        df[df["status"].isin(["BLOQUEADO", "SUSPENSO", "INATIVO"])]["valor_atual"].sum()
    )

    invalid_jurisdiction_value = float(
        df[df["jurisdicao_valida"] == False]["valor_atual"].sum()
    )

    max_rail_concentration = float(
        (df.groupby("trilho")["valor_atual"].sum() / gross_value).max()
        if gross_value > 0
        else 1
    )

    max_entity_concentration = float(
        (df.groupby("entidade")["valor_atual"].sum() / gross_value).max()
        if gross_value > 0
        else 1
    )

    critical_flags = []

    if liquidity_score < 55:
        critical_flags.append("LIQUIDEZ_OPERACIONAL_CRITICA")

    if blocked_value > 0:
        critical_flags.append("ATIVO_COM_ACESSO_BLOQUEADO")

    if gross_value > 0 and invalid_jurisdiction_value / gross_value > 0.50:
        critical_flags.append("MAIS_DE_50_EM_JURISDICAO_NAO_VALIDA")

    if max_rail_concentration > 0.65:
        critical_flags.append("CONCENTRACAO_DE_TRILHO_ACIMA_65")

    if max_entity_concentration > 0.65:
        critical_flags.append("CONCENTRACAO_DE_ENTIDADE_ACIMA_65")

    liquidity_audit = df[[
        "ativo",
        "valor_atual",
        "peso_atual",
        "trilho",
        "entidade",
        "jurisdicao",
        "status",
        "criticidade",
        "jurisdicao_valida",
        "financial_haircut_pct",
        "entity_haircut_pct",
        "rail_haircut_pct",
        "jurisdiction_haircut_pct",
        "status_penalty_pct",
        "criticidade_penalty_pct",
        "total_haircut_pct",
        "valor_liquido_operacional",
        "access_score",
        "access_level",
    ]].copy()

    liquidity_audit["timestamp_utc"] = timestamp_utc

    liquidity_summary = pd.DataFrame([{
        "timestamp_utc": timestamp_utc,

        # colunas antigas obrigatórias
        "gross_value": round(gross_value, 2),
        "liquid_value": round(liquid_value, 2),
        "aggregate_haircut_pct": round(aggregate_haircut_pct * 100, 2),

        # colunas novas operacionais
        "operational_liquid_value": round(liquid_value, 2),
        "aggregate_operational_haircut_pct": round(aggregate_haircut_pct * 100, 2),

        "liquidity_score": liquidity_score,
        "liquidity_level": liquidity_level,
        "blocked_value": round(blocked_value, 2),
        "invalid_jurisdiction_value": round(invalid_jurisdiction_value, 2),
        "max_rail_concentration_pct": round(max_rail_concentration * 100, 2),
        "max_entity_concentration_pct": round(max_entity_concentration * 100, 2),
        "critical_flags": " | ".join(critical_flags) if critical_flags else "",
    }])

    ensure_outputs_dir()

    liquidity_audit.to_csv(
        os.path.join(OUTPUT_DIR, "liquidity_audit.csv"),
        index=False,
    )

    liquidity_summary.to_csv(
        os.path.join(OUTPUT_DIR, "liquidity_summary.csv"),
        index=False,
    )

    print("====================================================")
    print("OPERATIONAL LIQUIDITY ENGINE")
    print("====================================================")
    print(f"Data UTC:                      {timestamp_utc}")
    print(f"Valor Bruto:                   US${gross_value:,.2f}")
    print(f"Valor Liquido:                 US${liquid_value:,.2f}")
    print(f"Haircut Agregado:              {aggregate_haircut_pct:.2%}")
    print(f"Liquidity Score:               {liquidity_score}")
    print(f"Liquidity Level:               {liquidity_level}")
    print(f"Max Rail Concentration:        {max_rail_concentration:.2%}")
    print(f"Max Entity Concentration:      {max_entity_concentration:.2%}")

    if critical_flags:
        print(f"Critical Flags:                {' | '.join(critical_flags)}")
    else:
        print("Critical Flags:                Nenhuma")

    print("====================================================")

    return {
        "liquidity_audit": liquidity_audit,
        "liquidity_summary": liquidity_summary,
    }
