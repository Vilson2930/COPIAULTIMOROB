import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

from nemotron_robot_auditor import (
    MAIN_ENGINES,
    MODEL,
    OUTPUT_DIR,
    SRC_DIR,
    FINAL_STAGE_MAX_ATTEMPTS,
    FINAL_STAGE_RETRY_WAIT_SECONDS,
    call_nemotron_json,
    precheck_nemotron,
    save_json,
)

DECISION_BLOCK_SIZE = 4
MAX_TOKENS_DECISION_BLOCK = 7000
MAX_TOKENS_BUG_VERIFY = 5000
BLOCK_STRUCTURAL_ATTEMPTS = 2

DECISION_CLASSES = {
    "BUG_REAL",
    "REGRA_INTENCIONAL",
    "NAO_APLICAVEL_NO_PIPELINE_ATUAL",
    "FRAGILIDADE_FUTURA",
    "QUESTAO_METODOLOGICA",
    "REFUTADO",
    "REQUER_VALIDACAO",
}

NON_BUG_CLASSES = DECISION_CLASSES - {"BUG_REAL"}

FACT_LISTS = [
    "fatos_confirmados",
    "fatos_refutados",
    "evidencia_insuficiente",
    "escolhas_metodologicas",
    "riscos_potenciais_nao_comprovados",
]

RELATIONS = {
    "data_engine.py": [
        "macro_engine.py",
        "portfolio_engine.py",
    ],
    "macro_engine.py": [
        "data_engine.py",
        "portfolio_engine.py",
        "governance_engine.py",
    ],
    "portfolio_engine.py": [
        "macro_engine.py",
        "allocation_advisor.py",
        "operational_risk.py",
        "stress_engine.py",
        "governance_engine.py",
    ],
    "allocation_advisor.py": [
        "portfolio_engine.py",
        "governance_engine.py",
    ],
    "operational_risk.py": [
        "portfolio_engine.py",
        "stress_engine.py",
        "governance_engine.py",
    ],
    "stress_engine.py": [
        "portfolio_engine.py",
        "operational_risk.py",
        "governance_engine.py",
    ],
    "risk_budget_engine.py": [
        "portfolio_engine.py",
        "governance_engine.py",
    ],
    "liquidity_engine.py": [
        "portfolio_engine.py",
        "governance_engine.py",
    ],
    "counterparty_engine.py": [
        "portfolio_engine.py",
        "governance_engine.py",
    ],
    "governance_engine.py": list(MAIN_ENGINES),
}


def log(message=""):
    print(message, flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo obrigatório não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_policy():
    path = Path("config/audit_policy.json")
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "version": 1,
        "principles": [
            "FATO_CONFIRMADO prova apenas que o comportamento existe; não prova que seja bug.",
            "Somente classifique BUG_REAL quando houver cálculo incorreto, integração quebrada, contrato violado, dado relevante ignorado ou comportamento contrário à metodologia definida.",
            "Alertas de risco corretos não são bugs só porque o risco é alto.",
            "Fail-safe explicitamente documentado é regra intencional, salvo se contradizer contrato superior.",
            "Não alterar código e não gerar testes.",
        ],
    }


def numbered_text(text):
    return "\n".join(
        f"{idx:04d}: {line}"
        for idx, line in enumerate(text.splitlines(), start=1)
    )


def load_sources():
    sources = {}
    missing = []

    for filename in MAIN_ENGINES:
        path = SRC_DIR / filename
        if not path.is_file():
            missing.append(filename)
            continue
        sources[filename] = numbered_text(
            path.read_text(encoding="utf-8", errors="replace")
        )

    if missing:
        raise RuntimeError(
            "Motores obrigatórios ausentes em src/: "
            + ", ".join(missing)
        )

    main_path = Path("main.py")
    if main_path.is_file():
        sources["main.py"] = numbered_text(
            main_path.read_text(encoding="utf-8", errors="replace")
        )

    return sources


