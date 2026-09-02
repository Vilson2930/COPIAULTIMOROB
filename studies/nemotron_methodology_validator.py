import json
import re
from pathlib import Path
from datetime import datetime, timezone

from nemotron_robot_auditor import (
    MAIN_ENGINES,
    OUTPUT_DIR,
    SRC_DIR,
    FINAL_STAGE_MAX_ATTEMPTS,
    FINAL_STAGE_RETRY_WAIT_SECONDS,
    call_nemotron_json,
    precheck_nemotron,
    save_json,
)

INPUT_QUEUE = OUTPUT_DIR / "robot_correction_queue.json"
POLICY_PATH = Path("config/audit_policy.json")

FINAL_BLOCK_SIZE = 3
MAX_TOKENS_FINAL_BLOCK = 6500
MAX_TOKENS_FINAL_VERIFY = 5000
STRUCTURAL_ATTEMPTS = 2

FINAL_CLASSES = {
    "CORRIGIR",
    "MANTER",
    "MELHORAR_ROBUSTEZ",
}

CLASS_ALIASES = {
    "BUG_REAL": "CORRIGIR",
    "CORRECAO": "CORRIGIR",
    "CORREÇÃO": "CORRIGIR",
    "NAO_CORRIGIR": "MANTER",
    "NÃO_CORRIGIR": "MANTER",
    "NAO_CORRIGIR_AGORA": "MANTER",
    "NÃO_CORRIGIR_AGORA": "MANTER",
    "REGRA_INTENCIONAL": "MANTER",
    "QUESTAO_METODOLOGICA": "MANTER",
    "QUESTÃO_METODOLÓGICA": "MANTER",
    "FRAGILIDADE_FUTURA": "MELHORAR_ROBUSTEZ",
    "NAO_APLICAVEL_NO_PIPELINE_ATUAL": "MELHORAR_ROBUSTEZ",
    "NÃO_APLICÁVEL_NO_PIPELINE_ATUAL": "MELHORAR_ROBUSTEZ",
}


