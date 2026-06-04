import pandas as pd

from src.portfolio_engine import build_target_allocation


def make_latest(
    macro_conviction,
    confidence_score,
    macro_momentum,
    macro_score,
    liquidez,
    crescimento,
    stress,
    inflacao,
):
    return pd.Series({
        "macro_conviction": macro_conviction,
        "confidence_score": confidence_score,
        "macro_momentum": macro_momentum,
        "macro_score": macro_score,
        "liquidez": liquidez,
        "crescimento": crescimento,
        "stress": stress,
        "inflacao": inflacao,
    })


def test_euforia_extrema():
    latest = make_latest(
        macro_conviction=90,
        confidence_score=85,
        macro_momentum=20,
        macro_score=90,
        liquidez=85,
        crescimento=85,
        stress=85,
        inflacao=50,
    )

    allocation = build_target_allocation(latest)

    risk_weight = (
        allocation["BTC-USD"]
        + allocation["VOO"]
        + allocation["BOTZ"]
        + allocation["INDA"]
    )

    defensive_weight = (
        allocation["USDT-USD"]
        + allocation["GLD"]
        + allocation["TLT"]
    )

    print("\n=== EUFORIA EXTREMA ===")
    print(allocation)
    print("Risk weight:", round(risk_weight, 4))
    print("Defensive weight:", round(defensive_weight, 4))

    assert risk_weight > defensive_weight
    assert allocation["BTC-USD"] >= 0.25
    assert allocation["USDT-USD"] <= 0.10


def test_recessao_extrema():
    latest = make_latest(
        macro_conviction=20,
        confidence_score=45,
        macro_momentum=-20,
        macro_score=25,
        liquidez=20,
        crescimento=20,
        stress=25,
        inflacao=70,
    )

    allocation = build_target_allocation(latest)

    risk_weight = (
        allocation["BTC-USD"]
        + allocation["VOO"]
        + allocation["BOTZ"]
        + allocation["INDA"]
    )

    defensive_weight = (
        allocation["USDT-USD"]
        + allocation["GLD"]
        + allocation["TLT"]
    )

    print("\n=== RECESSAO EXTREMA ===")
    print(allocation)
    print("Risk weight:", round(risk_weight, 4))
    print("Defensive weight:", round(defensive_weight, 4))

    assert defensive_weight > risk_weight
    assert allocation["TLT"] >= 0.25
    assert allocation["USDT-USD"] >= 0.20
    assert allocation["BTC-USD"] <= 0.15


if __name__ == "__main__":
    test_euforia_extrema()
    test_recessao_extrema()
    print("\nTESTES EXTREMOS CONCLUÍDOS COM SUCESSO")