def flatten_fact_findings(fact_result):
    findings = []

    for source_list in FACT_LISTS:
        rows = fact_result.get(source_list, [])
        if not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue

            item = dict(row)
            item["_fact_list"] = source_list

            finding_id = str(item.get("finding_id", "")).strip()
            if not finding_id:
                raise RuntimeError(
                    f"Achado sem finding_id em {source_list}."
                )

            findings.append(item)

    if not findings:
        raise RuntimeError("robot_fact_filter.json não possui achados.")

    seen = set()
    for item in findings:
        fid = item["finding_id"]
        if fid in seen:
            raise RuntimeError(f"finding_id duplicado: {fid}")
        seen.add(fid)

    return sorted(
        findings,
        key=lambda x: int(re.sub(r"\D", "", x["finding_id"]) or 0),
    )


def finding_text(finding):
    return json.dumps(finding, ensure_ascii=False, sort_keys=True)


def infer_engine_names(finding, all_sources):
    text = finding_text(finding).lower()
    selected = set()

    original = finding.get("achado_original", {})
    if isinstance(original, dict):
        origin = original.get("origem")
        if origin in all_sources:
            selected.add(origin)

    for filename in MAIN_ENGINES:
        stem = filename.replace(".py", "").lower()
        pretty = stem.replace("_engine", "").replace("_", " ")
        if filename.lower() in text or stem in text or pretty in text:
            selected.add(filename)

    expanded = set(selected)
    for filename in list(selected):
        expanded.update(RELATIONS.get(filename, []))

    # Governance é o consumidor integrado principal; incluir quando houver
    # qualquer achado de contrato/score/flag/veredito.
    integration_terms = (
        "integra", "contrato", "score", "flag", "vered", "govern",
        "upstream", "downstream", "output", "input", "nome", "unidade",
    )
    if any(term in text for term in integration_terms):
        expanded.add("governance_engine.py")

    # main.py prova a orquestração real.
    if "main.py" in all_sources:
        expanded.add("main.py")

    # Limita a quantidade de motores por achado para manter contexto manejável.
    ordered = []
    for name in list(MAIN_ENGINES) + ["main.py"]:
        if name in expanded and name in all_sources:
            ordered.append(name)

    if not ordered:
        ordered = ["main.py"] if "main.py" in all_sources else []
        # Sem origem clara: inclua governance + primeiro motor citado no fato.
        if "governance_engine.py" in all_sources:
            ordered.insert(0, "governance_engine.py")

    # Máximo de 6 fontes por bloco, priorizando origem/relacionados.
    return ordered[:6]


def relevant_sources_for_block(block, all_sources):
    names = []
    for finding in block:
        for name in infer_engine_names(finding, all_sources):
            if name not in names:
                names.append(name)

    # Em blocos heterogêneos, evita prompt excessivo.
    names = names[:8]
    return {name: all_sources[name] for name in names}


def decision_schema(block):
    return {
        "confidence": 0,
        "resultados": [
            {
                "finding_id": item["finding_id"],
                "classificacao_decisao": "BUG_REAL",
                "acao": "CORRIGIR",
                "prioridade": "ALTA",
                "motor_principal": "arquivo.py",
                "motores_relacionados": ["arquivo.py"],
                "funcao_ou_bloco": "nome",
                "linhas_relevantes": ["0001-0005"],
                "comportamento_observado": "curto",
                "comportamento_esperado": "curto",
                "prova_integracao": "curto",
                "por_que_e_ou_nao_e_bug": "curto",
                "impacto_real": "curto",
                "confidence": 0,
            }
            for item in block
        ],
    }


