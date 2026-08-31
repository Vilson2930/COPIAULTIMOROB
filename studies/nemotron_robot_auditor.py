import json
import os
import sys
import time
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
MAX_TOKENS_FACT = 10000

# Proteção operacional das chamadas à NVIDIA.
# Cada tentativa tem no máximo 5 minutos e há apenas 1 nova tentativa.
REQUEST_TIMEOUT_SECONDS = 300
MAX_API_ATTEMPTS = 2
RETRY_WAIT_SECONDS = 5

# Precheck: valida o endpoint antes de iniciar os 10 motores.
PRECHECK_TIMEOUT_SECONDS = 30
PRECHECK_MAX_ATTEMPTS = 2
PRECHECK_RETRY_WAIT_SECONDS = 5

# Se o Nemotron responder com JSON malformado, tenta corrigir somente a sintaxe uma vez.
JSON_REPAIR_MAX_ATTEMPTS = 1

# Validação cruzada em blocos menores para evitar respostas JSON excessivamente grandes.
CROSS_GROUP_SIZE = 5
MAX_TOKENS_CROSS_PART = 7000
MAX_TOKENS_CROSS_CONSOLIDATION = 7000

# Etapas finais são mais caras; usam mais tentativas e backoff progressivo.
FINAL_STAGE_MAX_ATTEMPTS = 4
FINAL_STAGE_RETRY_WAIT_SECONDS = 20


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def log(message=""):
    """Imprime imediatamente no GitHub Actions, sem buffering."""
    print(message, flush=True)


def get_client():
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY não encontrada.")

    return OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    )


