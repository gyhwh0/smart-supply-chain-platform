import json
import re
from datetime import datetime
from functools import lru_cache
from io import BytesIO
from pathlib import Path

import pandas as pd
from openai import OpenAI

from app.config import BASE_DIR, settings


DATA_PATH = BASE_DIR / "data" / "aa.xlsx"
REQUIRED_COLUMNS = ["商品名称", "品类", "规格", "总数量（最小单位）", "整件数量", "散装数量"]
OPTIONAL_COLUMNS = ["入库", "出库", "退货", "批次", "生产日期", "保质期(月)", "到期日", "剩余天数", "货物状态"]
SEARCH_COLUMNS = ["商品名称", "品类", "规格", "批次", "货物状态"]
BATCH_QUERY_HINTS = ["批次", "批号", "生产日期", "到期", "保质期", "剩余天数", "货物状态"]
OVERDUE_QUERY_HINTS = ["已经过期", "已过期", "过期商品", "过期了", "过期的", "有没有过期", "已经到期", "已到期", "到期了"]
EXPIRING_QUERY_HINTS = ["临期", "快过期", "快到期", "快坏了", "要过期", "要到期", "马上过期", "马上到期", "即将过期", "即将到期", "还有几天", "还剩几天", "多久到期", "什么时候到期", "什么时候过期", "还有多少天", "临保"]
QUERY_UNITS = ["瓶", "箱", "件", "包", "袋", "盒", "桶", "罐", "杯", "支", "条", "个", "斤", "公斤", "千克", "克", "升", "毫升"]
XLSX_SIGNATURE = b"PK"


def _clean(value):
    return value.strip() if isinstance(value, str) else value