def build_decision_prompt(block, sources, policy, block_number, total_blocks):
    compact_findings = []
    for item in block:
        compact_findings.append({
            "finding_id": item["finding_id"],
            "classificacao_factual": item.get("classificacao_factual"),
            "categoria_na_validacao_cruzada": item.get(
                "categoria_na_validacao_cruzada"
            ),
            "fact_list": item.get("_fact_list"),
            "conclusao": item.get("conclusao"),
            "evidencia": item.get("evidencia"),
            "motivo": item.get("motivo"),
            "achado_original": item.get("achado_original"),
        })

    schema = decision_schema(block)

    return f"""
Você é o JULGADOR TÉCNICO FINAL de um robô financeiro.

Esta é a QUARTA CAMADA da auditoria.
As camadas anteriores localizaram comportamentos e fizeram filtro factual.
Agora sua obrigação é decidir se cada comportamento é realmente um BUG
do sistema atual.

REGRA CENTRAL:
"FATO_CONFIRMADO" significa somente que o comportamento descrito existe.
NÃO significa que o comportamento seja defeito.

Você DEVE voltar ao código atual fornecido, conferir o motor de origem,
os motores relacionados, o consumidor downstream e a orquestração real.
Não aceite a conclusão da auditoria anterior sem revalidá-la.

CLASSIFICAÇÕES PERMITIDAS:
- BUG_REAL
- REGRA_INTENCIONAL
- NAO_APLICAVEL_NO_PIPELINE_ATUAL
- FRAGILIDADE_FUTURA
- QUESTAO_METODOLOGICA
- REFUTADO
- REQUER_VALIDACAO

Use BUG_REAL SOMENTE se a prova fechar TODOS estes pontos:
1. existe no código atual;
2. ocorre em caminho executável/relevante;
3. o comportamento está objetivamente errado;
4. existe comportamento esperado demonstrável pelo próprio contrato,
   metodologia ou integração;
5. não é apenas alerta de risco, escolha metodológica, fail-safe,
   extensibilidade futura ou preferência de modelagem;
6. há impacto real em cálculo, integração, score, flag, decisão ou saída.

Se qualquer ponto acima não fechar, NÃO use BUG_REAL.

REGRAS IMPORTANTES:
- pesos-alvo configurados pelo robô são decisões metodológicas; não chame
  concentração alta de bug apenas porque é alta;
- contribuição de risco elevada de BTC ou outro ativo é diagnóstico, não bug,
  se a matemática estiver correta;
- um limite genérico só invalida um peso-alvo se o código/metodologia o tratar
  explicitamente como invariável obrigatória;
- comportamento conservador/fail-safe documentado é REGRA_INTENCIONAL;
- código preparado para um ativo futuro, mas correto para o universo atual,
  é FRAGILIDADE_FUTURA ou NAO_APLICAVEL_NO_PIPELINE_ATUAL;
- se o achado original estiver errado diante do código, use REFUTADO;
- se a decisão depender de intenção metodológica não documentada, use
  QUESTAO_METODOLOGICA ou REQUER_VALIDACAO;
- não proponha mudar pesos da carteira;
- não altere código;
- não gere nem execute testes.

AÇÃO:
- somente BUG_REAL pode receber "acao": "CORRIGIR";
- todas as outras classes devem receber
  "acao": "NAO_CORRIGIR_AUTOMATICAMENTE".

Para BUG_REAL, "por_que_e_ou_nao_e_bug" deve conter uma cadeia curta:
código -> contrato esperado -> divergência -> impacto.
Sem essa cadeia, rebaixe a classificação.

Bloco {block_number}/{total_blocks}.

POLÍTICA/METODOLOGIA DO ROBÔ:
{json.dumps(policy, ensure_ascii=False, indent=2)}

ACHADOS:
{json.dumps(compact_findings, ensure_ascii=False, indent=2)}

CÓDIGO ATUAL COM NÚMEROS DE LINHA:
{json.dumps(sources, ensure_ascii=False, indent=2)}

Retorne SOMENTE JSON válido, exatamente nesta estrutura:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def validate_decision_result(result, block):
    if not isinstance(result, dict):
        raise ValueError("Resposta de decisão não é objeto JSON.")

    rows = result.get("resultados")
    if not isinstance(rows, list):
        raise ValueError("Campo resultados ausente ou inválido.")

    expected = {item["finding_id"] for item in block}
    received = []

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Resultado individual inválido.")

        fid = row.get("finding_id")
        cls = row.get("classificacao_decisao")
        action = row.get("acao")

        if fid not in expected:
            raise ValueError(f"finding_id inesperado: {fid}")

        if cls not in DECISION_CLASSES:
            raise ValueError(
                f"Classificação inválida em {fid}: {cls}"
            )

        expected_action = (
            "CORRIGIR"
            if cls == "BUG_REAL"
            else "NAO_CORRIGIR_AUTOMATICAMENTE"
        )
        if action != expected_action:
            raise ValueError(
                f"Ação incompatível em {fid}: {action}; "
                f"esperado={expected_action}"
            )

        received.append(fid)

    if set(received) != expected or len(received) != len(expected):
        raise ValueError(
            "Resposta não contém exatamente todos os finding_id do bloco."
        )

    return rows


def run_decision_blocks(findings, sources, policy):
    total_blocks = (
        len(findings) + DECISION_BLOCK_SIZE - 1
    ) // DECISION_BLOCK_SIZE

    all_rows = []
    confidences = []

    for start in range(0, len(findings), DECISION_BLOCK_SIZE):
        block = findings[start:start + DECISION_BLOCK_SIZE]
        block_number = (start // DECISION_BLOCK_SIZE) + 1
        relevant_sources = relevant_sources_for_block(block, sources)

        log("")
        log(
            f"[DECISAO] Bloco {block_number}/{total_blocks} | "
            f"achados={len(block)} | "
            f"fontes={', '.join(relevant_sources.keys())}"
        )

        prompt = build_decision_prompt(
            block,
            relevant_sources,
            policy,
            block_number,
            total_blocks,
        )

        last_error = None

        for structural_attempt in range(
            1, BLOCK_STRUCTURAL_ATTEMPTS + 1
        ):
            try:
                result = call_nemotron_json(
                    prompt,
                    MAX_TOKENS_DECISION_BLOCK,
                    stage=(
                        f"Julgamento técnico bloco "
                        f"{block_number}/{total_blocks}"
                    ),
                    max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
                    retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
                )

                rows = validate_decision_result(result, block)

                source_by_id = {
                    item["finding_id"]: item
                    for item in block
                }

                for row in rows:
                    original = source_by_id[row["finding_id"]]
                    row["classificacao_factual_anterior"] = (
                        original.get("classificacao_factual")
                    )
                    row["fact_list_anterior"] = original.get("_fact_list")
                    row["achado_factual_anterior"] = {
                        k: v
                        for k, v in original.items()
                        if not k.startswith("_")
                    }

                all_rows.extend(rows)

                confidence = result.get("confidence")
                if isinstance(confidence, (int, float)):
                    confidences.append(float(confidence))

                save_json(
                    OUTPUT_DIR
                    / f"robot_decision_filter_part_{block_number}.json",
                    {
                        "bloco": block_number,
                        "total_blocos": total_blocks,
                        "fontes": list(relevant_sources.keys()),
                        "confidence": result.get("confidence"),
                        "resultados": rows,
                    },
                )

                log(
                    f"[OK] Bloco de decisão "
                    f"{block_number}/{total_blocks} concluído."
                )
                last_error = None
                break

            except Exception as exc:
                last_error = exc
                log(
                    f"[DECISAO] Estrutura inválida no bloco "
                    f"{block_number}/{total_blocks}: "
                    f"{type(exc).__name__}: {exc}"
                )

                if structural_attempt < BLOCK_STRUCTURAL_ATTEMPTS:
                    log(
                        "[DECISAO] Reexecutando somente este bloco."
                    )

        if last_error is not None:
            raise RuntimeError(
                f"Bloco de decisão {block_number}/{total_blocks} falhou: "
                f"{type(last_error).__name__}: {last_error}"
            )

    return all_rows, confidences


def bug_verify_schema(row):
    return {
        "finding_id": row["finding_id"],
        "verificacao_bug": "CONFIRMADO_COM_PROVA",
        "classificacao_final": "BUG_REAL",
        "acao_final": "CORRIGIR",
        "prova_final": {
            "arquivo": "arquivo.py",
            "funcao_ou_bloco": "nome",
            "linhas": ["0001-0005"],
            "comportamento_atual": "curto",
            "contrato_esperado": "curto",
            "divergencia_objetiva": "curto",
            "impacto": "curto",
        },
        "motivo_final": "curto",
        "confidence": 0,
    }


def build_bug_verify_prompt(row, sources, policy):
    relevant_names = infer_engine_names(
        row.get("achado_factual_anterior", {}),
        sources,
    )

    # Reaproveita também os motores citados no primeiro julgamento.
    for name in row.get("motores_relacionados", []) or []:
        if name in sources and name not in relevant_names:
            relevant_names.append(name)

    principal = row.get("motor_principal")
    if principal in sources and principal not in relevant_names:
        relevant_names.insert(0, principal)

    relevant_names = relevant_names[:8]
    relevant_sources = {
        name: sources[name]
        for name in relevant_names
        if name in sources
    }

    schema = bug_verify_schema(row)

    return f"""
