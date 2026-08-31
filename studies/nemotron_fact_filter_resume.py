import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

# Reutiliza exatamente a lógica já validada do auditor principal.
from nemotron_robot_auditor import (
    MAIN_ENGINES,
    MODEL,
    OUTPUT_DIR,
    SRC_DIR,
    fact_filter,
    precheck_nemotron,
    save_json,
)


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

    missing = [
        field
        for field in required
        if field not in cross_result
    ]

    if missing:
        raise RuntimeError(
            "Validação cruzada anterior incompleta. Campos ausentes: "
            + ", ".join(missing)
        )


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


def main():
    log("=" * 78)
    log("NEMOTRON — RETOMADA DO FILTRO FINAL DE FATO")
    log("=" * 78)

    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY não encontrada no ambiente."
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    cross_path = OUTPUT_DIR / "robot_cross_validation.json"

    log(f"[LOAD] Validação cruzada: {cross_path}")
    cross_result = load_json(cross_path)
    validate_previous_audit(cross_result)

    log(
        "[OK] Validação cruzada anterior carregada | "
        f"veredito={cross_result.get('veredito_integrado')} | "
        f"score={cross_result.get('score_integrado')} | "
        f"confiança={cross_result.get('confidence')}"
    )

    sources = load_sources()
    log(f"[OK] Código dos motores carregado: {len(sources)}/{len(MAIN_ENGINES)}")

    log("")
    log("=" * 78)
    log("PRECHECK — NVIDIA / NEMOTRON")
    log("=" * 78)

    precheck_nemotron()

    log("")
    log("=" * 78)
    log("EXECUTANDO SOMENTE O FILTRO FINAL DE FATO")
    log("=" * 78)

    try:
        fact_result = fact_filter(
            cross_result,
            sources,
        )

        save_json(
            OUTPUT_DIR / "robot_fact_filter.json",
            fact_result,
        )

        update_complete_report(fact_result)

        failed_marker = OUTPUT_DIR / "robot_fact_filter_failed.json"
        if failed_marker.exists():
            failed_marker.unlink()

        log("")
        log("=" * 78)
        log("FILTRO FACTUAL CONCLUÍDO")
        log("=" * 78)

        summary = fact_result.get("resumo_quantitativo", {})

        log(
            f"Veredito factual: "
            f"{fact_result.get('veredito_factual', 'N/D')}"
        )
        log(
            f"Confiança factual: "
            f"{fact_result.get('confidence', 'N/D')}"
        )
        log(
            f"Fatos confirmados: "
            f"{summary.get('fatos_confirmados', 0)}"
        )
        log(
            f"Fatos refutados: "
            f"{summary.get('fatos_refutados', 0)}"
        )
        log(
            f"Evidência insuficiente: "
            f"{summary.get('evidencia_insuficiente', 0)}"
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
                "status": "FILTRO_FACTUAL_RETOMADA_FALHOU",
                "erro": error,
                "validacao_cruzada_preservada": True,
                "arquivo_validacao_cruzada": str(cross_path),
            },
        )

        log("")
        log("=" * 78)
        log("RETOMADA DO FILTRO FACTUAL FALHOU")
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
