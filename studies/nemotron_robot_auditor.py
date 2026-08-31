import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
BASE_URL = "https://integrate.api.nvidia.com/v1"
SRC_DIR = Path("src")
OUTPUT_DIR = Path("outputs/nemotron_robot_audit")

MAIN_ENGINES = [
    "data_engine.py",
    "macro_engine.py",
    "portfolio_engine.py",
    "allocation_advisor.py",
    "operational_risk.py",
    "stress_engine.py",
    "risk_budget_engine.py",
    "liquidity_engine.py",
    "counterparty_engine.py",
    "governance_engine.py",
]

MAX_TOKENS_INDIVIDUAL = 8000
MAX_TOKENS_CROSS = 10000


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def get_client():
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY não encontrada.")
    return OpenAI(api_key=api_key, base_url=BASE_URL)


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_engine(filename):
    path = SRC_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(f"Motor não encontrado: {path}")
    return path.read_text(encoding="utf-8", errors="replace")


def call_nemotron(prompt, max_tokens):
    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um auditor técnico sênior de sistemas quantitativos financeiros. "
                    "Analise código de forma conservadora. Diferencie erro real, inconsistência "
                    "provável, necessidade de validação e escolha metodológica. Não invente "
                    "evidências e não altere o código."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        max_tokens=max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("Nemotron retornou resposta vazia.")
    return content.strip()


def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("Resposta do Nemotron não contém JSON válido.")
        return json.loads(text[start:end + 1])


INDIVIDUAL_SCHEMA = {
    "arquivo": "",
    "veredito": "APROVADO | APROVADO_COM_RESSALVAS | REQUER_VALIDACAO | INCONSISTENTE",
    "score_estrutural": 0,
    "confidence": 0,
    "erros_confirmados": [],
    "inconsistencias_provaveis": [],
    "requer_validacao": [],
    "escolhas_metodologicas": [],
    "melhorias": [],
    "matematica": {"status": "OK | ATENCAO | ERRO", "observacoes": []},
    "logica": {"status": "OK | ATENCAO | ERRO", "observacoes": []},
    "dados": {"status": "OK | ATENCAO | ERRO", "observacoes": []},
    "integracao": {"status": "OK | ATENCAO | ERRO", "observacoes": []},
    "fail_safe": {"status": "OK | ATENCAO | ERRO", "observacoes": []},
    "pontos_fortes": [],
    "conclusao": "",
}


def build_individual_prompt(filename, source_code):
    schema = json.dumps(INDIVIDUAL_SCHEMA, ensure_ascii=False, indent=2)
    return f"""
AUDITORIA INDIVIDUAL DE MOTOR QUANTITATIVO

ARQUIVO: {filename}

Audite ESTE MOTOR ISOLADAMENTE. Considere que nenhuma auditoria anterior foi realizada.

Analise obrigatoriamente:
- matemática, fórmulas, pesos, percentuais, normalizações, sinais, divisões e unidades;
- lógica, condições, branches, defaults, thresholds e comportamento silencioso;
- dados, NaN, infinitos, nulos, duplicatas, tipos, índices, colunas, datas e fallbacks;
- risco temporal, look-ahead, backfill, forward fill, shifts e janelas móveis;
- fail-safe/fail-open, inclusive dados ausentes e ativos desconhecidos;
- integração esperada: inputs, outputs, colunas, formatos, unidades e contratos implícitos;
- robustez para carteira vazia, pesos inválidos, valores negativos e divisão por zero.

Classifique cada achado como:
ERRO_CONFIRMADO, INCONSISTENCIA_PROVAVEL, REQUER_VALIDACAO, ESCOLHA_METODOLOGICA ou MELHORIA.

Regras:
- não invente testes nem dependências;
- não presuma que shift() implica look-ahead;
- não presuma que abs() implica erro matemático;
- não transforme preferência arquitetural em bug;
- não altere o código;
- correções propostas devem ser mínimas;
- seja conservador com severidade CRITICA.

CÓDIGO:

```python
{source_code}
```

Retorne SOMENTE JSON válido nesta estrutura:
{schema}
""".strip()