Você é o REVISOR FINAL E ADVERSARIAL de um candidato a BUG_REAL.

O primeiro julgador marcou este achado como BUG_REAL.
Sua função é tentar REFUTAR essa conclusão antes que ele entre na fila
de correção.

CONFIRME COMO BUG somente se houver prova objetiva completa no código atual:
- caminho executável/relevante;
- comportamento atual;
- contrato/metodologia esperada;
- divergência inequívoca;
- impacto real;
- não ser escolha metodológica, fail-safe, diagnóstico de risco,
  extensibilidade futura ou cenário não aplicável.

Se a prova não fechar, você DEVE rebaixar para uma destas classes:
- REGRA_INTENCIONAL
- NAO_APLICAVEL_NO_PIPELINE_ATUAL
- FRAGILIDADE_FUTURA
- QUESTAO_METODOLOGICA
- REFUTADO
- REQUER_VALIDACAO

"verificacao_bug" deve ser:
- CONFIRMADO_COM_PROVA
ou
- NAO_CONFIRMADO

Somente CONFIRMADO_COM_PROVA pode manter:
"classificacao_final": "BUG_REAL"
e "acao_final": "CORRIGIR".

Não altere código. Não gere testes. Não mude pesos da carteira.

POLÍTICA:
{json.dumps(policy, ensure_ascii=False, indent=2)}