def precheck_nemotron():
    """
    Testa a disponibilidade real do Nemotron antes da auditoria.
    Não audita código e não altera nenhuma das três camadas.
    """
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        raise RuntimeError("NVIDIA_API_KEY não encontrada.")

    log("=" * 78)
    log("PRECHECK — NVIDIA / NEMOTRON")
    log("=" * 78)

    last_error = None

    for attempt in range(1, PRECHECK_MAX_ATTEMPTS + 1):
        started = time.monotonic()
        log(
            f"[PRECHECK] Tentativa {attempt}/{PRECHECK_MAX_ATTEMPTS} "
            f"(timeout {PRECHECK_TIMEOUT_SECONDS}s)"
        )

        try:
            client = OpenAI(
                api_key=api_key,
                base_url=BASE_URL,
                timeout=PRECHECK_TIMEOUT_SECONDS,
                max_retries=0,
            )

            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {
                        "role": "user",
                        "content": "Responda somente com a palavra OK.",
                    }
                ],
                temperature=0,
                max_tokens=8,
                extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            )

            content = (response.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("Nemotron retornou resposta vazia no precheck.")

            elapsed = time.monotonic() - started
            log(
                f"[PRECHECK] Nemotron disponível — resposta recebida "
                f"em {elapsed:.1f}s."
            )
            log("=" * 78)
            return True

        except Exception as exc:
            elapsed = time.monotonic() - started
            last_error = exc
            log(
                f"[PRECHECK] Falha após {elapsed:.1f}s: "
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < PRECHECK_MAX_ATTEMPTS:
                log(
                    f"[PRECHECK] Nova tentativa em "
                    f"{PRECHECK_RETRY_WAIT_SECONDS}s."
                )
                time.sleep(PRECHECK_RETRY_WAIT_SECONDS)

    log("=" * 78)
    raise RuntimeError(
        "PRECHECK FALHOU — NVIDIA/Nemotron indisponível. "
        "A auditoria dos motores não foi iniciada. "
        f"Último erro: {type(last_error).__name__}: {last_error}"
    )


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


def call_nemotron(
    prompt,
    max_tokens,
    stage="Nemotron",
    json_mode=False,
    max_attempts=None,
    retry_wait_seconds=None,
):
    """
    Faz uma chamada protegida ao endpoint NVIDIA.

    - timeout por tentativa;
    - sem retries ocultos do SDK;
    - 1 retry controlado;
    - logs imediatos com duração de cada tentativa;
    - quando json_mode=True, solicita Structured JSON Output à API.
    """
    last_error = None
    attempts = max_attempts or MAX_API_ATTEMPTS
    retry_wait = RETRY_WAIT_SECONDS if retry_wait_seconds is None else retry_wait_seconds

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        log(
            f"[API] {stage} — tentativa {attempt}/{attempts} "
            f"(timeout {REQUEST_TIMEOUT_SECONDS}s)"
        )

        try:
            client = get_client()
            request_kwargs = {
                "model": MODEL,
                "messages": [
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
                "temperature": 0.1,
                "max_tokens": max_tokens,
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": False
                    }
                },
            }

            if json_mode:
                request_kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(**request_kwargs)

            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("Nemotron retornou resposta vazia.")

            elapsed = time.monotonic() - started
            log(f"[API] {stage} — resposta recebida em {elapsed:.1f}s")
            return content.strip()

        except Exception as exc:
            elapsed = time.monotonic() - started
            last_error = exc
            log(
                f"[API] {stage} — falha após {elapsed:.1f}s: "
                f"{type(exc).__name__}: {exc}"
            )

            if attempt < attempts:
                wait_now = retry_wait * attempt
                log(f"[API] {stage} — nova tentativa em {wait_now}s")
                time.sleep(wait_now)

    raise RuntimeError(
        f"{stage} falhou após {attempts} tentativas: "
        f"{type(last_error).__name__}: {last_error}"
    )


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


def repair_json_with_nemotron(
    raw_text,
    stage="JSON",
    max_attempts=None,
    retry_wait_seconds=None,
):
    """
    Pede ao Nemotron para corrigir SOMENTE a sintaxe de uma resposta JSON inválida.
    Não refaz a auditoria e não permite alterar o conteúdo substantivo.
    """
    repair_prompt = f"""
CORREÇÃO ESTRITA DE JSON

A resposta abaixo deveria ser JSON válido, mas contém erro de sintaxe.

REGRAS OBRIGATÓRIAS:
- corrija SOMENTE a sintaxe JSON;
- preserve integralmente o conteúdo, valores, conclusões, listas e classificações;
- não reanalise o código;
- não acrescente achados;
- não remova achados;
- não mude scores;
- não mude vereditos;
- não explique nada;
- retorne SOMENTE o JSON corrigido.

RESPOSTA INVÁLIDA:

{raw_text}
""".strip()

    log(f"[JSON] {stage} — resposta inválida; solicitando correção sintática.")

    repaired_text = call_nemotron(
        repair_prompt,
        max_tokens=max(
            MAX_TOKENS_INDIVIDUAL,
            MAX_TOKENS_CROSS,
            MAX_TOKENS_FACT,
        ),
        stage=f"Reparo JSON: {stage}",
        json_mode=True,
        max_attempts=max_attempts,
        retry_wait_seconds=retry_wait_seconds,
    )

    repaired = extract_json(repaired_text)
    log(f"[JSON] {stage} — JSON corrigido com sucesso.")
    return repaired


def call_nemotron_json(
    prompt,
    max_tokens,
    stage="Nemotron",
    max_attempts=None,
    retry_wait_seconds=None,
):
    """
    Executa a chamada normal e valida o JSON.
    Se a resposta estiver malformada, faz uma única tentativa de reparo sintático.
    """
    raw_text = call_nemotron(
        prompt,
        max_tokens,
        stage=stage,
        json_mode=True,
        max_attempts=max_attempts,
        retry_wait_seconds=retry_wait_seconds,
    )

    try:
        return extract_json(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        log(
            f"[JSON] {stage} — JSON inválido: "
            f"{type(exc).__name__}: {exc}"
        )

        last_error = exc
        for attempt in range(1, JSON_REPAIR_MAX_ATTEMPTS + 1):
            try:
                log(
                    f"[JSON] {stage} — tentativa de reparo "
                    f"{attempt}/{JSON_REPAIR_MAX_ATTEMPTS}"
                )
                return repair_json_with_nemotron(
                    raw_text,
                    stage=stage,
                    max_attempts=max_attempts,
                    retry_wait_seconds=retry_wait_seconds,
                )
            except Exception as repair_exc:
                last_error = repair_exc
                log(
                    f"[JSON] {stage} — reparo falhou: "
                    f"{type(repair_exc).__name__}: {repair_exc}"
                )

        raise RuntimeError(
            f"{stage} retornou JSON inválido e o reparo automático falhou: "
            f"{type(last_error).__name__}: {last_error}"
        )


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
    result = call_nemotron_json(
        prompt,
        MAX_TOKENS_INDIVIDUAL,
        stage=f"Auditoria individual: {filename}",
    )
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


def build_cross_consolidation_prompt(partial_results, results):
    schema = json.dumps(CROSS_SCHEMA, ensure_ascii=False, indent=2)
    partials_json = json.dumps(partial_results, ensure_ascii=False, indent=2)
    compact_json = json.dumps(
        [compact_individual_result(result) for result in results],
        ensure_ascii=False,
        indent=2,
    )

    return f"""
CONSOLIDAÇÃO FINAL DA VALIDAÇÃO CRUZADA DE UM ROBÔ QUANTITATIVO

Você recebeu:
1. auditorias cruzadas parciais feitas sobre grupos menores de motores;
2. os resumos das auditorias individuais de todos os motores.

Sua função é CONSOLIDAR, não refazer toda a auditoria.

Objetivos:
- unir achados equivalentes sem duplicação;
- preservar achados confirmados sustentados pelas auditorias parciais;
- identificar conflitos entre os dois grupos;
- refutar achados quando os resumos individuais ou parciais mostrarem incompatibilidade;
- manter como validação necessária aquilo que não puder ser comprovado;
- identificar problemas de integração entre grupos APENAS quando houver evidência nos dados fornecidos;
- não inventar contratos, chamadas, outputs ou comportamento não mostrado.

Classificações:
CONFIRMADO_PELA_INTEGRACAO
REFUTADO_PELA_INTEGRACAO
MANTIDO_COMO_INCONSISTENCIA_PROVAVEL
MANTIDO_COMO_REQUER_VALIDACAO
ESCOLHA_METODOLOGICA
NOVO_PROBLEMA_DE_INTEGRACAO

REGRAS DE SAÍDA:
- seja conciso;
- não repita o mesmo achado em categorias diferentes;
- cada item deve ser curto e objetivo;
- não reproduza grandes trechos de código;
- não ultrapasse 12 itens por lista;
- prioridade_correcao deve conter somente os pontos realmente prioritários;
- não altere código.

AUDITORIAS CRUZADAS PARCIAIS:
{partials_json}

RESUMOS INDIVIDUAIS:
{compact_json}

Retorne SOMENTE JSON válido nesta estrutura:
{schema}
""".strip()


def cross_validate(results, sources):
    """
    Executa a validação cruzada em grupos menores e depois consolida os resultados.
    Isso reduz o tamanho de cada resposta JSON e evita perder toda a execução por
    uma única resposta excessivamente longa.
    """
    partial_results = []

    ordered_results = [
        result for filename in MAIN_ENGINES
        for result in results
        if result.get("arquivo") == filename
    ]

    for start in range(0, len(ordered_results), CROSS_GROUP_SIZE):
        group_results = ordered_results[start:start + CROSS_GROUP_SIZE]
        group_files = [result.get("arquivo") for result in group_results]
        group_sources = {
            filename: sources[filename]
            for filename in group_files
            if filename in sources
        }

        group_number = (start // CROSS_GROUP_SIZE) + 1
        total_groups = (len(ordered_results) + CROSS_GROUP_SIZE - 1) // CROSS_GROUP_SIZE

        log(
            f"[CROSS] Grupo {group_number}/{total_groups}: "
            f"{', '.join(group_files)}"
        )

        prompt = build_cross_validation_prompt(group_results, group_sources)
        partial = call_nemotron_json(
            prompt,
            MAX_TOKENS_CROSS_PART,
            stage=f"Validação cruzada parcial {group_number}/{total_groups}",
            max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
            retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
        )

        if not isinstance(partial, dict):
            raise ValueError(
                f"Resultado cruzado parcial {group_number} não é um objeto JSON."
            )

        partial["grupo"] = group_number
        partial["motores"] = group_files
        partial_results.append(partial)

        save_json(
            OUTPUT_DIR / f"robot_cross_validation_part_{group_number}.json",
            partial,
        )
        log(f"[OK] Validação cruzada parcial {group_number} concluída e salva.")

    if not partial_results:
        raise RuntimeError("Nenhuma validação cruzada parcial foi concluída.")

    log("[CROSS] Consolidando as validações cruzadas parciais.")

    consolidation_prompt = build_cross_consolidation_prompt(
        partial_results,
        ordered_results,
    )
    consolidated = call_nemotron_json(
        consolidation_prompt,
        MAX_TOKENS_CROSS_CONSOLIDATION,
        stage="Consolidação da validação cruzada",
        max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
        retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
    )

    if not isinstance(consolidated, dict):
        raise ValueError("Resultado cruzado consolidado não é um objeto JSON.")

    # As validações parciais já foram salvas separadamente.
    # Não embutir tudo no consolidado reduz o tamanho do prompt do filtro factual.
    return consolidated


FACT_SCHEMA = {
    "veredito_factual": (
        "SEM_ERROS_FACTUAIS_CONFIRMADOS | "
        "HA_FATOS_CONFIRMADOS | "
        "EVIDENCIA_INSUFICIENTE"
    ),
    "confidence": 0,
    "fatos_confirmados": [],
    "fatos_refutados": [],
    "evidencia_insuficiente": [],
    "escolhas_metodologicas": [],
    "riscos_potenciais_nao_comprovados": [],
    "prioridade_fatos_confirmados": [],
    "resumo_quantitativo": {
        "fatos_confirmados": 0,
        "fatos_refutados": 0,
        "evidencia_insuficiente": 0,
        "escolhas_metodologicas": 0,
        "riscos_potenciais_nao_comprovados": 0,
    },
    "conclusao_factual": "",
}


def build_fact_filter_prompt(cross_result, sources):
    schema = json.dumps(FACT_SCHEMA, ensure_ascii=False, indent=2)
    cross_json = json.dumps(cross_result, ensure_ascii=False, indent=2)
    sources_json = json.dumps(sources, ensure_ascii=False, indent=2)

    return f"""
FILTRO FINAL DE FATO — AUDITORIA DE ROBÔ QUANTITATIVO

Esta é a terceira e última camada da auditoria.

Sua função NÃO é procurar livremente novos problemas.
Sua função é julgar os achados que sobreviveram à validação cruzada.

Classifique cada achado em uma destas categorias:
- FATO_CONFIRMADO
- FATO_REFUTADO
- EVIDENCIA_INSUFICIENTE
- ESCOLHA_METODOLOGICA
- RISCO_POTENCIAL_NAO_COMPROVADO

REGRA DE PROVA PARA FATO_CONFIRMADO:

Um achado só pode ser classificado como FATO_CONFIRMADO quando existir
evidência objetiva, direta e verificável no código fornecido.

Para cada FATO_CONFIRMADO, informe:
1. arquivo;
2. função, método ou bloco afetado, quando identificável;
3. trecho ou expressão curta e exata do código;
4. comportamento observado;
5. comportamento esperado;
6. por que esse comportamento esperado é demonstrável pelo próprio código
   ou pelo contrato entre os motores;
7. cadeia lógica que prova a divergência;
8. impacto concreto;
9. motores ou contratos que confirmam o problema;
10. nível de confiança.

NÃO classifique como FATO_CONFIRMADO quando:
- depender de requisito de negócio não fornecido;
- depender de preferência arquitetural;
- for apenas possibilidade futura;
- depender de interpretação subjetiva;
- houver mais de uma interpretação razoável;
- não houver comportamento esperado demonstrável;
- outro motor fornecer explicação válida;
- depender de teste não executado;
- depender de dado externo não fornecido;
- for apenas melhoria de robustez;
- representar escolha metodológica válida;
- não houver impacto concreto;
- a evidência for parcial;
- a cadeia causal estiver incompleta.

Classifique como FATO_REFUTADO quando:
- outro motor demonstrar que o comportamento está correto;
- o contrato entre os motores justificar o comportamento;
- a acusação original interpretar incorretamente uma variável;
- a acusação ignorar normalização ou tratamento posterior;
- a acusação for incompatível com o código fornecido.

Use EVIDENCIA_INSUFICIENTE quando houver suspeita plausível,
mas não existir prova suficiente para confirmar nem refutar.

Use ESCOLHA_METODOLOGICA quando o código estiver coerente e o ponto
for apenas uma alternativa de modelagem.

Use RISCO_POTENCIAL_NAO_COMPROVADO quando existir um cenário de risco,
mas o problema não estiver demonstrado no código atual.

REGRAS GERAIS:
- não altere código;
- não gere testes;
- não invente requisitos;
- não invente contratos;
- não invente comportamento externo;
- não aceite automaticamente os achados da auditoria anterior;
- julgue cada achado novamente com base no código;
- se a prova não fechar, rebaixe o achado;
- na dúvida entre FATO_CONFIRMADO e EVIDENCIA_INSUFICIENTE,
  use EVIDENCIA_INSUFICIENTE.

VALIDAÇÃO CRUZADA:
{cross_json}

CÓDIGO DOS MOTORES:
{sources_json}

Retorne SOMENTE JSON válido nesta estrutura:
{schema}
""".strip()


def fact_filter(cross_result, sources):
    prompt = build_fact_filter_prompt(cross_result, sources)
    result = call_nemotron_json(
        prompt,
        MAX_TOKENS_FACT,
        stage="Filtro final de fato",
        max_attempts=FINAL_STAGE_MAX_ATTEMPTS,
        retry_wait_seconds=FINAL_STAGE_RETRY_WAIT_SECONDS,
    )

    if not isinstance(result, dict):
        raise ValueError("Resultado do filtro factual não é um objeto JSON.")

    return result

def create_markdown(results, cross_result, fact_result, failures):
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
        "## Filtro Final de Fato",
        "",
        f"**Veredito factual:** {fact_result.get('veredito_factual', 'N/D')}",
        "",
        f"**Confiança factual:** {fact_result.get('confidence', 'N/D')}",
        "",
    ])

    summary = fact_result.get("resumo_quantitativo", {})
    if summary:
        lines.extend([
            f"- Fatos confirmados: {summary.get('fatos_confirmados', 0)}",
            f"- Fatos refutados: {summary.get('fatos_refutados', 0)}",
            f"- Evidência insuficiente: {summary.get('evidencia_insuficiente', 0)}",
            f"- Escolhas metodológicas: {summary.get('escolhas_metodologicas', 0)}",
            (
                "- Riscos potenciais não comprovados: "
                f"{summary.get('riscos_potenciais_nao_comprovados', 0)}"
            ),
            "",
        ])

    conclusion = fact_result.get("conclusao_factual", "")
    if conclusion:
        lines.extend(["## Conclusão Factual", "", conclusion, ""])

    return "\n".join(lines)


def run():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Regra operacional: só inicia a auditoria se o endpoint responder ao precheck.
    precheck_nemotron()

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

    log("=" * 78)
    log("NEMOTRON — AUDITORIA DOS PRINCIPAIS MOTORES")
    log("=" * 78)
    log(f"Motores encontrados: {len(existing_engines)}")
    log("=" * 78)

    for index, filename in enumerate(existing_engines, start=1):
        log(f"\n[{index}/{len(existing_engines)}] Auditando {filename}")
        engine_started = time.monotonic()

        try:
            sources[filename] = read_engine(filename)
            result = audit_engine(filename)
            results.append(result)
            save_json(
                OUTPUT_DIR / f"{Path(filename).stem}_audit.json",
                result,
            )
            elapsed = time.monotonic() - engine_started
            log(
                f"[OK] {filename} concluído em {elapsed:.1f}s | "
                f"veredito={result.get('veredito', 'N/D')} | "
                f"score={result.get('score_estrutural', 'N/D')}"
            )
        except Exception as exc:
            failure = {
                "arquivo": filename,
                "erro": f"{type(exc).__name__}: {exc}",
            }
            failures.append(failure)
            elapsed = time.monotonic() - engine_started
            log(f"[FALHA] {filename} após {elapsed:.1f}s | {failure['erro']}")

    if not results:
        raise RuntimeError("Nenhuma auditoria individual foi concluída.")

    log("\n" + "=" * 78)
    log("VALIDAÇÃO CRUZADA ENTRE OS MOTORES — EM BLOCOS")
    log("=" * 78)

    cross_result = cross_validate(results, sources)

    save_json(
        OUTPUT_DIR / "robot_cross_validation.json",
        cross_result,
    )
    log("[OK] Validação cruzada concluída e salva.")

    log("\n" + "=" * 78)
    log("FILTRO FINAL DE FATO")
    log("=" * 78)

    fact_result = fact_filter(cross_result, sources)

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