@lru_cache(maxsize=4)
def _load_cached(path: str, modified_at: float) -> pd.DataFrame:
    del modified_at
    df = pd.read_excel(path, engine="openpyxl").map(_clean)
    missing = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"库存表缺少必要列：{', '.join(missing)}")
    for column in OPTIONAL_COLUMNS:
        if column not in df.columns:
            df[column] = pd.NA
    for column in ["总数量（最小单位）", "入库", "出库", "退货", "剩余天数"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    for column in ["生产日期", "到期日"]:
        df[column] = pd.to_datetime(df[column], errors="coerce")
    return df


def load_data() -> pd.DataFrame:
    if not DATA_PATH.exists():
        raise FileNotFoundError("尚未上传库存表 aa.xlsx")
    return _load_cached(str(DATA_PATH), DATA_PATH.stat().st_mtime).copy()


def last_update() -> str:
    if not DATA_PATH.exists():
        return "尚未上传库存表"
    return datetime.fromtimestamp(DATA_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def summary(df: pd.DataFrame | None = None) -> dict:
    df = load_data() if df is None else df
    stock = pd.to_numeric(df["总数量（最小单位）"], errors="coerce").fillna(0)
    batches = df["批次"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().nunique()
    days = pd.to_numeric(df["剩余天数"], errors="coerce")
    categories = sorted(
        {value.strip() for value in df["品类"].dropna().astype(str) if value.strip()}
    )
    return {
        "total_items": len(df),
        "total_stock": float(stock.sum()),
        "zero_stock": int((stock <= 0).sum()),
        "batch_count": int(batches),
        "expiring_30_days": int(((days >= 0) & (days <= 30)).sum()),
        "last_update": last_update(),
        "categories": categories,
    }


def normalize_query(text: str) -> str:
    batch_match = re.search(r"批(?:次|号)\s*[:：]?\s*([A-Za-z0-9_.-]+)", text)
    if batch_match:
        return batch_match.group(1).strip()
    unit_pattern = "|".join(sorted(map(re.escape, QUERY_UNITS), key=len, reverse=True))
    keyword = re.sub(rf"(还剩|剩余|剩下|还有|有)?\s*(多少|几)\s*({unit_pattern})?", "", text.strip(), flags=re.IGNORECASE)
    stop_words = ["麻烦", "请帮我", "帮我", "帮忙", "查一下", "查下", "查询", "查", "看一下", "看下", "看看", "帮我看一下", "还剩", "剩余", "剩下", "还有", "库存", "多少", "有没有", "请问", "一下", "现在", "批次", "批号", "生产日期", "到期日", "到期", "保质期", "货物状态", "是多少", "是什么", "是啥", "这个", "那个", "情况", "了吗", "了没", "吗", "呢"]
    for word in sorted(stop_words, key=len, reverse=True):
        keyword = keyword.replace(word, "")
    return re.sub(r"\s+", " ", keyword).strip(" ，,。？?") or text.strip()


@lru_cache(maxsize=256)
def extract_keyword(question: str) -> str:
    fallback = normalize_query(question)
    if not settings.INVENTORY_LLM_API_KEY:
        return fallback
    try:
        client = OpenAI(
            api_key=settings.INVENTORY_LLM_API_KEY,
            base_url=settings.INVENTORY_LLM_BASE_URL,
            timeout=4.0,
            max_retries=0,
        )
        response = client.chat.completions.create(
            model=settings.INVENTORY_LLM_MODEL,
            messages=[
                {"role": "system", "content": "只提取库存问题中的商品名、品类、规格、批次或批号。必须只返回 JSON：{\"keyword\":\"\"}。"},
                {"role": "user", "content": json.dumps({"user_input": question}, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        result = json.loads(response.choices[0].message.content or "{}")
        return normalize_query(str(result.get("keyword", ""))) or fallback
    except Exception:
        return fallback


def detect_query_type(question: str) -> str:
    if re.search(r"\d+\s*天内\s*(?:到期|过期)", question) or any(hint in question for hint in EXPIRING_QUERY_HINTS):
        return "临期查询"
    if any(hint in question for hint in OVERDUE_QUERY_HINTS):
        return "过期查询"
    if any(hint in question for hint in BATCH_QUERY_HINTS):
        return "批次查询"
    return "库存查询"


def parse_expiring_days(question: str) -> int:
    match = re.search(r"(\d+)\s*天", question)
    return max(1, min(int(match.group(1)), 365)) if match else 90


def search_mask(df: pd.DataFrame, keyword: str) -> pd.Series:
    if not keyword:
        return pd.Series(False, index=df.index)
    terms = [term for term in re.split(r"[\s,，、]+", keyword) if term]
    searchable = pd.Series("", index=df.index, dtype="string")
    for column in SEARCH_COLUMNS:
        searchable = searchable.str.cat(df[column].fillna("").astype(str), sep=" ")
    mask = pd.Series(True, index=df.index)
    for term in terms:
        mask &= searchable.str.contains(re.escape(term), case=False, na=False)
    return mask


def choose_keyword(df: pd.DataFrame, keyword: str) -> str:
    if not keyword or search_mask(df, keyword).any():
        return keyword
    for unit in sorted(QUERY_UNITS, key=len, reverse=True):
        if keyword.endswith(unit) and len(keyword) > len(unit) + 1:
            shorter = keyword[:-len(unit)].strip()
            if search_mask(df, shorter).any():
                return shorter
    return keyword


def matching_categories(df: pd.DataFrame, keyword: str) -> list[str]:
    """Match natural category phrases such as “油类” or “饮料类” to sheet categories."""
    if not keyword:
        return []
    category_names = sorted(
        {value.strip() for value in df["品类"].dropna().astype(str) if value.strip()}
    )
    category_keyword = re.sub(r"(?:商品)?(?:品类|类别|类)$", "", keyword.strip())
    return [
        category
        for category in category_names
        if keyword.strip() == category
        or (category_keyword and (category_keyword == category or category_keyword in category))
    ]


def _serialize(df: pd.DataFrame) -> list[dict]:
    columns = REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    result = df[columns].copy()
    for column in ["生产日期", "到期日"]:
        result[column] = result[column].dt.strftime("%Y-%m-%d")
    result = result.astype(object).where(pd.notna(result), None)
    return result.to_dict(orient="records")


def query(question: str, categories: list[str], only_available: bool, only_expiring: bool) -> dict:
    df = load_data()
    selected_categories = [str(category).strip() for category in categories if str(category).strip()]
    if categories:
        df = df[df["品类"].astype(str).isin(selected_categories)]
    if only_available:
        df = df[pd.to_numeric(df["总数量（最小单位）"], errors="coerce").fillna(0) > 0]
    if only_expiring:
        days = pd.to_numeric(df["剩余天数"], errors="coerce")
        df = df[(days >= 0) & (days <= 30)]
    question = question.strip()
    if not question and selected_categories:
        query_type = "品类查询"
        keyword = "、".join(selected_categories)
    else:
        query_type = detect_query_type(question)
        # Keep the original inventory-query behavior: DeepSeek extracts the product,
        # category, specification or batch keyword for every question. The extractor
        # has a short timeout and falls back to local normalization if DeepSeek is slow.
        keyword = choose_keyword(df, extract_keyword(question))
        category_matches = matching_categories(df, keyword)
        if query_type == "库存查询" and category_matches:
            query_type = "品类查询"
    if query_type == "临期查询":
        days_left = parse_expiring_days(question)
        base = df[search_mask(df, keyword)] if keyword and search_mask(df, keyword).any() else df
        days = pd.to_numeric(base["剩余天数"], errors="coerce")
        result = base[(days >= 0) & (days <= days_left)].sort_values("剩余天数")
    elif query_type == "过期查询":
        base = df[search_mask(df, keyword)] if keyword and search_mask(df, keyword).any() else df
        days = pd.to_numeric(base["剩余天数"], errors="coerce")
        result = base[days < 0].sort_values("剩余天数")
    elif query_type == "品类查询":
        if not question:
            result = df
        else:
            result = df[df["品类"].astype(str).isin(category_matches)]
    else:
        result = df[search_mask(df, keyword)]
    return {
        "query_type": query_type,
        "keyword": keyword,
        "days_left": parse_expiring_days(question) if query_type == "临期查询" else None,
        "count": len(result),
        "has_zero_stock": bool((pd.to_numeric(result["总数量（最小单位）"], errors="coerce").fillna(0) <= 0).any()),
        "rows": _serialize(result),
    }


def replace_data(file_bytes: bytes) -> dict:
    if not file_bytes.startswith(XLSX_SIGNATURE):
        raise ValueError("这不是标准 xlsx 文件")
    preview = pd.read_excel(BytesIO(file_bytes), engine="openpyxl", nrows=5)
    missing = [column for column in REQUIRED_COLUMNS if column not in preview.columns]
    if missing:
        raise ValueError(f"库存表缺少必要列：{', '.join(missing)}")
    DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = DATA_PATH.with_suffix(".uploading.xlsx")
    temporary.write_bytes(file_bytes)
    temporary.replace(DATA_PATH)
    _load_cached.cache_clear()
    return summary()