CANDIDATO:
{json.dumps(row, ensure_ascii=False, indent=2)}

CÓDIGO ATUAL:
{json.dumps(relevant_sources, ensure_ascii=False, indent=2)}

Retorne SOMENTE JSON válido nesta estrutura:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def verify_bug_candidates(rows, sources, policy):
    verified = []

    for row in rows:
        if row["classificacao_decisao"] != "BUG_REAL":
            row["segunda_revisao_bug"] = "NAO_NECESSARIA"
            verified.append(row)
            continue

        fid = row["finding_id"]
        log(f"[BUG-CHECK] Segunda revisão adversarial de {fid}")

        prompt = build_bug_verify_prompt(row, sources, policy)
        result = call_nemotron_json(
            prompt,
            MAX_TOKENS_BUG_VERIFY,
            stage=f"Segunda revisão do bug {fid}",
            max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
            retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
        )

        if not isinstance(result, dict):
            raise ValueError(f"Segunda revisão inválida em {fid}")

        if result.get("finding_id") != fid:
            raise ValueError(f"finding_id divergente em {fid}")

        check = result.get("verificacao_bug")
        final_class = result.get("classificacao_final")
        final_action = result.get("acao_final")

        if check == "CONFIRMADO_COM_PROVA":
            if final_class != "BUG_REAL" or final_action != "CORRIGIR":
                raise ValueError(
                    f"Confirmação de bug inconsistente em {fid}"
                )
            row["segunda_revisao_bug"] = "CONFIRMADO_COM_PROVA"
            row["verificacao_final_bug"] = result
        else:
            if final_class not in NON_BUG_CLASSES:
                raise ValueError(
                    f"Rebaixamento inválido em {fid}: {final_class}"
                )
            if final_action != "NAO_CORRIGIR_AUTOMATICAMENTE":
                raise ValueError(
                    f"Ação final inválida em {fid}: {final_action}"
                )

            row["segunda_revisao_bug"] = "NAO_CONFIRMADO"
            row["classificacao_decisao_inicial"] = "BUG_REAL"
            row["classificacao_decisao"] = final_class
            row["acao"] = final_action
            row["motivo_rebaixamento"] = result.get("motivo_final")
            row["verificacao_final_bug"] = result

        verified.append(row)

    return verified


def confidence_of(rows, block_confidences):
    values = []
    for row in rows:
        value = row.get("confidence")
        if isinstance(value, (int, float)):
            values.append(float(value))

    if values:
        return round(sum(values) / len(values))
    if block_confidences:
        return round(sum(block_confidences) / len(block_confidences))
    return 0


