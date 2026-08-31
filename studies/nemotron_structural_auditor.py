import json
import os
import sys
from pathlib import Path

from openai import OpenAI


MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
BASE_URL = "https://integrate.api.nvidia.com/v1"

SRC_DIR = Path("src")
OUTPUT_DIR = Path("outputs/structural_audit")


def get_client():
    api_key = os.getenv("NVIDIA_API_KEY")

    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY não encontrada nas variáveis de ambiente."
        )

    return OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
    )


def get_source_file(filename):
    """
    Permite auditar somente arquivos Python diretamente dentro de src/.
    Evita que o workflow leia arquivos arbitrários do repositório.
    """
    filename = Path(filename).name

    if not filename.endswith(".py"):
        raise ValueError("Somente arquivos .py podem ser auditados.")

    path = SRC_DIR / filename

    if not path.is_file():
        raise FileNotFoundError(f"Motor não encontrado: {path}")

    return path


def build_prompt(filename, source_code):
    return f"""
Você é um auditor técnico de um sistema quantitativo de investimentos.

Sua tarefa é auditar estruturalmente o código abaixo.

ARQUIVO:
{filename}

IMPORTANTE:
Este sistema já passou por testes em diferentes cenários econômicos.
Não refaça a avaliação histórica de eficiência da estratégia.

O objetivo desta auditoria é encontrar problemas no CÓDIGO,
na MATEMÁTICA, na LÓGICA e na INTEGRAÇÃO.

Analise especificamente:

- fórmulas matemáticas;
- identidades e conservação;
- unidades;
- percentuais;
- normalizações;
- divisões por zero;
- NaN e infinitos;
- tratamento de dados ausentes;
- tratamento de ativos desconhecidos;
- fallbacks;
- proxies;
- thresholds;
- double counting;
- look-ahead real;
- vazamento temporal;
- fail-open;
- fail-safe;
- coerência entre inputs e outputs;
- integração com outros motores;
- interpretação dos resultados;
- falhas silenciosas;
- rastreabilidade.

REGRAS:

1. Diferencie claramente três categorias:

ERRO_CONFIRMADO:
Existe evidência suficiente no próprio código de bug matemático,
lógico, temporal, de integração ou de tratamento de dados.

REQUER_TESTE:
Existe uma suspeita tecnicamente plausível, mas ela precisa ser
comprovada por teste determinístico antes de qualquer alteração.

ESCOLHA_METODOLOGICA:
A implementação pode ser discutível ou simplificada, mas não existe
evidência suficiente para classificá-la como erro.

2. Não classifique uma metodologia como errada apenas porque existe
uma técnica mais sofisticada.

3. Não considere shift() automaticamente como look-ahead.
Analise a direção temporal.

4. Não considere thresholds fixos automaticamente como erro.

5. Não considere uso de valores absolutos automaticamente como erro.
Primeiro determine a finalidade daquela métrica.

6. Não proponha mudança de metodologia apenas para melhorar
sofisticação estatística.

7. Não invente resultados de testes.

8. Quando algo exigir execução para comprovação, classifique como
REQUER_TESTE e descreva exatamente o teste necessário.

9. Seja conservador ao declarar erro crítico.

10. Não altere o código.

11. Caso exista uma correção óbvia para um ERRO_CONFIRMADO,
descreva apenas a correção mínima necessária.

12. Preserve a metodologia original sempre que possível.

CÓDIGO DO MOTOR:

{source_code}

Retorne SOMENTE JSON válido, sem Markdown e sem texto fora do JSON.

Estrutura obrigatória:

{{
  "arquivo": "{filename}",
  "veredito": "APROVADO | APROVADO_COM_RESSALVAS | REQUER_TESTE | ERRO_CONFIRMADO",
  "score_estrutural": 0,
  "confidence": 0,
  "erro_critico_confirmado": false,

  "erros_confirmados": [
    {{
      "titulo": "",
      "severidade": "BAIXA | MEDIA | ALTA | CRITICA",
      "evidencia": "",
      "impacto": "",
      "correcao_minima": ""
    }}
  ],

  "requer_testes": [
    {{
      "titulo": "",
      "hipotese": "",
      "teste_deterministico": "",
      "criterio_de_falha": ""
    }}
  ],

  "escolhas_metodologicas": [
    {{
      "titulo": "",
      "descricao": "",
      "observacao": ""
    }}
  ],

  "matematica": {{
    "status": "OK | ATENCAO | ERRO",
    "observacoes": []
  }},

  "dados": {{
    "status": "OK | ATENCAO | ERRO",
    "observacoes": []
  }},

  "integracao": {{
    "status": "OK | ATENCAO | ERRO",
    "observacoes": []
  }},

  "fail_safe": {{
    "status": "OK | ATENCAO | ERRO",
    "observacoes": []
  }},

  "pontos_fortes": [],

  "conclusao": ""
}}

O score estrutural vai de 0 a 100 e representa qualidade estrutural,
robustez e rastreabilidade.

O score NÃO representa probabilidade estatística de o código
estar correto.
"""


