"""LLM cost: USD per 1M tokens as (input, output). Prices drift, so the table is injectable
(the config layer merges OPENAI_PRICES from .env over these defaults)."""

DEFAULT_PRICES = {
    "gpt-5": (1.25, 10.0),
    "gpt-5-mini": (0.25, 2.0),
    "gpt-5-nano": (0.05, 0.40),
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
}


def cost(model, input_tokens, output_tokens, prices=None):
    table = prices or DEFAULT_PRICES
    # match dated snapshots like "gpt-5-mini-2025-08-07" to their base price
    key = model if model in table else next((k for k in sorted(table, key=len, reverse=True)
                                             if model.startswith(k)), None)
    if not key:
        return 0.0
    p_in, p_out = table[key]
    return (input_tokens * p_in + output_tokens * p_out) / 1_000_000


def over_budget(spent, budget):
    return bool(budget) and spent >= budget
