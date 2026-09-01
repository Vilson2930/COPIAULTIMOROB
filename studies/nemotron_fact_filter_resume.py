import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timezone

# Reutiliza o cliente, retries, timeout e reparo JSON já validados
# do auditor estrutural principal.
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


FACT_BLOCK_SIZE = 6
MAX_TOKENS_FACT_BLOCK = 6500
BLOCK_STRUCTURAL_ATTEMPTS = 2

FACT_CLASSES = {
    "FATO_CONFIRMADO",
    "FATO_REFUTADO",
    "EVIDENCIA_INSUFICIENTE",
    "ESCOLHA_METODOLOGICA",
    "RISCO_POTENCIAL_NAO_COMPROVADO",
}

CROSS_LISTS = [
    "achados_confirmados",
    "achados_refutados",
    "inconsistencias_mantidas",
    "validacoes_necessarias",
]


def log(message=""):
    print(message, flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo obrigatório não encontrado: {path}")

    return json.loads(path.read_text(encoding="utf-8"))


def load_sources():
    sources = {}
    missing = []

    for filename in MAIN_ENGINES:
        path = SRC_DIR / filename

        if not path.is_file():
            missing.append(filename)
            continue

        sources[filename] = path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    if missing:
        raise RuntimeError(
            "Motores obrigatórios ausentes em src/: "
            + ", ".join(missing)
        )

    return sources


def validate_previous_audit(cross_result):
    if not isinstance(cross_result, dict):
        raise RuntimeError(
            "robot_cross_validation.json não contém um objeto JSON válido."
        )

    required = [
        "veredito_integrado",
        "score_integrado",
        "confidence",
    ]

    missing = [field for field in required if field not in cross_result]

    if missing:
        raise RuntimeError(
            "Validação cruzada anterior incompleta. Campos ausentes: "
            + ", ".join(missing)
        )

    total = sum(
        len(cross_result.get(key, []))
        for key in CROSS_LISTS
        if isinstance(cross_result.get(key, []), list)
    )

    if total == 0:
        raise RuntimeError(
            "Nenhum achado foi encontrado na validação cruzada."
        )

    return total


def flatten_cross_findings(cross_result):
    findings = []
    seq = 1

    for category in CROSS_LISTS:
        items = cross_result.get(category, [])

        if not isinstance(items, list):
            continue

        for item in items:
            if not isinstance(item, dict):
                item = {"conteudo": str(item)}

            finding = dict(item)
            finding["_finding_id"] = f"F{seq:03d}"
            finding["_categoria_origem"] = category

            findings.append(finding)
            seq += 1

    return findings


def text_of_finding(finding):
    return json.dumps(
        finding,
        ensure_ascii=False,
        sort_keys=True,
    )


def relevant_sources_for_block(block, all_sources):
    filenames = set()

    for finding in block:
        origin = finding.get("origem")
        if origin in all_sources:
            filenames.add(origin)

        text = text_of_finding(finding)

        for filename in MAIN_ENGINES:
            if filename in text:
                filenames.add(filename)

    # Se nenhum motor foi identificável, usa todos apenas como fallback.
    if not filenames:
        return dict(all_sources)

    return {
        filename: all_sources[filename]
        for filename in MAIN_ENGINES
        if filename in filenames
    }


def build_fact_block_prompt(block, relevant_sources, block_number, total_blocks):
    findings_payload = []

    for finding in block:
        clean = {
            key: value
            for key, value in finding.items()
            if not key.startswith("_")
        }

        findings_payload.append(
            {
                "finding_id": finding["_finding_id"],
                "categoria_na_validacao_cruzada": finding["_categoria_origem"],
                "achado": clean,
            }
        )

    schema = {
        "bloco": block_number,
        "confidence": 0,
        "resultados": [
            {
                "finding_id": "F001",
                "classificacao_factual": (
                    "FATO_CONFIRMADO | FATO_REFUTADO | "
                    "EVIDENCIA_INSUFICIENTE | ESCOLHA_METODOLOGICA | "
                    "RISCO_POTENCIAL_NAO_COMPROVADO"
                ),
                "arquivo": "",
                "funcao_ou_bloco": "",
                "expressao_exata_curta": "",
                "comportamento_observado": "",
                "comportamento_esperado": "",
                "prova_ou_motivo": "",
                "cadeia_logica": "",
                "impacto_concreto": "",
                "evidencia_integracao": "",
                "confidence": 0,
            }
        ],
    }

    return f"""
FILTRO FINAL DE FATO — BLOCO {block_number}/{total_blocks}

Esta é a terceira camada de uma auditoria estrutural de robô quantitativo.

Você NÃO deve procurar livremente novos problemas.
Você deve julgar SOMENTE os achados deste bloco.

Para CADA finding_id, produza EXATAMENTE UMA classificação:
- FATO_CONFIRMADO
- FATO_REFUTADO
- EVIDENCIA_INSUFICIENTE
- ESCOLHA_METODOLOGICA
- RISCO_POTENCIAL_NAO_COMPROVADO

REGRA FORTE PARA FATO_CONFIRMADO:

Só use FATO_CONFIRMADO quando o código fornecido demonstrar objetiva e
diretamente a divergência.

A prova deve fechar:
1. arquivo;
2. função/método/bloco, quando identificável;
3. expressão curta e exata do código;
4. comportamento observado;
5. comportamento esperado demonstrável;
6. cadeia lógica;
7. impacto concreto;
8. evidência de integração, quando aplicável;
9. confiança.

NÃO use FATO_CONFIRMADO quando:
- depender de requisito de negócio não fornecido;
- depender de dado externo;
- depender de teste não executado;
- for preferência arquitetural;
- for melhoria de robustez;
- houver mais de uma interpretação razoável;
- o comportamento esperado não puder ser demonstrado;
- outro motor justificar o comportamento;
- a cadeia causal estiver incompleta.

Use FATO_REFUTADO quando o próprio código ou contrato fornecido demonstrar
que a acusação não procede.

Use EVIDENCIA_INSUFICIENTE quando houver suspeita plausível, mas a prova
não fechar.

Use ESCOLHA_METODOLOGICA quando o ponto for uma decisão coerente de
modelagem/arquitetura e não um erro demonstrável.

Use RISCO_POTENCIAL_NAO_COMPROVADO quando existir cenário de risco,
mas o problema não estiver demonstrado no código atual.

REGRAS DE SAÍDA:
- responda SOMENTE JSON válido;
- devolva exatamente {len(block)} resultados;
- preserve cada finding_id exatamente;
- não omita nenhum finding_id;
- não duplique finding_id;
- seja conciso;
- não reproduza grandes trechos de código;
- "expressao_exata_curta" deve ser realmente curta;
- não altere código;
- não gere testes;
- não invente requisitos ou contratos.

ACHADOS DESTE BLOCO:
{json.dumps(findings_payload, ensure_ascii=False, indent=2)}

CÓDIGO RELEVANTE PARA ESTE BLOCO:
{json.dumps(relevant_sources, ensure_ascii=False, indent=2)}

Retorne SOMENTE JSON válido nesta estrutura:
{json.dumps(schema, ensure_ascii=False, indent=2)}
""".strip()


def validate_block_result(result, block):
    if not isinstance(result, dict):
        raise ValueError("Resposta do bloco não é objeto JSON.")

    rows = result.get("resultados")

    if not isinstance(rows, list):
        raise ValueError("Campo 'resultados' ausente ou inválido.")

    expected_ids = {item["_finding_id"] for item in block}
    received_ids = []

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Resultado factual individual não é objeto.")

        finding_id = row.get("finding_id")
        classification = row.get("classificacao_factual")

        if finding_id not in expected_ids:
            raise ValueError(
                f"finding_id inesperado no bloco: {finding_id}"
            )

        if classification not in FACT_CLASSES:
            raise ValueError(
                f"Classificação factual inválida em {finding_id}: "
                f"{classification}"
            )

        received_ids.append(finding_id)

    if len(received_ids) != len(set(received_ids)):
        raise ValueError("Há finding_id duplicado no bloco.")

    missing = expected_ids - set(received_ids)

    if missing:
        raise ValueError(
            "Finding IDs ausentes no bloco: "
            + ", ".join(sorted(missing))
        )

    if len(rows) != len(block):
        raise ValueError(
            f"Quantidade incorreta de resultados: "
            f"{len(rows)} recebido(s), {len(block)} esperado(s)."
        )

    return rows


def run_fact_blocks(findings, sources):
    total_blocks = (
        len(findings) + FACT_BLOCK_SIZE - 1
    ) // FACT_BLOCK_SIZE

    all_rows = []
    block_confidences = []

    for start in range(0, len(findings), FACT_BLOCK_SIZE):
        block = findings[start:start + FACT_BLOCK_SIZE]
        block_number = (start // FACT_BLOCK_SIZE) + 1
        relevant_sources = relevant_sources_for_block(block, sources)

        log("")
        log(
            f"[FATO] Bloco {block_number}/{total_blocks} | "
            f"achados={len(block)} | "
            f"motores={', '.join(relevant_sources.keys())}"
        )

        prompt = build_fact_block_prompt(
            block,
            relevant_sources,
            block_number,
            total_blocks,
        )

        last_error = None

        for structural_attempt in range(
            1,
            BLOCK_STRUCTURAL_ATTEMPTS + 1,
        ):
            try:
                result = call_nemotron_json(
                    prompt,
                    MAX_TOKENS_FACT_BLOCK,
                    stage=(
                        f"Filtro factual bloco "
                        f"{block_number}/{total_blocks}"
                    ),
                    max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
                    retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
                )

                rows = validate_block_result(result, block)

                source_by_id = {
                    item["_finding_id"]: item
                    for item in block
                }

                for row in rows:
                    original = source_by_id[row["finding_id"]]

                    row["categoria_na_validacao_cruzada"] = (
                        original["_categoria_origem"]
                    )
                    row["achado_original"] = {
                        key: value
                        for key, value in original.items()
                        if not key.startswith("_")
                    }

                all_rows.extend(rows)

                confidence = result.get("confidence")
                if isinstance(confidence, (int, float)):
                    block_confidences.append(float(confidence))

                save_json(
                    OUTPUT_DIR
                    / f"robot_fact_filter_part_{block_number}.json",
                    {
                        "bloco": block_number,
                        "total_blocos": total_blocks,
                        "motores_enviados": list(
                            relevant_sources.keys()
                        ),
                        "confidence": result.get("confidence"),
                        "resultados": rows,
                    },
                )

                log(
                    f"[OK] Bloco factual {block_number}/{total_blocks} "
                    f"concluído e salvo."
                )

                last_error = None
                break

            except Exception as exc:
                last_error = exc

                log(
                    f"[FATO] Estrutura inválida no bloco "
                    f"{block_number}/{total_blocks}: "
                    f"{type(exc).__name__}: {exc}"
                )

                if structural_attempt < BLOCK_STRUCTURAL_ATTEMPTS:
                    log(
                        "[FATO] Reexecutando somente este bloco "
                        "para obter estrutura completa."
                    )

        if last_error is not None:
            raise RuntimeError(
                f"Bloco factual {block_number}/{total_blocks} "
                f"não pôde ser concluído: "
                f"{type(last_error).__name__}: {last_error}"
            )

    return all_rows, block_confidences


def severity_of(row):
    original = row.get("achado_original", {})

    for key in ("severidade", "impacto"):
        value = str(original.get(key, "")).upper()

        if value in {"CRITICA", "CRÍTICA"}:
            return 4
        if value == "ALTA":
            return 3
        if value == "MEDIA" or value == "MÉDIA":
            return 2
        if value == "BAIXA":
            return 1

    return 0


def consolidate_locally(rows, block_confidences):
    by_class = {
        classification: []
        for classification in FACT_CLASSES
    }

    for row in rows:
        by_class[row["classificacao_factual"]].append(row)

    confirmed = by_class["FATO_CONFIRMADO"]
    refuted = by_class["FATO_REFUTADO"]
    insufficient = by_class["EVIDENCIA_INSUFICIENTE"]
    methodological = by_class["ESCOLHA_METODOLOGICA"]
    potential = by_class["RISCO_POTENCIAL_NAO_COMPROVADO"]

    priority = sorted(
        confirmed,
        key=lambda row: (
            severity_of(row),
            float(row.get("confidence", 0) or 0),
        ),
        reverse=True,
    )

    if confirmed:
        verdict = "HA_FATOS_CONFIRMADOS"
    elif insufficient or potential:
        verdict = "EVIDENCIA_INSUFICIENTE"
    else:
        verdict = "SEM_ERROS_FACTUAIS_CONFIRMADOS"

    item_confidences = []

    for row in rows:
        value = row.get("confidence")
        if isinstance(value, (int, float)):
            item_confidences.append(float(value))

    if item_confidences:
        confidence = round(
            sum(item_confidences) / len(item_confidences)
        )
    elif block_confidences:
        confidence = round(
            sum(block_confidences) / len(block_confidences)
        )
    else:
        confidence = 0

    return {
        "veredito_factual": verdict,
        "confidence": confidence,
        "fatos_confirmados": confirmed,
        "fatos_refutados": refuted,
        "evidencia_insuficiente": insufficient,
        "escolhas_metodologicas": methodological,
        "riscos_potenciais_nao_comprovados": potential,
        "prioridade_fatos_confirmados": priority,
        "resumo_quantitativo": {
            "fatos_confirmados": len(confirmed),
            "fatos_refutados": len(refuted),
            "evidencia_insuficiente": len(insufficient),
            "escolhas_metodologicas": len(methodological),
            "riscos_potenciais_nao_comprovados": len(potential),
            "total_achados_julgados": len(rows),
        },
        "conclusao_factual": (
            "Consolidação determinística dos blocos factuais. "
            "Nenhuma nova inferência foi adicionada na consolidação."
        ),
        "metodo": {
            "execucao": "FILTRO_FACTUAL_EM_BLOCOS",
            "tamanho_bloco": FACT_BLOCK_SIZE,
            "consolidacao": "DETERMINISTICA_LOCAL",
            "modelo": MODEL,
        },
    }


def update_complete_report(fact_result):
    complete_path = OUTPUT_DIR / "robot_audit_complete.json"

    if not complete_path.is_file():
        log(
            "[AVISO] robot_audit_complete.json não encontrado. "
            "O filtro factual será salvo normalmente."
        )
        return

    complete = load_json(complete_path)

    complete["status"] = "CONCLUIDA"
    complete["filtro_factual"] = fact_result
    complete["filtro_factual_executado"] = True
    complete["erro_filtro_factual"] = None
    complete["filtro_factual_retomado_em_utc"] = utc_now()

    save_json(complete_path, complete)

    log(
        "[OK] robot_audit_complete.json atualizado para status CONCLUIDA."
    )


def cleanup_old_failure_markers():
    for filename in [
        "robot_fact_filter_failed.json",
        "robot_fact_filter_resume_failed.json",
    ]:
        path = OUTPUT_DIR / filename

        if path.exists():
            path.unlink()


def main():
    log("=" * 78)
    log("NEMOTRON — RETOMADA DO FILTRO FINAL DE FATO V2")
    log("=" * 78)

    if not os.getenv("NVIDIA_API_KEY"):
        raise RuntimeError(
            "NVIDIA_API_KEY não encontrada no ambiente."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cross_path = OUTPUT_DIR / "robot_cross_validation.json"

    log(f"[LOAD] Validação cruzada: {cross_path}")

    cross_result = load_json(cross_path)
    total_findings = validate_previous_audit(cross_result)

    log(
        "[OK] Validação cruzada anterior carregada | "
        f"veredito={cross_result.get('veredito_integrado')} | "
        f"score={cross_result.get('score_integrado')} | "
        f"confiança={cross_result.get('confidence')} | "
        f"achados={total_findings}"
    )

    sources = load_sources()

    log(
        f"[OK] Código dos motores carregado: "
        f"{len(sources)}/{len(MAIN_ENGINES)}"
    )

    findings = flatten_cross_findings(cross_result)

    total_blocks = (
        len(findings) + FACT_BLOCK_SIZE - 1
    ) // FACT_BLOCK_SIZE

    log(
        f"[OK] Filtro factual dividido em "
        f"{total_blocks} bloco(s) de até {FACT_BLOCK_SIZE} achados."
    )

    log("")
    log("=" * 78)
    log("PRECHECK — NVIDIA / NEMOTRON")
    log("=" * 78)

    precheck_nemotron()

    log("")
    log("=" * 78)
    log("EXECUTANDO SOMENTE O FILTRO FINAL DE FATO — EM BLOCOS")
    log("=" * 78)

    try:
        rows, block_confidences = run_fact_blocks(
            findings,
            sources,
        )

        if len(rows) != len(findings):
            raise RuntimeError(
                f"Consolidação bloqueada: {len(rows)} resultados "
                f"para {len(findings)} achados."
            )

        fact_result = consolidate_locally(
            rows,
            block_confidences,
        )

        save_json(
            OUTPUT_DIR / "robot_fact_filter.json",
            fact_result,
        )

        update_complete_report(fact_result)
        cleanup_old_failure_markers()

        summary = fact_result["resumo_quantitativo"]

        log("")
        log("=" * 78)
        log("FILTRO FACTUAL CONCLUÍDO")
        log("=" * 78)
        log(
            f"Veredito factual: "
            f"{fact_result['veredito_factual']}"
        )
        log(
            f"Confiança factual: "
            f"{fact_result['confidence']}"
        )
        log(
            f"Fatos confirmados: "
            f"{summary['fatos_confirmados']}"
        )
        log(
            f"Fatos refutados: "
            f"{summary['fatos_refutados']}"
        )
        log(
            f"Evidência insuficiente: "
            f"{summary['evidencia_insuficiente']}"
        )
        log(
            f"Escolhas metodológicas: "
            f"{summary['escolhas_metodologicas']}"
        )
        log(
            f"Riscos potenciais não comprovados: "
            f"{summary['riscos_potenciais_nao_comprovados']}"
        )
        log(
            f"Total julgado: "
            f"{summary['total_achados_julgados']}"
        )
        log(
            f"Resultado: "
            f"{OUTPUT_DIR / 'robot_fact_filter.json'}"
        )
        log("=" * 78)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

        save_json(
            OUTPUT_DIR / "robot_fact_filter_resume_failed.json",
            {
                "timestamp_utc": utc_now(),
                "model": MODEL,
                "status": "FILTRO_FACTUAL_RETOMADA_V2_FALHOU",
                "erro": error,
                "validacao_cruzada_preservada": True,
                "arquivo_validacao_cruzada": str(cross_path),
                "modo": "BLOCOS",
                "tamanho_bloco": FACT_BLOCK_SIZE,
            },
        )

        log("")
        log("=" * 78)
        log("RETOMADA DO FILTRO FACTUAL V2 FALHOU")
        log("=" * 78)
        log(error)
        log(
            "Nenhuma auditoria individual nem validação cruzada "
            "foi refeita."
        )
        log("=" * 78)

        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log("")
        log("=" * 78)
        log("EXECUÇÃO ENCERRADA COM FALHA")
        log("=" * 78)
        log(f"{type(exc).__name__}: {exc}")
        log("=" * 78)
        sys.exit(1)