def consolidate(rows, block_confidences):
    by_class = {
        classification: []
        for classification in DECISION_CLASSES
    }

    for row in rows:
        by_class[row["classificacao_decisao"]].append(row)

    bugs = by_class["BUG_REAL"]

    severity_rank = {
        "CRITICA": 4,
        "CRÍTICA": 4,
        "ALTA": 3,
        "MEDIA": 2,
        "MÉDIA": 2,
        "BAIXA": 1,
    }

    def rank_bug(row):
        priority = str(row.get("prioridade", "")).upper()
        p_rank = severity_rank.get(priority, 0)
        confidence = float(row.get("confidence", 0) or 0)
        return (p_rank, confidence)

    correction_queue = sorted(
        bugs,
        key=rank_bug,
        reverse=True,
    )

    if bugs:
        verdict = "HA_BUGS_REAIS_CONFIRMADOS"
    elif by_class["REQUER_VALIDACAO"]:
        verdict = "SEM_BUG_CONFIRMADO_MAS_HA_VALIDACOES"
    else:
        verdict = "SEM_BUGS_REAIS_CONFIRMADOS"

    return {
        "veredito_tecnico_final": verdict,
        "confidence": confidence_of(rows, block_confidences),
        "bugs_reais": bugs,
        "regras_intencionais": by_class["REGRA_INTENCIONAL"],
        "nao_aplicaveis_pipeline_atual": by_class[
            "NAO_APLICAVEL_NO_PIPELINE_ATUAL"
        ],
        "fragilidades_futuras": by_class["FRAGILIDADE_FUTURA"],
        "questoes_metodologicas": by_class["QUESTAO_METODOLOGICA"],
        "refutados": by_class["REFUTADO"],
        "requer_validacao": by_class["REQUER_VALIDACAO"],
        "fila_correcao": correction_queue,
        "resumo_quantitativo": {
            "bugs_reais": len(bugs),
            "regras_intencionais": len(
                by_class["REGRA_INTENCIONAL"]
            ),
            "nao_aplicaveis_pipeline_atual": len(
                by_class["NAO_APLICAVEL_NO_PIPELINE_ATUAL"]
            ),
            "fragilidades_futuras": len(
                by_class["FRAGILIDADE_FUTURA"]
            ),
            "questoes_metodologicas": len(
                by_class["QUESTAO_METODOLOGICA"]
            ),
            "refutados": len(by_class["REFUTADO"]),
            "requer_validacao": len(
                by_class["REQUER_VALIDACAO"]
            ),
            "total_julgado": len(rows),
        },
        "metodo": {
            "camada": "JULGAMENTO_TECNICO_FINAL",
            "modelo": MODEL,
            "bloco": DECISION_BLOCK_SIZE,
            "segunda_revisao_adversarial": True,
            "somente_bug_real_entra_na_fila_correcao": True,
            "modifica_codigo": False,
            "gera_testes": False,
        },
    }


def create_markdown(result):
    summary = result["resumo_quantitativo"]
    lines = [
        "# Nemotron — Julgamento Técnico Final",
        "",
        f"**Veredito:** {result['veredito_tecnico_final']}",
        f"**Confiança:** {result['confidence']}%",
        "",
        "## Resumo",
        "",
        f"- Bugs reais confirmados: {summary['bugs_reais']}",
        f"- Regras intencionais: {summary['regras_intencionais']}",
        (
            "- Não aplicáveis no pipeline atual: "
            f"{summary['nao_aplicaveis_pipeline_atual']}"
        ),
        f"- Fragilidades futuras: {summary['fragilidades_futuras']}",
        f"- Questões metodológicas: {summary['questoes_metodologicas']}",
        f"- Refutados: {summary['refutados']}",
        f"- Requer validação: {summary['requer_validacao']}",
        f"- Total julgado: {summary['total_julgado']}",
        "",
        "## Fila de correção",
        "",
    ]

    queue = result["fila_correcao"]
    if not queue:
        lines.append("Nenhum BUG_REAL confirmado para correção.")
    else:
        for row in queue:
            lines.extend([
                f"### {row['finding_id']} — {row.get('motor_principal', 'N/D')}",
                "",
                f"- Prioridade: {row.get('prioridade', 'N/D')}",
                f"- Impacto: {row.get('impacto_real', 'N/D')}",
                f"- Prova: {row.get('por_que_e_ou_nao_e_bug', 'N/D')}",
                "",
            ])

    return "\n".join(lines) + "\n"


