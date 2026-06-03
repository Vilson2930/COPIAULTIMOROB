# main.py

from src.data_engine import run_data_engine
from src.macro_engine import run_macro_engine
from src.portfolio_engine import run_portfolio_engine
from src.operational_risk import run_operational_risk
from src.governance_engine import run_governance_engine


def print_header(title):
    print("====================================================")
    print(title)
    print("====================================================")


def main():
    print_header("ULTIMOROBO — EXECUÇÃO INICIADA")

    data_context = run_data_engine()

    macro_context = run_macro_engine(
        fred_data=data_context["fred_data"],
        market_data=data_context["market_data"],
    )

    portfolio_context = run_portfolio_engine(
        latest=macro_context["latest"],
        latest_market=data_context["latest_market"],
    )

    risk_context = run_operational_risk(
        rebalance=portfolio_context["rebalance"],
        access_map_path="config/access_map.csv",
        monthly_expense_usd=2000,
    )

    governance_context = run_governance_engine(
        latest=macro_context["latest"],
        macro_engine_audit=macro_context["macro_engine_audit"],
        market_audit=data_context["market_audit"],
        rebalance=portfolio_context["rebalance"],
        orders=portfolio_context["orders"],
        total_value=portfolio_context["total_value"],
        gross_turnover_final=portfolio_context["gross_turnover_final"],
        turnover_status=portfolio_context["turnover_status"],
        kill_switch=portfolio_context["kill_switch"],
        survival_audit=risk_context["survival_audit"],
        deterioration_audit=macro_context["deterioration_audit"],
        liquidity_forecast=macro_context["liquidity_forecast"],
    )

    latest = macro_context["latest"]
    survival = risk_context["survival_audit"].iloc[-1]
    risk = governance_context["risk_committee_integrated"].iloc[-1]

    print_header("ULTIMOROBO — RESUMO EXECUTIVO FINAL")

    print(f"Regime Macro:        {latest['regime']}")
    print(f"Sinal Operacional:   {latest['sinal_operacional']}")
    print(f"Macro Conviction:    {float(latest['macro_conviction']):.2f}")
    print(f"Confidence Score:    {float(latest['confidence_score']):.2f}")
    print("----------------------------------------------------")
    print(f"Valor Total:         US${float(portfolio_context['total_value']):,.2f}")
    print(f"Giro Final:          {float(portfolio_context['gross_turnover_final']):.2%}")
    print(f"Status de Giro:      {portfolio_context['turnover_status']}")
    print("----------------------------------------------------")
    print(f"Survival Status:     {survival['survival_status']}")
    print(f"Risco de Ruína:      {survival['ruin_risk']}")
    print(f"Survival KillSwitch: {survival['survival_kill_switch']}")
    print("----------------------------------------------------")
    print(f"Comitê:              {risk['integrated_risk_level']}")
    print(f"Ação:                {risk['committee_action']}")
    print(f"VEREDITO FINAL:      {risk['final_verdict']}")
    print("====================================================")
    print("Relatórios gerados:")
    print("- executive_dashboard.csv")
    print("- risk_committee_integrated.csv")
    print("- audit_log_robo_macro.csv")
    print("- orders_log_robo_macro.csv")
    print("- outputs/survival_audit.csv")
    print("====================================================")

    return {
        "data": data_context,
        "macro": macro_context,
        "portfolio": portfolio_context,
        "risk": risk_context,
        "governance": governance_context,
    }


if __name__ == "__main__":
    main()
