from src.data_engine import run_data_engine
from src.macro_engine import run_macro_engine
from src.portfolio_engine import run_portfolio_engine
from src.operational_risk import run_operational_risk
from src.governance_engine import run_governance_engine
from src.stress_engine import run_stress_engine
from src.risk_budget_engine import run_risk_budget_engine
from src.liquidity_engine import run_liquidity_engine
from src.counterparty_engine import run_counterparty_engine
from src.ai_auditor import run_ai_auditor
from src.openai_auditor import run_openai_auditor
from src.allocation_advisor import build_allocation_advisor


def print_header(title):
    print("====================================================")
    print(title)
    print("====================================================")


def safe_last(context, key):
    try:
        df = context.get(key)
        if df is not None and not df.empty:
            return df.iloc[-1]
    except Exception:
        pass
    return {}


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

    allocation_advisor_context = build_allocation_advisor(
        portfolio_context["rebalance"]
    )

    risk_context = run_operational_risk(
        rebalance=portfolio_context["rebalance"],
        access_map_path="config/access_map.csv",
        monthly_expense_usd=2000,
    )

    stress_context = run_stress_engine(
        rebalance=portfolio_context["rebalance"],
        monthly_expense_usd=2000,
    )

    risk_budget_context = run_risk_budget_engine(
        rebalance=portfolio_context["rebalance"],
        market_data=data_context["market_data"],
    )

    liquidity_context = run_liquidity_engine(
        rebalance=portfolio_context["rebalance"],
    )

    counterparty_context = run_counterparty_engine(
        rebalance=portfolio_context["rebalance"],
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
        stress_summary_override=stress_context["stress_summary"],
        risk_budget_summary=risk_budget_context["risk_budget_summary"],
        liquidity_summary=liquidity_context["liquidity_summary"],
        counterparty_summary=counterparty_context["counterparty_summary"],
    )

    ai_audit_context = run_ai_auditor()

    try:
        openai_audit_context = run_openai_auditor()
    except Exception as e:
        print("====================================================")
        print("OPENAI AUDITOR FALHOU — EXECUÇÃO CONTINUARÁ")
        print("====================================================")
        print(e)
        openai_audit_context = {
            "openai_audit_summary": None,
            "openai_audit_details": None,
            "openai_audit_report": None,
        }

    latest = macro_context["latest"]
    survival = risk_context["survival_audit"].iloc[-1]
    stress = stress_context["stress_summary"].iloc[-1]
    risk_budget = risk_budget_context["risk_budget_summary"].iloc[-1]
    liquidity = liquidity_context["liquidity_summary"].iloc[-1]
    counterparty = counterparty_context["counterparty_summary"].iloc[-1]
    risk = governance_context["risk_committee_integrated"].iloc[-1]
    ai_audit = ai_audit_context["ai_audit_summary"].iloc[-1]
    allocation_summary = allocation_advisor_context[
        "allocation_advisor_summary"
    ].iloc[-1]

    openai_audit = safe_last(
        openai_audit_context,
        "openai_audit_summary",
    )

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
    print(f"Allocation Score:    {allocation_summary['allocation_alignment_score']}")
    print(f"Allocation Level:    {allocation_summary['allocation_alignment_level']}")
    print(f"Model Drift:         {float(allocation_summary['total_model_drift_pct']):.2f}%")
    print(f"Top Gap Asset:       {allocation_summary['top_gap_asset']}")
    print(f"Top Gap Abs:         {float(allocation_summary['top_gap_abs_pct']):.2f}%")

    print("----------------------------------------------------")
    print(f"Survival Status:     {survival['survival_status']}")
    print(f"Risco de Ruína:      {survival['ruin_risk']}")
    print(f"Survival KillSwitch: {survival['survival_kill_switch']}")

    print("----------------------------------------------------")
    print(f"Stress Level:        {stress['stress_level']}")
    print(f"Stress Score:        {stress['stress_score']}")
    print(f"Max Drawdown:        {float(stress['max_drawdown_pct']):.2f}%")
    print(f"Forced Selling:      {stress['forced_selling_any']}")

    print("----------------------------------------------------")
    print(f"Risk Budget Level:   {risk_budget['risk_budget_level']}")
    print(f"Risk Budget Score:   {risk_budget['risk_budget_score']}")
    print(f"Top Risk Asset:      {risk_budget['top_risk_asset']}")
    print(f"Max Risk Contrib.:   {float(risk_budget['max_risk_contribution_pct']):.2f}%")

    print("----------------------------------------------------")
    print(f"Liquidity Level:     {liquidity['liquidity_level']}")
    print(f"Liquidity Score:     {float(liquidity['liquidity_score']):.2f}")

    haircut_agregado = liquidity.get(
        "aggregate_haircut_pct",
        liquidity.get("aggregate_operational_haircut_pct", 0),
    )
    print(f"Haircut Agregado:    {float(haircut_agregado):.2f}%")

    print("----------------------------------------------------")
    print(f"Counterparty Level:  {counterparty['counterparty_level']}")
    print(f"Counterparty Score:  {counterparty['counterparty_score']}")
    print(f"Maior Contraparte:   {counterparty['largest_counterparty']}")

    print("----------------------------------------------------")
    print(f"Comitê:              {risk['integrated_risk_level']}")
    print(f"Ação:                {risk['committee_action']}")
    print(f"VEREDITO FINAL:      {risk['final_verdict']}")

    print("----------------------------------------------------")
    print(f"AI Audit Status:     {ai_audit['ai_audit_status']}")
    print(f"AI Audit Score:      {ai_audit['ai_audit_score']}")
    print(f"AI Root Cause:       {ai_audit['root_cause']}")

    print("----------------------------------------------------")
    print(f"OpenAI Audit:        {openai_audit.get('openai_audit_status', 'NAO_EXECUTADO')}")
    print(f"OpenAI Verdict:      {openai_audit.get('audit_verdict', 'N/D')}")
    print(f"OpenAI Score:        {openai_audit.get('audit_score', 'N/D')}")
    print(f"OpenAI Confidence:   {openai_audit.get('audit_confidence', 'N/D')}")
    print(f"OpenAI Severity:     {openai_audit.get('severity', 'N/D')}")
    print(f"OpenAI Root Cause:   {openai_audit.get('root_cause', 'N/D')}")
    print(f"OpenAI Final Opinion:{openai_audit.get('final_opinion', 'N/D')}")

    print("====================================================")
    print("Relatórios gerados:")
    print("- executive_dashboard.csv")
    print("- risk_committee_integrated.csv")
    print("- audit_log_robo_macro.csv")
    print("- orders_log_robo_macro.csv")
    print("- outputs/allocation_advisor.csv")
    print("- outputs/allocation_advisor_summary.csv")
    print("- outputs/survival_audit.csv")
    print("- outputs/stress_results_v2.csv")
    print("- outputs/stress_summary_v2.csv")
    print("- outputs/risk_budget.csv")
    print("- outputs/risk_budget_summary.csv")
    print("- outputs/liquidity_audit.csv")
    print("- outputs/liquidity_summary.csv")
    print("- outputs/counterparty_audit.csv")
    print("- outputs/counterparty_summary.csv")
    print("- outputs/ai_audit_summary.csv")
    print("- outputs/ai_audit_details.csv")
    print("- outputs/openai_audit_summary.csv")
    print("- outputs/openai_audit_details.csv")
    print("- outputs/openai_audit_report.csv")
    print("====================================================")

    return {
        "data": data_context,
        "macro": macro_context,
        "portfolio": portfolio_context,
        "allocation_advisor": allocation_advisor_context,
        "risk": risk_context,
        "stress": stress_context,
        "risk_budget": risk_budget_context,
        "liquidity": liquidity_context,
        "counterparty": counterparty_context,
        "governance": governance_context,
        "ai_audit": ai_audit_context,
        "openai_audit": openai_audit_context,
    }


if __name__ == "__main__":
    main()