def extract_json(text):
    """
    Tenta interpretar a resposta diretamente.
    Se o modelo eventualmente adicionar ```json, remove o wrapper.
    """
    text = text.strip()

    if text.startswith("```"):
        lines = text.splitlines()

        if lines[0].strip().lower() in ("```json", "```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return json.loads(text)


def validate_result(result, filename):
    if not isinstance(result, dict):
        raise ValueError("Resposta do Nemotron não é um objeto JSON.")

    result["arquivo"] = filename

    for field in (
        "erros_confirmados",
        "requer_testes",
        "escolhas_metodologicas",
        "pontos_fortes",
    ):
        if not isinstance(result.get(field), list):
            result[field] = []

    try:
        score = float(result.get("score_estrutural", 0))
    except (TypeError, ValueError):
        score = 0.0

    try:
        confidence = float(result.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0

    result["score_estrutural"] = max(0.0, min(100.0, score))
    result["confidence"] = max(0.0, min(100.0, confidence))

    return result


def audit(filename):
    source_path = get_source_file(filename)
    source_code = source_path.read_text(encoding="utf-8")

    client = get_client()

    print("=" * 70)
    print("NEMOTRON STRUCTURAL AUDITOR")
    print("=" * 70)
    print(f"Motor:  {source_path.name}")
    print(f"Modelo: {MODEL}")
    print("=" * 70)

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "Você é um auditor conservador de sistemas "
                    "quantitativos. Diferencie rigorosamente bugs "
                    "comprovados, hipóteses que exigem testes e "
                    "escolhas metodológicas."
                ),
            },
            {
                "role": "user",
                "content": build_prompt(
                    source_path.name,
                    source_code,
                ),
            },
        ],
        temperature=0.1,
        max_tokens=8000,
        extra_body={
            "chat_template_kwargs": {
                "enable_thinking": False
            }
        },
    )

    content = response.choices[0].message.content

    if not content:
        raise RuntimeError("Nemotron retornou resposta vazia.")

    result = extract_json(content)
    result = validate_result(result, source_path.name)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_path = (
        OUTPUT_DIR
        / f"{source_path.stem}_structural_audit.json"
    )

    output_path.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print("RESULTADO")
    print("-" * 70)
    print(f"Veredito:          {result.get('veredito', 'N/D')}")
    print(f"Score estrutural:  {result.get('score_estrutural', 'N/D')}")
    print(f"Confiança:         {result.get('confidence', 'N/D')}")
    print(
        "Erros confirmados:",
        len(result.get("erros_confirmados", [])),
    )
    print(
        "Testes requeridos:",
        len(result.get("requer_testes", [])),
    )
    print(
        "Escolhas metod.: ",
        len(result.get("escolhas_metodologicas", [])),
    )
    print(f"Relatório:         {output_path}")
    print("=" * 70)

    return result


def main():
    if len(sys.argv) != 2:
        print(
            "Uso: python studies/nemotron_structural_auditor.py "
            "nome_do_motor.py"
        )
        sys.exit(2)

    try:
        audit(sys.argv[1])

    except Exception as exc:
        print()
        print("=" * 70)
        print("AUDITORIA FALHOU")
        print("=" * 70)
        print(f"{type(exc).__name__}: {exc}")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
