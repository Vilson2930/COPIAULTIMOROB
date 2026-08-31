946
947
948
949
950
951
952
953
954
955
956
957
958
959
960
961
962
963
964
965
966
967
968
969
970
971
972
973
974
975
976
977
978
979
980
981
982
983
984
985
986
987
988
989
990
991
992
993
994
995
996
997
998
999
1000
1001
1002
1003
1004
1005
1006
1007
1008
1009
1010
1011
1012
1013
import json

    save_json(
        OUTPUT_DIR / "robot_fact_filter.json",
        fact_result,
    )
    log("[OK] Filtro final de fato concluído e salvo.")

    complete_report = {
        "timestamp_utc": utc_now(),
        "model": MODEL,
        "motores_planejados": MAIN_ENGINES,
        "motores_auditados": [result.get("arquivo") for result in results],
        "falhas_execucao": failures,
        "auditorias_individuais": results,
        "validacao_cruzada": cross_result,
        "validacoes_cruzadas_parciais": [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(OUTPUT_DIR.glob("robot_cross_validation_part_*.json"))
        ],
        "filtro_factual": fact_result,
    }

    save_json(
        OUTPUT_DIR / "robot_audit_complete.json",
        complete_report,
    )

    markdown = create_markdown(results, cross_result, fact_result, failures)
    (OUTPUT_DIR / "robot_audit_report.md").write_text(
        markdown,
        encoding="utf-8",
    )

    log("\n" + "=" * 78)
    log("AUDITORIA CONCLUÍDA")
    log("=" * 78)
    summary = fact_result.get("resumo_quantitativo", {})

    log(f"Veredito integrado: {cross_result.get('veredito_integrado', 'N/D')}")
    log(f"Score integrado: {cross_result.get('score_integrado', 'N/D')}")
    log(f"Confiança integração: {cross_result.get('confidence', 'N/D')}")
    log(f"Veredito factual: {fact_result.get('veredito_factual', 'N/D')}")
    log(f"Confiança factual: {fact_result.get('confidence', 'N/D')}")
    log(f"Fatos confirmados: {summary.get('fatos_confirmados', 0)}")
    log(f"Fatos refutados: {summary.get('fatos_refutados', 0)}")
    log(f"Evidência insuficiente: {summary.get('evidencia_insuficiente', 0)}")
    log(f"Motores auditados: {len(results)}")
    log(f"Falhas de execução: {len(failures)}")
    log(f"Relatório completo: {OUTPUT_DIR / 'robot_audit_complete.json'}")
    log(f"Filtro factual: {OUTPUT_DIR / 'robot_fact_filter.json'}")
    log(f"Relatório leitura: {OUTPUT_DIR / 'robot_audit_report.md'}")
    log("=" * 78)


def main():
    try:
        run()
    except Exception as exc:
        log("\n" + "=" * 78)
        log("AUDITORIA FALHOU")
        log("=" * 78)
        log(f"{type(exc).__name__}: {exc}")
        log("=" * 78)
        sys.exit(1)


if __name__ == "__main__":
    main()
