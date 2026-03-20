"""
Factor AI ERP Agent — Classifier Prompt (part of llm_orchestrator)
--------------------------------------------------------------------
Prompt com o MÁXIMO de informação: princípio de decisão, tiers, contexto do agente,
e por modelo: id, tier, task_type, context window, custo, descrição completa, best_for completo.

Stack — escalada por output (cheapest → most capable):
  openai/gpt-5.1-codex-mini             → simple      ($0.25in / $2.00out)  ← default
  openai/gpt-5.4-nano                   → reasoning+  ($0.20in / $1.25out)
  moonshotai/kimi-k2.5                  → reasoning+  ($0.45in / $2.20out)
  openai/gpt-5.4-mini                   → reasoning+  ($0.75in / $4.50out)

"""

# Expected tool calls per tier
TIER_TOOL_CALLS = {
    "light": "0",
    "medium-low": "0-1",
    "medium": "1-3",
    "medium-high": "2-5",
    "heavy-lite": "3-10",
    "heavy": "5-15",
}

ROUTING_CONTEXT = """
TASK TYPES — match first, then pick CHEAPEST model:
  simple    → explicação, conceitos, página atual. ZERO tool calls. Resposta do page_context ou conversa.
  long      → traduzir, extrair, formatar, transcrever. Dados no texto, sem search_read no ERP.
  reasoning → listar, contar, criar, atualizar simples. 1-3 tool calls. Modelo único, campos diretos.
  reasoning+→ comparar, agregar, multi-step, Many2one simples. 2-5 tool calls no ERP.
  complex   → workflows, Many2one complexo, agentic longo, self-correction. 3-10 tool calls. LAST RESORT.

PRINCIPLE: Bom, Bonito e Barato — use the CHEAPEST model that does the job correctly.
  Default to Gemini 3.1 Flash Lite when in doubt — 1M context, safe for page_context.

AGENT CONTEXT (what the agent can do):
  - ERP API: list_available_models, inspect_model_fields, execute_erp_command (search_read, create, write...)
  - Page context (current ERP DOM injected into system prompt)
  - Conversation history, user memory, permissions, installed modules
  - Maximum 15 chained tool calls per request
"""

CLASSIFIER_SYSTEM_PROMPT = """You are a model routing classifier for the Factor AI ERP Agent.

Your ONLY job is to read the user message and decide which LLM model is best suited
to handle it, based on the ROUTING CONTEXT and AVAILABLE MODELS below.

ROUTING CONTEXT (read this first):
{routing_context}

IMPORTANT — Your decision has direct business impact:
  - Wrong model (too capable) = unnecessary cost to the company.
  - Wrong model (too cheap) = agent fails, loses user trust and time.
  - Your routing decision directly influences the final agent response and business outcome.
  - Principle: Bom, Bonito e Barato — good, clean, and cheap. Escalate only when necessary.

RULES:
- Respond with ONLY a valid JSON object. No explanation. No markdown. No extra text.
- Response format: {{"model": "provider/model-id"}}
- First match user message to TASK TYPE. Then pick the CHEAPEST model for that type.
- Use DESCRIPTION and BEST FOR to confirm the model fits.
- Among models that CAN handle the task, choose the one with lowest output cost.
- Valid model IDs (use exactly one): {valid_model_ids}
- When in doubt, use the default model: {default_model}

AVAILABLE MODELS AND THEIR CAPABILITIES:
{models_description}
"""

CLASSIFIER_USER_PROMPT = """User message: "{user_message}"

Which model should handle this request? Reply with JSON only: {{"model": "provider/model-id"}}"""


def _format_context(n):
    if n is None or n == "?":
        return "?"
    if isinstance(n, int):
        if n >= 1_000_000:
            return f"{n:,} ({n // 1_000_000}M)"
        if n >= 1000:
            return f"{n:,} ({n // 1000}K)"
        return str(n)
    return str(n)


def build_models_description(models: list[dict]) -> str:
    """
    Builds the full description of each model for the classifier:
    id, tier, task_type, context window, cost, description, best_for, not_for,
    expected tool calls per tier.
    """
    lines = []
    for m in models:
        tier = m.get("tier", "?")
        task_type = m.get("task_type", tier)
        ctx_str = _format_context(m.get("context_window"))
        pricing = m.get("pricing") or {}
        input_cost = pricing.get("input_per_1m_tokens", "?")
        output_cost = pricing.get("output_per_1m_tokens", "?")
        long_note = (pricing.get("long_context_note") or "").strip()
        tool_calls = TIER_TOOL_CALLS.get(tier, "?")

        lines.append("---")
        lines.append(f"MODEL ID: {m['id']}")
        lines.append(f"TASK TYPE: {task_type}  |  TIER: {tier}  |  EXPECTED TOOL CALLS: {tool_calls}")
        lines.append(f"CONTEXT WINDOW: {ctx_str} tokens")
        lines.append(f"COST: input {input_cost} / output {output_cost} per 1M tokens")
        if long_note:
            lines.append(f"COST NOTE: {long_note}")
        lines.append("")
        lines.append("DESCRIPTION:")
        lines.append(m.get("description", "").strip())
        lines.append("")
        lines.append("BEST FOR (match user message to these use cases and examples):")
        for use_case in m.get("best_for") or []:
            lines.append(f"  - {use_case.strip()}")
        not_for = (m.get("not_for") or "").strip()
        if not_for:
            lines.append("")
            lines.append(f"NOT FOR (do not pick this model if user asks): {not_for}")
        lines.append("")

    return "\n".join(lines)


def _valid_model_ids(models: list[dict]) -> str:
    return ", ".join(f'"{m["id"]}"' for m in models)


def build_classifier_prompt(
    user_message: str,
    models: list[dict],
    default_model: str,
) -> tuple[str, str]:
    """
    Builds the full system + user prompt for the classifier.

    Returns:
        (system_prompt, user_prompt) — pass both to the local Qwen3-0.6B classifier.
    """
    models_description = build_models_description(models)
    valid_ids = _valid_model_ids(models)

    system = CLASSIFIER_SYSTEM_PROMPT.format(
        routing_context=ROUTING_CONTEXT.strip(),
        valid_model_ids=valid_ids,
        default_model=default_model,
        models_description=models_description,
    )

    user = CLASSIFIER_USER_PROMPT.format(user_message=user_message)

    return system, user