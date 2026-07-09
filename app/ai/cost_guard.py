"""
Оценка и контроль стоимости AI-обработки перед запуском.
Грубая оценка на основе среднего числа токенов на item — уточнить
после первых реальных прогонов на конкретной модели.
"""
from dataclasses import dataclass

from config import settings

# Очень грубые ориентиры для gpt-4o-mini (уточнить под актуальный прайс модели)
AVG_INPUT_TOKENS_PER_ITEM = 300
AVG_OUTPUT_TOKENS_PER_ITEM = 150
PRICE_PER_1K_INPUT_TOKENS_USD = 0.00015
PRICE_PER_1K_OUTPUT_TOKENS_USD = 0.0006


@dataclass
class CostEstimate:
    items_count: int
    estimated_cost_usd: float
    within_budget: bool


def estimate_cost(items_count: int, tasks: int = 1) -> CostEstimate:
    """
    tasks — сколько AI-операций на item (например 1 для категоризации,
    2 если ещё и перевод — тогда стоимость примерно удваивается).
    """
    input_cost = (items_count * AVG_INPUT_TOKENS_PER_ITEM * tasks / 1000) * PRICE_PER_1K_INPUT_TOKENS_USD
    output_cost = (items_count * AVG_OUTPUT_TOKENS_PER_ITEM * tasks / 1000) * PRICE_PER_1K_OUTPUT_TOKENS_USD
    total = round(input_cost + output_cost, 4)
    return CostEstimate(
        items_count=items_count,
        estimated_cost_usd=total,
        within_budget=total <= settings.ai_monthly_budget_usd,
    )