def audit_engine(filename):
    source_code = read_engine(filename)
    prompt = build_individual_prompt(filename, source_code)
    result = extract_json(call_nemotron(prompt, MAX_TOKENS_INDIVIDUAL))
    if not isinstance(result, dict):
        raise ValueError("Resultado individual não é um objeto JSON.")
    result["arquivo"] = filename
    return result


def compact_individual_result(result):
    return {
        "arquivo": result.get("arquivo"),
        "veredito": result.get("veredito"),
        "score_estrutural": result.get("score_estrutural"),
        "confidence": result.get("confidence"),
        "erros_confirmados": result.get("erros_confirmados", []),
        "inconsistencias_provaveis": result.get("inconsistencias_provaveis", []),
        "requer_validacao": result.get("requer_validacao", []),
        "escolhas_metodologicas": result.get("escolhas_metodologicas", []),
        "integracao": result.get("integracao", {}),
        "conclusao": result.get("conclusao", ""),
    }


CROSS_SCHEMA = {
    "veredito_integrado": "APROVADO | APROVADO_COM_RESSALVAS | REQUER_VALIDACAO | INCONSISTENTE",
    "score_integrado": 0,
    "confidence": 0,
    "achados_confirmados": [],
    "achados_refutados": [],
    "inconsistencias_mantidas": [],
    "validacoes_necessarias": [],
    "novos_problemas_integracao": [],
    "escolhas_metodologicas": [],
    "prioridade_correcao": [],
    "pontos_fortes_integracao": [],
    "conclusao_final": "",
}


def build_cross_validation_prompt(results, sources):
    compact = [compact_individual_result(result) for result in results]
    schema = json.dumps(CROSS_SCHEMA, ensure_ascii=False, indent=2)
    audits_json = json.dumps(compact, ensure_ascii=False, indent=2)
    sources_json = json.dumps(sources, ensure_ascii=False, indent=2)

    return f"""
AUDITORIA CRUZADA DOS PRINCIPAIS MOTORES DE UM ROBÔ QUANTITATIVO

Revise os achados individuais relacionando todos os motores.

Objetivos:
- confirmar observações quando a integração fornecer evidência compatível;
- refutar observações quando outro motor mostrar que o comportamento está correto;
- manter como requer validação aquilo que não puder ser comprovado;
- identificar problemas novos de integração;
- verificar contratos de entrada e saída, nomes de colunas, índices, unidades, percentuais,
  pesos, flags, scores, formatos e semântica;
- verificar double counting, fail-open sistêmico, dependências frágeis e propagação incorreta.

Classificações de revisão:
CONFIRMADO_PELA_INTEGRACAO
REFUTADO_PELA_INTEGRACAO
MANTIDO_COMO_INCONSISTENCIA_PROVAVEL
MANTIDO_COMO_REQUER_VALIDACAO
ESCOLHA_METODOLOGICA
NOVO_PROBLEMA_DE_INTEGRACAO

Regras:
- use somente os códigos e auditorias fornecidos;
- não invente chamadas, outputs ou testes;
- não transforme metodologia em bug;
- não altere código;
- seja conservador ao confirmar erro.

AUDITORIAS INDIVIDUAIS:
{audits_json}

CÓDIGO DOS MOTORES:
{sources_json}

Retorne SOMENTE JSON válido nesta estrutura:
{schema}
""".strip()


def cross_validate(results, sources):
    prompt = build_cross_validation_prompt(results, sources)
    result = extract_json(call_nemotron(prompt, MAX_TOKENS_CROSS))
    if not isinstance(result, dict):
        raise ValueError("Resultado cruzado não é um objeto JSON.")
    return result


