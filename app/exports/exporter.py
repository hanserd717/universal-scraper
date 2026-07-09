"""
Экспорт items в Excel / CSV / JSON.

Важно: перед экспортом в Excel/CSV экранируем ячейки, начинающиеся с
=, +, -, @ — известная уязвимость "formula injection" (данные с сайта
могут содержать вредоносную "формулу", которая выполнится при открытии
файла в Excel/Google Sheets).
"""
import json
from io import BytesIO

import pandas as pd

DANGEROUS_PREFIXES = ("=", "+", "-", "@")


def _sanitize_cell(value):
    if isinstance(value, str) and value.startswith(DANGEROUS_PREFIXES):
        return "'" + value  # префикс апострофом нейтрализует формулу в Excel/Sheets
    return value


def _items_to_dataframe(items: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(items)
    for col in df.columns:
        df[col] = df[col].map(_sanitize_cell)
    return df


def export_to_excel(items: list[dict]) -> bytes:
    df = _items_to_dataframe(items)
    buffer = BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


def export_to_csv(items: list[dict]) -> bytes:
    df = _items_to_dataframe(items)
    return df.to_csv(index=False).encode("utf-8")


def export_to_json(items: list[dict]) -> bytes:
    # В JSON formula injection не актуальна (не открывается в Excel), но
    # сохраняем данные как есть для программного использования.
    return json.dumps(items, ensure_ascii=False, indent=2).encode("utf-8")