def update_complete_report(decision_result):
    path = OUTPUT_DIR / "robot_audit_complete.json"
    if not path.is_file():
        return

    complete = load_json(path)
    complete["julgamento_tecnico_final"] = decision_result
    complete["julgamento_tecnico_executado"] = True
    complete["julgamento_tecnico_em_utc"] = utc_now()
    complete["status"] = "CONCLUIDA_COM_JULGAMENTO_TECNICO"
    save_json(path, complete)


def main():
    log("=" * 78)
    log("NEMOTRON — JULGAMENTO TÉCNICO FINAL")
    log("=" * 78)

    if not os.getenv("NVIDIA_API_KEY"):
        raise RuntimeError(
            "NVIDIA_API_KEY não encontrada no ambiente."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    fact_path = OUTPUT_DIR / "robot_fact_filter.json"
    log(f"[LOAD] Filtro factual: {fact_path}")
    fact_result = load_json(fact_path)

    findings = flatten_fact_findings(fact_result)
    sources = load_sources()
    policy = load_policy()

    log(
        f"[OK] Achados carregados: {len(findings)} | "
        f"motores: {len(MAIN_ENGINES)} | "
        f"orquestrador={'SIM' if 'main.py' in sources else 'NAO'}"
    )

    precheck_nemotron()

    rows, block_confidences = run_decision_blocks(
        findings,
        sources,
        policy,
    )

    if len(rows) != len(findings):
        raise RuntimeError(
            f"Julgamento incompleto: {len(rows)}/{len(findings)}"
        )

    rows = verify_bug_candidates(
        rows,
        sources,
        policy,
    )

    final_result = consolidate(
        rows,
        block_confidences,
    )

    save_json(
        OUTPUT_DIR / "robot_decision_filter.json",
        final_result,
    )

    save_json(
        OUTPUT_DIR / "robot_correction_queue.json",
        {
            "timestamp_utc": utc_now(),
            "veredito_tecnico_final": final_result[
                "veredito_tecnico_final"
            ],
            "bugs_reais_confirmados": final_result["fila_correcao"],
            "total_para_corrigir": len(final_result["fila_correcao"]),
            "observacao": (
                "Somente achados confirmados como BUG_REAL em duas "
                "camadas entram nesta fila. Nenhum código foi alterado."
            ),
        },
    )

    (OUTPUT_DIR / "robot_decision_report.md").write_text(
        create_markdown(final_result),
        encoding="utf-8",
    )

    update_complete_report(final_result)

    summary = final_result["resumo_quantitativo"]

    log("")
    log("=" * 78)
    log("JULGAMENTO TÉCNICO CONCLUÍDO")
    log("=" * 78)
    log(
        f"Veredito: {final_result['veredito_tecnico_final']}"
    )
    log(f"Confiança: {final_result['confidence']}")
    log(f"BUGS REAIS: {summary['bugs_reais']}")
    log(
        "Regras intencionais: "
        f"{summary['regras_intencionais']}"
    )
    log(
        "Não aplicáveis agora: "
        f"{summary['nao_aplicaveis_pipeline_atual']}"
    )
    log(
        "Fragilidades futuras: "
        f"{summary['fragilidades_futuras']}"
    )
    log(
        "Questões metodológicas: "
        f"{summary['questoes_metodologicas']}"
    )
    log(f"Refutados: {summary['refutados']}")
    log(
        f"Requer validação: {summary['requer_validacao']}"
    )
    log(
        "Fila de correção: "
        f"{OUTPUT_DIR / 'robot_correction_queue.json'}"
    )
    log("=" * 78)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("")
        log("=" * 78)
        log("JULGAMENTO TÉCNICO FALHOU")
        log("=" * 78)
        log(f"{type(exc).__name__}: {exc}")
        log("=" * 78)
        sys.exit(1)