def create_markdown(results, cross_result, failures):
    lines = [
        "# Auditoria Estrutural — Nemotron",
        "",
        f"Data UTC: {utc_now()}",
        "",
        f"Modelo: `{MODEL}`",
        "",
        "## Auditorias Individuais",
        "",
        "| Motor | Veredito | Score | Erros | Inconsistências | Validações |",
        "|---|---|---:|---:|---:|---:|",
    ]

    for result in results:
        lines.append(
            f"| {result.get('arquivo', '')} "
            f"| {result.get('veredito', '')} "
            f"| {result.get('score_estrutural', '')} "
            f"| {len(result.get('erros_confirmados', []))} "
            f"| {len(result.get('inconsistencias_provaveis', []))} "
            f"| {len(result.get('requer_validacao', []))} |"
        )

    if failures:
        lines.extend(["", "## Falhas de Execução", ""])
        for failure in failures:
            lines.append(f"- **{failure['arquivo']}**: {failure['erro']}")

    lines.extend([
        "",
        "## Validação Cruzada",
        "",
        f"**Veredito integrado:** {cross_result.get('veredito_integrado', 'N/D')}",
        "",
        f"**Score integrado:** {cross_result.get('score_integrado', 'N/D')}",
        "",
        f"**Confiança:** {cross_result.get('confidence', 'N/D')}",
        "",
    ])

    conclusion = cross_result.get("conclusao_final", "")
    if conclusion:
        lines.extend(["## Conclusão", "", conclusion, ""])

    return "\n".join(lines)


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    sources = {}
    failures = []
    existing_engines = []

    for filename in MAIN_ENGINES:
        path = SRC_DIR / filename
        if path.is_file():
            existing_engines.append(filename)
        else:
            failures.append({
                "arquivo": filename,
                "erro": "Arquivo não encontrado em src/.",
            })

    if not existing_engines:
        raise RuntimeError("Nenhum dos motores principais foi encontrado.")

    print("=" * 78)
    print("NEMOTRON — AUDITORIA DOS PRINCIPAIS MOTORES")
    print("=" * 78)
    print(f"Motores encontrados: {len(existing_engines)}")
    print("=" * 78)

    for index, filename in enumerate(existing_engines, start=1):
        print(f"\n[{index}/{len(existing_engines)}] Auditando {filename}")

        try:
            sources[filename] = read_engine(filename)
            result = audit_engine(filename)
            results.append(result)
            save_json(
                OUTPUT_DIR / f"{Path(filename).stem}_audit.json",
                result,
            )
            print("Veredito:", result.get("veredito", "N/D"))
            print("Score:", result.get("score_estrutural", "N/D"))
        except Exception as exc:
            failure = {
                "arquivo": filename,
                "erro": f"{type(exc).__name__}: {exc}",
            }
            failures.append(failure)
            print("FALHA:", failure["erro"])

    if not results:
        raise RuntimeError("Nenhuma auditoria individual foi concluída.")

    print("\n" + "=" * 78)
    print("VALIDAÇÃO CRUZADA ENTRE OS MOTORES")
    print("=" * 78)

    cross_result = cross_validate(results, sources)

    complete_report = {
        "timestamp_utc": utc_now(),
        "model": MODEL,
        "motores_planejados": MAIN_ENGINES,
        "motores_auditados": [result.get("arquivo") for result in results],
        "falhas_execucao": failures,
        "auditorias_individuais": results,
        "validacao_cruzada": cross_result,
    }

    save_json(
        OUTPUT_DIR / "robot_audit_complete.json",
        complete_report,
    )

    markdown = create_markdown(results, cross_result, failures)
    (OUTPUT_DIR / "robot_audit_report.md").write_text(
        markdown,
        encoding="utf-8",
    )

    print("\n" + "=" * 78)
    print("AUDITORIA CONCLUÍDA")
    print("=" * 78)
    print("Veredito integrado:", cross_result.get("veredito_integrado", "N/D"))
    print("Score integrado:", cross_result.get("score_integrado", "N/D"))
    print("Confiança:", cross_result.get("confidence", "N/D"))
    print("Motores auditados:", len(results))
    print("Falhas de execução:", len(failures))
    print("Relatório completo:", OUTPUT_DIR / "robot_audit_complete.json")
    print("Relatório leitura:", OUTPUT_DIR / "robot_audit_report.md")
    print("=" * 78)


def main():
    try:
        run()
    except Exception as exc:
        print("\n" + "=" * 78)
        print("AUDITORIA FALHOU")
        print("=" * 78)
        print(f"{type(exc).__name__}: {exc}")
        print("=" * 78)
        sys.exit(1)


if __name__ == "__main__":
    main()