def log(message=""):
    print(message, flush=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def load_json(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Arquivo obrigatório não encontrado: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_class(value):
    raw = str(value or "").strip().upper()
    if raw in FINAL_CLASSES:
        return raw
    return CLASS_ALIASES.get(raw, raw)


def numbered_text(text):
    return "\n".join(
        f"{idx:04d}: {line}"
        for idx, line in enumerate(text.splitlines(), start=1)
    )


def load_policy():
    if POLICY_PATH.is_file():
        return load_json(POLICY_PATH)

    return {
        "principles": [
            "FATO_CONFIRMADO não significa BUG.",
            "Somente corrigir erro objetivo de cálculo, contrato, integração ou regra contrária à metodologia.",
            "Risco alto, concentração alta e contribuição alta de BTC são diagnósticos, não bugs por si só.",
            "Fail-safe documentado pode ser regra intencional.",
            "Não alterar pesos da carteira como correção de software.",
            "Não alterar código automaticamente.",
            "Não gerar nem executar testes automaticamente.",
        ]
    }


def load_sources():
    sources = {}

    for filename in MAIN_ENGINES:
        path = SRC_DIR / filename
        if not path.is_file():
            raise RuntimeError(f"Motor obrigatório ausente: {path}")
        sources[filename] = numbered_text(
            path.read_text(encoding="utf-8", errors="replace")
        )

    main_path = Path("main.py")
    if main_path.is_file():
        sources["main.py"] = numbered_text(
            main_path.read_text(encoding="utf-8", errors="replace")
        )

    return sources


def load_candidates():
    queue = load_json(INPUT_QUEUE)
    rows = queue.get("bugs_reais_confirmados", [])

    if not isinstance(rows, list) or not rows:
        raise RuntimeError(
            "robot_correction_queue.json não possui bugs_reais_confirmados."
        )

    seen = set()
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        fid = str(row.get("finding_id", "")).strip()
        if not fid:
            raise RuntimeError("Candidato sem finding_id.")
        if fid in seen:
            raise RuntimeError(f"finding_id duplicado: {fid}")
        seen.add(fid)
        clean.append(row)

    return sorted(
        clean,
        key=lambda x: int(re.sub(r"\D", "", x["finding_id"]) or 0),
    )


def select_sources(row, all_sources):
    names = []

    principal = row.get("motor_principal")
    if principal in all_sources:
        names.append(principal)

    for name in row.get("motores_relacionados", []) or []:
        if name in all_sources and name not in names:
            names.append(name)

    text = json.dumps(row, ensure_ascii=False).lower()
    for filename in MAIN_ENGINES:
        if filename.lower() in text and filename in all_sources and filename not in names:
            names.append(filename)

    if "governance_engine.py" in all_sources and "governance_engine.py" not in names:
        names.append("governance_engine.py")

    if "main.py" in all_sources and "main.py" not in names:
        names.append("main.py")

    return {
        name: all_sources[name]
        for name in names[:8]
    }


def sources_for_block(block, all_sources):
    selected = {}
    for row in block:
        for name, source in select_sources(row, all_sources).items():
            if name not in selected:
                selected[name] = source
    return dict(list(selected.items())[:9])


def expected_schema(block):
    return {
        "confidence": 0,
        "resultados": [
            {
                "finding_id": row["finding_id"],
                "classificacao_final_metodologia": "CORRIGIR",
                "prioridade_final": "ALTA",
                "regra_metodologica_aplicada": "curto",
                "comportamento_atual": "curto",
                "comportamento_esperado_pela_metodologia": "curto",
                "divergencia_objetiva": "curto",
                "impacto_real": "curto",
                "motivo_final": "curto",
                "confidence": 0,
            }
            for row in block
        ],
    }


def build_prompt(block, sources, policy, block_number, total_blocks):
    compact = []
    for row in block:
        compact.append({
            "finding_id": row.get("finding_id"),
            "prioridade_anterior": row.get("prioridade"),
            "motor_principal": row.get("motor_principal"),
            "motores_relacionados": row.get("motores_relacionados"),
            "funcao_ou_bloco": row.get("funcao_ou_bloco"),
            "linhas_relevantes": row.get("linhas_relevantes"),
            "comportamento_observado": row.get("comportamento_observado"),
            "comportamento_esperado": row.get("comportamento_esperado"),
            "prova_integracao": row.get("prova_integracao"),
            "por_que_e_ou_nao_e_bug": row.get("por_que_e_ou_nao_e_bug"),
            "impacto_real": row.get("impacto_real"),
            "confidence_anterior": row.get("confidence"),
            "verificacao_final_bug": row.get("verificacao_final_bug"),
        })

    return f"""
Você é a QUINTA E ÚLTIMA CAMADA de auditoria de um robô financeiro.

As camadas anteriores já classificaram estes itens como BUG_REAL.
Sua obrigação agora NÃO é aceitar essa classificação.
Sua obrigação é confrontar cada candidato com a METODOLOGIA DEFINIDA
do robô e com o CÓDIGO ATUAL, e decidir a ação correta.

CLASSIFICAÇÕES FINAIS PERMITIDAS:
- CORRIGIR
- MANTER
- MELHORAR_ROBUSTEZ

DEFINIÇÕES:
CORRIGIR:
  erro matemático/lógico atual, dado relevante ignorado, contrato quebrado,
  integração incorreta, regra executada de modo diferente da metodologia,
  ou saída objetivamente inconsistente com a metodologia definida.

MANTER:
  comportamento intencional, fail-safe, diagnóstico correto, escolha
  metodológica válida ou alerta severo que está refletindo corretamente
  o risco do portfólio.

MELHORAR_ROBUSTEZ:
  comportamento que funciona corretamente no universo/pipeline atual,
  mas pode falhar com novos ativos, dados ausentes, novas integrações
  ou mudanças futuras de contrato.

PORTÃO OBRIGATÓRIO PARA "CORRIGIR":
Você só pode classificar CORRIGIR se conseguir demonstrar explicitamente:

REGRA PRETENDIDA
-> CÓDIGO ATUAL
-> COMPORTAMENTO PRODUZIDO
-> DIVERGÊNCIA OBJETIVA
-> IMPACTO REAL.

Se qualquer elo não fechar, NÃO classifique CORRIGIR.

REGRAS DE PROTEÇÃO DA METODOLOGIA:
- peso alto, concentração alta ou contribuição de risco alta NÃO são bugs
  por si só;
- risco elevado do BTC é um diagnóstico válido quando a matemática está certa;
- não reduza risco, concentração ou score severo apenas para "melhorar" o resultado;
- pesos-alvo configurados são decisões deliberadas e não devem ser alterados;
- limites genéricos não anulam pesos-alvo deliberados salvo se estiverem
  definidos como invariantes obrigatórias da própria metodologia;
- fail-safe documentado é MANTER, salvo contradição objetiva com regra superior;
- janelas, thresholds, haircuts e convenções são MANTER quando forem escolhas
  metodológicas sem prova objetiva de erro;
- problema apenas futuro é MELHORAR_ROBUSTEZ;
- não altere código;
- não gere nem execute testes;
- não proponha mudança dos pesos da carteira.

Bloco {block_number}/{total_blocks}.

POLÍTICA DO ROBÔ:
{json.dumps(policy, ensure_ascii=False, indent=2)}

CANDIDATOS A CORREÇÃO:
{json.dumps(compact, ensure_ascii=False, indent=2)}

CÓDIGO ATUAL COM NÚMEROS DE LINHA:
{json.dumps(sources, ensure_ascii=False, indent=2)}

Retorne SOMENTE JSON válido exatamente nesta estrutura:
{json.dumps(expected_schema(block), ensure_ascii=False, indent=2)}
""".strip()


def validate_block(result, block):
    if not isinstance(result, dict):
        raise ValueError("Resposta não é objeto JSON.")

    rows = result.get("resultados")
    if not isinstance(rows, list):
        raise ValueError("Campo resultados ausente ou inválido.")

    expected = {row["finding_id"] for row in block}
    received = []

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Resultado individual inválido.")

        fid = row.get("finding_id")
        cls = normalize_class(row.get("classificacao_final_metodologia"))
        row["classificacao_final_metodologia"] = cls

        if fid not in expected:
            raise ValueError(f"finding_id inesperado: {fid}")

        if cls not in FINAL_CLASSES:
            raise ValueError(
                f"Classificação final inválida em {fid}: {cls}"
            )

        if cls == "CORRIGIR":
            required = [
                "regra_metodologica_aplicada",
                "comportamento_atual",
                "comportamento_esperado_pela_metodologia",
                "divergencia_objetiva",
                "impacto_real",
                "motivo_final",
            ]
            missing = [
                field for field in required
                if not str(row.get(field, "")).strip()
            ]
            if missing:
                raise ValueError(
                    f"CORRIGIR sem prova completa em {fid}: {missing}"
                )

        received.append(fid)

    if set(received) != expected or len(received) != len(expected):
        raise ValueError(
            "Resposta não contém exatamente todos os finding_id do bloco."
        )

    return rows


def run_blocks(candidates, sources, policy):
    total_blocks = (
        len(candidates) + FINAL_BLOCK_SIZE - 1
    ) // FINAL_BLOCK_SIZE

    all_rows = []
    block_confidences = []

    for start in range(0, len(candidates), FINAL_BLOCK_SIZE):
        block = candidates[start:start + FINAL_BLOCK_SIZE]
        block_number = start // FINAL_BLOCK_SIZE + 1
        relevant = sources_for_block(block, sources)

        log("")
        log(
            f"[METODOLOGIA] Bloco {block_number}/{total_blocks} | "
            f"achados={len(block)} | fontes={', '.join(relevant.keys())}"
        )

        prompt = build_prompt(
            block, relevant, policy, block_number, total_blocks
        )

        last_error = None
        for structural_attempt in range(1, STRUCTURAL_ATTEMPTS + 1):
            try:
                result = call_nemotron_json(
                    prompt,
                    MAX_TOKENS_FINAL_BLOCK,
                    stage=(
                        f"Validação metodológica bloco "
                        f"{block_number}/{total_blocks}"
                    ),
                    max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
                    retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
                )

                rows = validate_block(result, block)
                original_by_id = {
                    row["finding_id"]: row
                    for row in block
                }

                for row in rows:
                    original = original_by_id[row["finding_id"]]
                    row["candidato_anterior"] = original

                all_rows.extend(rows)

                confidence = result.get("confidence")
                if isinstance(confidence, (int, float)):
                    block_confidences.append(float(confidence))

                save_json(
                    OUTPUT_DIR
                    / f"robot_methodology_validation_part_{block_number}.json",
                    {
                        "bloco": block_number,
                        "total_blocos": total_blocks,
                        "fontes": list(relevant.keys()),
                        "confidence": result.get("confidence"),
                        "resultados": rows,
                    },
                )

                log(
                    f"[OK] Bloco metodológico "
                    f"{block_number}/{total_blocks} concluído."
                )
                last_error = None
                break

            except Exception as exc:
                last_error = exc
                log(
                    f"[METODOLOGIA] Estrutura inválida no bloco "
                    f"{block_number}/{total_blocks}: "
                    f"{type(exc).__name__}: {exc}"
                )
                if structural_attempt < STRUCTURAL_ATTEMPTS:
                    log("[METODOLOGIA] Reexecutando somente este bloco.")

        if last_error is not None:
            raise RuntimeError(
                f"Bloco metodológico {block_number}/{total_blocks} falhou: "
                f"{type(last_error).__name__}: {last_error}"
            )

    return all_rows, block_confidences


def verify_schema(row):
    return {
        "finding_id": row["finding_id"],
        "verificacao_final": "CONFIRMADO",
        "classificacao_final_metodologia": "CORRIGIR",
        "regra_metodologica_aplicada": "curto",
        "prova_final": {
            "codigo_atual": "curto",
            "comportamento_produzido": "curto",
            "comportamento_exigido": "curto",
            "divergencia_objetiva": "curto",
            "impacto_real": "curto",
        },
        "motivo_final": "curto",
        "confidence": 0,
    }


def build_verify_prompt(row, sources, policy):
    original = row.get("candidato_anterior", {})
    relevant = select_sources(original, sources)

    return f"""
Você é o REVISOR ADVERSARIAL FINAL da quinta camada.

Outro julgador concluiu que este item deve ser CORRIGIDO.
Tente REFUTAR essa conclusão usando a metodologia definida e o código atual.

Só mantenha CORRIGIR quando houver prova fechada de:
regra metodológica pretendida
-> código atual
-> comportamento produzido
-> divergência objetiva
-> impacto real atual.

Se for comportamento intencional, diagnóstico correto, fail-safe ou escolha
metodológica, rebaixe para MANTER.

Se funcionar corretamente hoje e o problema for apenas de extensibilidade,
novo ativo, dado futuro ou contrato futuro, rebaixe para MELHORAR_ROBUSTEZ.

Nunca mantenha CORRIGIR apenas porque:
- BTC tem risco/concentração/contribuição alta;
- um score ficou crítico;
- um alerta ficou severo;
- o modelo prefere outro threshold/janela;
- existe um limite genérico que conflita com peso-alvo deliberado sem que
  esse limite seja um hard invariant comprovado.

Não altere código. Não gere testes. Não altere pesos da carteira.

POLÍTICA:
{json.dumps(policy, ensure_ascii=False, indent=2)}

DECISÃO A SER CONTESTADA:
{json.dumps(row, ensure_ascii=False, indent=2)}

CÓDIGO ATUAL:
{json.dumps(relevant, ensure_ascii=False, indent=2)}

Retorne SOMENTE JSON válido:
{json.dumps(verify_schema(row), ensure_ascii=False, indent=2)}
""".strip()


def adversarial_verify(rows, sources, policy):
    final_rows = []

    for row in rows:
        if row["classificacao_final_metodologia"] != "CORRIGIR":
            row["segunda_revisao_metodologica"] = "NAO_NECESSARIA"
            final_rows.append(row)
            continue

        fid = row["finding_id"]
        log(f"[METODOLOGIA-CHECK] Segunda revisão de {fid}")

        result = call_nemotron_json(
            build_verify_prompt(row, sources, policy),
            MAX_TOKENS_FINAL_VERIFY,
            stage=f"Revisão metodológica final {fid}",
            max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
            retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
        )

        if not isinstance(result, dict):
            raise ValueError(f"Revisão metodológica inválida em {fid}")

        if result.get("finding_id") != fid:
            raise ValueError(f"finding_id divergente em {fid}")

        cls = normalize_class(
            result.get("classificacao_final_metodologia")
        )
        result["classificacao_final_metodologia"] = cls

        if cls not in FINAL_CLASSES:
            raise ValueError(
                f"Classificação da revisão inválida em {fid}: {cls}"
            )

        check = str(result.get("verificacao_final", "")).strip().upper()

        if cls == "CORRIGIR":
            if check not in {"CONFIRMADO", "CONFIRMADO_COM_PROVA"}:
                raise ValueError(
                    f"CORRIGIR sem confirmação final em {fid}: {check}"
                )
            row["segunda_revisao_metodologica"] = "CONFIRMADO_COM_PROVA"
            row["verificacao_metodologica_final"] = result
        else:
            row["segunda_revisao_metodologica"] = "REBAIXADO"
            row["classificacao_inicial_metodologia"] = "CORRIGIR"
            row["classificacao_final_metodologia"] = cls
            row["motivo_rebaixamento_metodologico"] = result.get(
                "motivo_final"
            )
            row["verificacao_metodologica_final"] = result

        final_rows.append(row)

    return final_rows


def confidence_of(rows, block_confidences):
    values = []
    for row in rows:
        verification = row.get("verificacao_metodologica_final")
        if isinstance(verification, dict):
            value = verification.get("confidence")
            if isinstance(value, (int, float)):
                values.append(float(value))
                continue

        value = row.get("confidence")
        if isinstance(value, (int, float)):
            values.append(float(value))

    if values:
        return round(sum(values) / len(values))

    if block_confidences:
        return round(sum(block_confidences) / len(block_confidences))

    return 0


def priority_rank(value):
    return {
        "CRITICA": 4,
        "CRÍTICA": 4,
        "ALTA": 3,
        "MEDIA": 2,
        "MÉDIA": 2,
        "BAIXA": 1,
    }.get(str(value or "").upper(), 0)


def consolidate(rows, block_confidences):
    groups = {cls: [] for cls in FINAL_CLASSES}

    for row in rows:
        groups[row["classificacao_final_metodologia"]].append(row)

    for cls in groups:
        groups[cls].sort(
            key=lambda r: (
                -priority_rank(
                    r.get("prioridade_final")
                    or r.get("candidato_anterior", {}).get("prioridade")
                ),
                int(re.sub(r"\D", "", r["finding_id"]) or 0),
            )
        )

    corrigir = groups["CORRIGIR"]
    manter = groups["MANTER"]
    robustez = groups["MELHORAR_ROBUSTEZ"]

    verdict = (
        "HA_CORRECOES_REAIS"
        if corrigir
        else "SEM_CORRECOES_OBRIGATORIAS"
    )

    return {
        "timestamp_utc": utc_now(),
        "veredito_final_metodologia": verdict,
        "confidence": confidence_of(rows, block_confidences),
        "corrigir": corrigir,
        "manter": manter,
        "melhorar_robustez": robustez,
        "resumo_quantitativo": {
            "total_avaliado": len(rows),
            "corrigir": len(corrigir),
            "manter": len(manter),
            "melhorar_robustez": len(robustez),
        },
        "metodo": {
            "entrada": str(INPUT_QUEUE),
            "policy": str(POLICY_PATH),
            "segunda_revisao_adversarial_para_corrigir": True,
            "codigo_alterado": False,
            "testes_gerados_ou_executados": False,
            "regra": (
                "CORRIGIR somente quando a metodologia definida, o código "
                "atual, a divergência objetiva e o impacto real fecham a "
                "cadeia de prova."
            ),
        },
    }


def write_report(result):
    summary = result["resumo_quantitativo"]
    lines = [
        "# Validação Final Contra a Metodologia",
        "",
        f"**Veredito:** {result['veredito_final_metodologia']}",
        f"**Confiança:** {result['confidence']}%",
        "",
        "## Resumo",
        "",
        f"- Total avaliado: {summary['total_avaliado']}",
        f"- CORRIGIR: {summary['corrigir']}",
        f"- MANTER: {summary['manter']}",
        f"- MELHORAR_ROBUSTEZ: {summary['melhorar_robustez']}",
        "",
    ]

    for title, key in [
        ("Correções obrigatórias", "corrigir"),
        ("Manter como está", "manter"),
        ("Melhorias de robustez", "melhorar_robustez"),
    ]:
        lines.append(f"## {title}")
        lines.append("")

        rows = result[key]
        if not rows:
            lines.append("_Nenhum item._")
            lines.append("")
            continue

        for row in rows:
            prior = (
                row.get("prioridade_final")
                or row.get("candidato_anterior", {}).get("prioridade")
                or "N/D"
            )
            motor = (
                row.get("candidato_anterior", {}).get("motor_principal")
                or "N/D"
            )
            lines.append(
                f"### {row['finding_id']} — {motor} — prioridade {prior}"
            )
            lines.append("")
            lines.append(
                str(row.get("motivo_final") or "Sem justificativa.")
            )
            lines.append("")

    path = OUTPUT_DIR / "robot_final_corrections_report.md"
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    log("=" * 78)
    log("NEMOTRON — VALIDAÇÃO FINAL CONTRA A METODOLOGIA")
    log("=" * 78)

    candidates = load_candidates()
    policy = load_policy()
    sources = load_sources()

    log(
        f"[LOAD] Candidatos: {len(candidates)} | "
        f"motores: {len(MAIN_ENGINES)} | "
        f"orquestrador={'SIM' if 'main.py' in sources else 'NAO'}"
    )

    precheck_nemotron()

    rows, block_confidences = run_blocks(
        candidates,
        sources,
        policy,
    )

    rows = adversarial_verify(
        rows,
        sources,
        policy,
    )

    result = consolidate(rows, block_confidences)

    save_json(
        OUTPUT_DIR / "robot_final_corrections.json",
        result,
    )

    write_report(result)

    summary = result["resumo_quantitativo"]

    log("")
    log("=" * 78)
    log("VALIDAÇÃO METODOLÓGICA FINAL CONCLUÍDA")
    log("=" * 78)
    log(f"Veredito: {result['veredito_final_metodologia']}")
    log(f"Confiança: {result['confidence']}")
    log(f"CORRIGIR: {summary['corrigir']}")
    log(f"MANTER: {summary['manter']}")
    log(f"MELHORAR_ROBUSTEZ: {summary['melhorar_robustez']}")
    log(
        "Resultado: "
        f"{OUTPUT_DIR / 'robot_final_corrections.json'}"
    )
    log("=" * 78)


if __name__ == "__main__":
    main()
