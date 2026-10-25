import base64
import hashlib
import io
import json
import re
import struct
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app import picking_service, sales_order_service
from app.models import (
    Complaint,
    Customer,
    Product,
    ProductUnit,
    SalesOrder,
    SalesOrderItem,
    User,
    WeComCustomerBinding,
    WeComMessage,
    WeComOrderDraft,
    WeComOrderDraftItem,
)


COMPLAINT_KEYWORDS = {
    "食品安全": (
        "中毒", "食物中毒", "异物", "变质", "过期", "发霉", "有虫",
        "拉肚子", "腹泻", "呕吐", "恶心", "肚子疼", "肚子痛", "腹痛",
        "吃坏了", "不舒服", "送医院", "去医院", "就医", "多人不适", "集体不适",
    ),
    "少货漏货": ("少了", "缺货", "漏送", "没送", "数量不对"),
    "品质问题": ("烂了", "坏了", "不新鲜", "质量", "品质", "不能吃"),
    "重量问题": ("缺斤", "少秤", "重量不够", "斤数不对"),
    "配送延迟": ("还没到", "没送到", "迟到", "太晚", "延迟"),
    "价格问题": ("价格不对", "太贵", "单价不对", "算错"),
    "服务问题": ("态度", "投诉", "客服", "司机"),
}

COMMON_UNITS = ("公斤", "千克", "kg", "KG", "斤", "件", "箱", "包", "袋", "瓶", "盒", "桶", "筐", "个", "只")


def _normalized_product_name(value: str | None) -> str:
    return re.sub(r"[\s（）()【】\[\]_-]", "", value or "").lower()


def _requested_unit(raw_message: str, requested_name: str) -> str | None:
    name = re.escape(requested_name.strip())
    unit_pattern = "|".join(map(re.escape, COMMON_UNITS))
    match = re.search(rf"{name}.{{0,18}}?\d+(?:\.\d+)?\s*({unit_pattern})", raw_message, re.I)
    return match.group(1) if match else None


def _unit_sales_price(product: Product, unit: ProductUnit | None):
    if not unit:
        return None
    if unit.sales_price is not None:
        return unit.sales_price
    if product.reference_price is None:
        return None
    return product.reference_price * unit.conversion_rate


def _delivery_date_from_text(content: str, base_date: date) -> date | None:
    if "大后天" in content:
        return base_date + timedelta(days=3)
    if "后天" in content:
        return base_date + timedelta(days=2)
    if "明天" in content or "明日" in content:
        return base_date + timedelta(days=1)
    if "今天" in content or "今日" in content:
        return base_date
    match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})[日号]?", content)
    if not match:
        return None
    year = int(match.group(1) or base_date.year)
    try:
        result = date(year, int(match.group(2)), int(match.group(3)))
        if not match.group(1) and result < base_date:
            result = date(year + 1, result.month, result.day)
        return result
    except ValueError:
        return None


def _fallback_order_extract(products: list[dict], content: str, base_date: date, error: str = "") -> dict:
    unit_pattern = "|".join(map(re.escape, COMMON_UNITS))
    items: list[dict] = []
    occupied_names: set[str] = set()
    for product in sorted(products, key=lambda row: max(map(len, [row["name"], *row.get("aliases", [])])), reverse=True):
        matched_name = None
        match = None
        for name in sorted([product["name"], *product.get("aliases", [])], key=len, reverse=True):
            after = re.search(rf"{re.escape(name)}.{{0,8}}?(\d+(?:\.\d+)?)\s*({unit_pattern})", content, re.I)
            before = re.search(rf"(\d+(?:\.\d+)?)\s*({unit_pattern})\s*{re.escape(name)}", content, re.I)
            match = after or before
            if match:
                matched_name = name
                break
        if not match:
            continue
        quantity, unit_name = match.group(1), match.group(2)
        unit = next((row for row in product["units"] if row["name"].lower() == unit_name.lower()), None)
        items.append(
            {
                "requested_name": matched_name or product["name"],
                "product_id": product["id"],
                "unit_id": unit["id"] if unit else None,
                "quantity": float(quantity),
                "specification": unit_name,
                "remark": None,
            }
        )
        occupied_names.update(_normalized_product_name(value) for value in [product["name"], *product.get("aliases", [])])
    for clause in re.split(r"[，,、；;。\n]", content):
        match = re.search(rf"(\d+(?:\.\d+)?)\s*({unit_pattern})\s*([\u4e00-\u9fa5A-Za-z0-9_-]+)", clause, re.I)
        if not match:
            continue
        name = re.sub(r"^(?:的|给我|下|下单|订|要)+", "", match.group(3)).strip()
        if not name or _normalized_product_name(name) in occupied_names:
            continue
        items.append(
            {
                "requested_name": name,
                "product_id": None,
                "unit_id": None,
                "quantity": float(match.group(1)),
                "specification": match.group(2),
                "remark": None,
            }
        )
    return {
        "intent": "order" if items else "other",
        "confidence": 0.75 if items else 0,
        "delivery_date": (_delivery_date_from_text(content, base_date) or base_date).isoformat() if items else None,
        "items": items,
        "notes": f"本地规则兜底识别；大模型异常：{error}" if error else "本地规则识别",
    }


def rematch_pending_items_for_product(db: Session, product: Product) -> dict:
    """Refresh unresolved WeCom draft lines after a product, price, or unit changes."""
    rows = db.scalars(
        select(WeComOrderDraftItem)
        .options(selectinload(WeComOrderDraftItem.draft).selectinload(WeComOrderDraft.items))
        .join(WeComOrderDraft, WeComOrderDraft.id == WeComOrderDraftItem.draft_id)
        .where(WeComOrderDraft.status.in_({"needs_review", "awaiting_confirmation"}))
    ).unique().all()
    affected: dict[int, WeComOrderDraft] = {}
    matched_items = 0
    for item in rows:
        if item.product_id not in {None, product.id}:
            continue
        if item.product_id is None:
            names = [product.name, *product.aliases]
            names.extend(
                str(row.get("alias"))
                for row in product.customer_aliases
                if int(row.get("customer_id", 0)) == item.draft.customer_id
            )
            if _normalized_product_name(item.requested_name) not in {
                _normalized_product_name(value) for value in names
            }:
                continue
        item.product_id = product.id
        requested_unit = _requested_unit(item.draft.raw_message, item.requested_name)
        units_by_name = {unit.name.lower(): unit for unit in product.units}
        if requested_unit and requested_unit.lower() in units_by_name:
            item.unit_id = units_by_name[requested_unit.lower()].id
        elif not requested_unit and len(product.units) == 1:
            item.unit_id = product.units[0].id
        elif item.unit_id and item.unit_id not in {unit.id for unit in product.units}:
            item.unit_id = None
        selected_unit = next((unit for unit in product.units if unit.id == item.unit_id), None)
        item.unit_price = _unit_sales_price(product, selected_unit)
        item.matched = bool(
            item.unit_id and item.quantity > 0 and product.active and item.unit_price is not None
        )
        matched_items += int(item.matched)
        affected[item.draft.id] = item.draft
    for draft in affected.values():
        all_matched = bool(draft.items) and all(
            item.matched and item.product_id and item.unit_id and item.unit_price is not None
            for item in draft.items
        )
        draft.status = "awaiting_confirmation" if all_matched and float(draft.confidence) >= 0.8 else "needs_review"
        source_message = db.scalar(select(WeComMessage).where(WeComMessage.msgid == draft.source_msgid))
        if source_message:
            source_message.status = draft.status
            source_message.intent = (
                "order_and_complaint" if source_message.intent in {"complaint", "order_and_complaint"} else "order"
            )
    return {"affected_drafts": len(affected), "matched_items": matched_items}


def wecom_config_status() -> dict:
    fields = {
        "corp_id": bool(settings.WECOM_CORP_ID),
        "kf_secret": bool(settings.WECOM_KF_SECRET),
        "callback_token": bool(settings.WECOM_CALLBACK_TOKEN),
        "encoding_aes_key": bool(settings.WECOM_ENCODING_AES_KEY),
    }
    return {
        "configured": all(fields.values()),
        "fields": fields,
        "voice_recognition_configured": bool(settings.VOICE_API_KEY),
        "voice_model": settings.VOICE_MODEL if settings.VOICE_API_KEY else None,
    }


def _signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    return hashlib.sha1("".join(sorted([token, timestamp, nonce, encrypted])).encode()).hexdigest()


def _decrypt(encrypted: str) -> str:
    key = base64.b64decode(settings.WECOM_ENCODING_AES_KEY + "=")
    encrypted_bytes = base64.b64decode(encrypted)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    plain = decryptor.update(encrypted_bytes) + decryptor.finalize()
    padding = plain[-1]
    if padding < 1 or padding > 32:
        raise ValueError("企业微信回调填充无效")
    plain = plain[:-padding]
    message_length = struct.unpack("!I", plain[16:20])[0]
    message = plain[20:20 + message_length]
    receiver = plain[20 + message_length:].decode("utf-8")
    if settings.WECOM_CORP_ID and receiver != settings.WECOM_CORP_ID:
        raise ValueError("企业微信回调接收方不匹配")
    return message.decode("utf-8")


def verify_callback(msg_signature: str, timestamp: str, nonce: str, echostr: str) -> str:
    expected = _signature(settings.WECOM_CALLBACK_TOKEN, timestamp, nonce, echostr)
    if not settings.WECOM_CALLBACK_TOKEN or expected != msg_signature:
        raise ValueError("企业微信回调签名验证失败")
    return _decrypt(echostr)


def parse_callback(body: bytes, msg_signature: str, timestamp: str, nonce: str) -> dict:
    root = ET.fromstring(body.decode("utf-8"))
    encrypted = root.findtext("Encrypt") or ""
    expected = _signature(settings.WECOM_CALLBACK_TOKEN, timestamp, nonce, encrypted)
    if not encrypted or expected != msg_signature:
        raise ValueError("企业微信回调签名验证失败")
    message_root = ET.fromstring(_decrypt(encrypted))
    return {child.tag: child.text or "" for child in message_root}


_token_cache = {"value": "", "expires_at": 0.0}


def _json_request(url: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    if result.get("errcode", 0) != 0:
        raise RuntimeError(f"企业微信接口失败：{result.get('errmsg')} ({result.get('errcode')})")
    return result


def access_token() -> str:
    if _token_cache["value"] and _token_cache["expires_at"] > time.time() + 120:
        return _token_cache["value"]
    query = urllib.parse.urlencode(
        {"corpid": settings.WECOM_CORP_ID, "corpsecret": settings.WECOM_KF_SECRET}
    )
    result = _json_request(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{query}")
    _token_cache.update(
        value=result["access_token"],
        expires_at=time.time() + int(result.get("expires_in", 7200)),
    )
    return result["access_token"]


def send_text(external_userid: str, open_kfid: str, content: str):
    if not wecom_config_status()["configured"] or open_kfid == "test-kf":
        return {"skipped": True}
    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/send_msg?access_token={access_token()}"
    return _json_request(
        url,
        {
            "touser": external_userid,
            "open_kfid": open_kfid,
            "msgid": uuid4().hex,
            "msgtype": "text",
            "text": {"content": content[:2048]},
        },
    )


def refresh_binding_profile(binding: WeComCustomerBinding) -> None:
    """Best-effort sync of the WeCom customer nickname/remark; never blocks order processing on failure."""
    if binding.open_kfid == "test-kf":
        return
    if binding.profile_synced_at and binding.profile_synced_at > datetime.now() - timedelta(hours=24):
        return
    try:
        url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/customer/batchget?access_token={access_token()}"
        result = _json_request(
            url,
            {"external_userid_list": [binding.external_userid], "need_enter_session_context": 0},
        )
        profile = next(
            (
                row for row in result.get("customer_list", [])
                if row.get("external_userid") == binding.external_userid
            ),
            {},
        )
        nickname = str(profile.get("nickname") or profile.get("name") or "").strip()
        remark = str(profile.get("remark") or profile.get("remark_name") or "").strip()
        if nickname:
            binding.wechat_name = nickname[:100]
        if remark:
            binding.wechat_remark = remark[:100]
        binding.profile_synced_at = datetime.now()
    except Exception:
        # Customer profile availability varies by WeCom access scope. Existing/manual names remain usable.
        return


def _salutation(binding: WeComCustomerBinding) -> str:
    customer = binding.customer
    return str(
        binding.wechat_remark
        or binding.wechat_name
        or customer.contact_name
        or customer.name
    ).strip()


def sync_messages(event_token: str, open_kfid: str = "") -> list[dict]:
    url = f"https://qyapi.weixin.qq.com/cgi-bin/kf/sync_msg?access_token={access_token()}"
    cursor = ""
    messages = []
    while True:
        payload = {"cursor": cursor, "token": event_token, "limit": 100, "voice_format": 0}
        if open_kfid:
            payload["open_kfid"] = open_kfid
        result = _json_request(url, payload)
        messages.extend(result.get("msg_list", []))
        if not result.get("has_more"):
            break
        cursor = result.get("next_cursor", "")
    return messages


def transcribe_voice(media_id: str) -> str:
    if not media_id:
        raise RuntimeError("语音消息缺少媒体ID")
    if not settings.VOICE_API_KEY:
        raise RuntimeError("尚未配置语音识别API")
    query = urllib.parse.urlencode({"access_token": access_token(), "media_id": media_id})
    request = urllib.request.Request(f"https://qyapi.weixin.qq.com/cgi-bin/media/get?{query}")
    with urllib.request.urlopen(request, timeout=30) as response:
        audio = response.read()
        content_type = response.headers.get_content_type()
    if content_type == "application/json":
        result = json.loads(audio.decode("utf-8"))
        raise RuntimeError(f"企业微信语音下载失败：{result.get('errmsg', '未知错误')}")
    stream = io.BytesIO(audio)
    stream.name = "wecom-voice.amr"
    client = OpenAI(api_key=settings.VOICE_API_KEY, base_url=settings.VOICE_BASE_URL)
    result = client.audio.transcriptions.create(
        model=settings.VOICE_MODEL,
        file=stream,
        language="zh",
        prompt="食材配送下单语音，准确识别商品名称、数量、单位、日期以及投诉内容。",
    )
    text_value = str(getattr(result, "text", "") or "").strip()
    if not text_value:
        raise RuntimeError("语音识别结果为空")
    return text_value


def _complaint_category(content: str) -> tuple[str | None, str]:
    for category, words in COMPLAINT_KEYWORDS.items():
        if any(word in content for word in words):
            return category, "P0" if category == "食品安全" else "P1"
    return ("其他", "P2") if "投诉" in content else (None, "P2")


def _create_complaint(
    db: Session,
    *,
    message: WeComMessage,
    customer: Customer,
    category: str,
    severity: str,
    salutation: str = "",
) -> tuple[Complaint, str]:
    existing = db.scalar(select(Complaint).where(Complaint.source_msgid == message.msgid))
    if existing:
        return existing, "该投诉已经登记，工作人员正在处理。"
    complaint = Complaint(
        complaint_no=f"CP{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
        customer_id=customer.id,
        assigned_to=customer.order_clerk_id,
        source_msgid=message.msgid,
        category=category,
        severity=severity,
        content=message.content or "",
        status="new",
        due_at=datetime.now() + timedelta(hours=1 if severity == "P0" else 4 if severity == "P1" else 24),
    )
    db.add(complaint)
    message.intent = "complaint"
    message.status = "processed"
    db.commit()
    handler = customer.order_clerk.name if customer.order_clerk else "工作人员"
    prefix = f"{salutation}，" if salutation else ""
    if severity == "P0":
        reply = (
            f"{prefix}孩子们现在情况怎么样？这件事我已经紧急登记了，编号是{complaint.complaint_no}，"
            f"也马上通知了{handler}。先不要继续食用，麻烦保留剩余食材、包装和照片；"
            "如果症状比较严重，请及时就医。"
        )
    else:
        reply = f"{prefix}您说的问题我记下了，编号是{complaint.complaint_no}，已经请{handler}尽快处理。"
    return complaint, reply


def _binding(db: Session, external_userid: str, open_kfid: str):
    return db.scalar(
        select(WeComCustomerBinding)
        .options(selectinload(WeComCustomerBinding.customer))
        .where(
            WeComCustomerBinding.external_userid == external_userid,
            WeComCustomerBinding.open_kfid == open_kfid,
            WeComCustomerBinding.verified.is_(True),
        )
    )


def _latest_order_draft(db: Session, customer_id: int, external_userid: str):
    return db.scalar(
        select(WeComOrderDraft)
        .options(selectinload(WeComOrderDraft.items))
        .where(
            WeComOrderDraft.customer_id == customer_id,
            WeComOrderDraft.external_userid == external_userid,
            WeComOrderDraft.status == "awaiting_confirmation",
        )
        .order_by(WeComOrderDraft.id.desc())
    )


def _confirm_draft(db: Session, draft: WeComOrderDraft) -> tuple[SalesOrder, bool]:
    if draft.sales_order_id:
        return db.get(SalesOrder, draft.sales_order_id), False
    if not draft.items or any(
        not item.matched or not item.product_id or not item.unit_id or item.unit_price is None
        for item in draft.items
    ):
        raise ValueError("订单仍有未匹配商品或价格，需订单员处理")
    creator_id = draft.assigned_to or draft.customer.order_clerk_id
    if not creator_id:
        creator_id = db.scalar(select(User.id).where(User.role == "admin", User.active.is_(True)))
    if not creator_id:
        raise ValueError("客户尚未分配订单员")
    draft.assigned_to = creator_id
    order = sales_order_service.find_daily_order(
        db,
        customer_id=draft.customer_id,
        order_date=date.today(),
        delivery_date=draft.delivery_date,
    )
    merged = order is not None
    if not order:
        order = SalesOrder(
            order_no=f"SO{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}",
            customer_id=draft.customer_id,
            created_by=creator_id,
            order_date=date.today(),
            delivery_date=draft.delivery_date,
            title="企业微信客户订单",
            notes=f"来源：企业微信\n原始消息：{draft.raw_message}",
            source="wecom",
            external_reference=draft.source_msgid,
            status="confirmed",
            confirmed_at=datetime.now(),
        )
        db.add(order)
    supplement_amount = Decimal("0")
    for item in draft.items:
        product = db.get(Product, item.product_id)
        unit = db.get(ProductUnit, item.unit_id)
        customer_alias = next(
            (
                row.get("alias") for row in product.customer_aliases
                if int(row.get("customer_id", 0)) == draft.customer_id
            ),
            None,
        )
        sales_order_service.add_or_merge_item(
            db,
            order,
            product=product,
            unit=unit,
            display_name=str(customer_alias or product.name),
            specification=item.specification,
            quantity=item.quantity,
            unit_price=item.unit_price,
            remark=item.remark,
        )
        supplement_amount += item.quantity * item.unit_price
    if merged:
        order.supplement_amount = Decimal(order.supplement_amount or 0) + supplement_amount
        sales_order_service.append_note(order, draft.raw_message, "企业微信加单")
    order.status = "confirmed"
    order.confirmed_at = order.confirmed_at or datetime.now()
    db.flush()
    if merged:
        picking_service.sync_picking_task(db, order)
    draft.sales_order_id = order.id
    draft.status = "confirmed"
    return order, merged


def _extract_order(db: Session, customer: Customer, content: str, base_date: date | None = None) -> dict:
    reference_date = base_date or date.today()
    products = db.scalars(
        select(Product).options(selectinload(Product.units)).where(Product.active.is_(True))
        .order_by(Product.category, Product.name)
    ).all()
    catalog = [
        {
            "id": product.id,
            "name": product.name,
            "aliases": [
                *product.aliases,
                *[
                    str(row.get("alias"))
                    for row in product.customer_aliases
                    if int(row.get("customer_id", 0)) == customer.id
                ],
            ],
            "category": product.category,
            "price": float(product.reference_price) if product.reference_price is not None else None,
            "units": [
                {
                    "id": unit.id,
                    "name": unit.name,
                    "is_base": unit.is_base,
                    "sales_price": float(_unit_sales_price(product, unit)) if _unit_sales_price(product, unit) is not None else None,
                }
                for unit in product.units
            ],
        }
        for product in products
    ]
    if not settings.LLM_API_KEY:
        result = _fallback_order_extract(catalog, content, reference_date, "未配置大模型")
        result["catalog"] = {product["id"]: product for product in catalog}
        return result
    try:
        client = OpenAI(api_key=settings.LLM_API_KEY, base_url=settings.LLM_BASE_URL)
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
            {
                "role": "system",
                "content": (
                    "你是食材配送业务消息分类与订单结构化助手。先判断消息是否涉及投诉，"
                    "尤其是食用后腹泻、呕吐、腹痛、中毒、多人不适等食品安全风险；此类必须判为complaint和P0。"
                    "只有下单消息才能使用给定商品和单位，不得编造价格。"
                    "商品aliases是可识别别名，客户使用别名时仍必须返回对应商品product_id。"
                    "一条消息可能同时包含下单和投诉，此时必须同时提取订单items，并将intent设为order_and_complaint。"
                    "输出纯JSON：{intent:'order|complaint|order_and_complaint|query|other',confidence:0到1,"
                    "complaint_category:'食品安全|少货漏货|品质问题|重量问题|配送延迟|价格问题|服务问题|其他|null',"
                    "severity:'P0|P1|P2|null',delivery_date:'YYYY-MM-DD或null',"
                    "items:[{requested_name,product_id,unit_id,quantity,specification,remark}],notes}。"
                    "无法唯一匹配时product_id和unit_id填null。相对日期以今天为准。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "today": reference_date.isoformat(),
                        "customer": customer.name,
                        "customer_rules": customer.ai_reply_rules or "",
                        "message": content,
                        "catalog": catalog,
                    },
                    ensure_ascii=False,
                ),
            },
            ],
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ValueError("大模型未返回可解析订单")
        result = json.loads(match.group(0))
    except Exception as exc:
        result = _fallback_order_extract(catalog, content, reference_date, str(exc))
    deterministic_date = _delivery_date_from_text(content, reference_date)
    if deterministic_date:
        result["delivery_date"] = deterministic_date.isoformat()
    result["catalog"] = {product["id"]: product for product in catalog}
    return result


def _friendly_date(value: date | None) -> str:
    if not value:
        return "这次"
    today = date.today()
    if value == today:
        return "今天"
    if value == today + timedelta(days=1):
        return "明天"
    if value == today + timedelta(days=2):
        return "后天"
    return f"{value.month}月{value.day}日"


def _draft_reply(draft: WeComOrderDraft, salutation: str = "") -> str:
    item_texts = []
    pending = []
    for item in draft.items:
        customer_alias = next(
            (
                row.get("alias") for row in item.product.customer_aliases
                if int(row.get("customer_id", 0)) == draft.customer_id
            ),
            None,
        ) if item.product else None
        product_name = str(customer_alias or item.product.name) if item.product else item.requested_name
        unit_name = item.unit.name if item.unit else "单位待确认"
        item_texts.append(f"{product_name}{float(item.quantity):g}{unit_name}")
        if not item.matched:
            pending.append(product_name)
    prefix = f"{salutation}，" if salutation else ""
    summary = "、".join(item_texts)
    if draft.status == "awaiting_confirmation":
        return f"{prefix}收到，{_friendly_date(draft.delivery_date)}要{summary}，对吧？回复“确认”我就帮您下单。"
    pending_text = "、".join(pending)
    return f"{prefix}{_friendly_date(draft.delivery_date)}要{summary}，我先给您记下了。{pending_text}还需要订单员确认一下，我确认好马上回复您。"


def process_inbound_message(
    db: Session,
    *,
    msgid: str,
    external_userid: str,
    open_kfid: str,
    content: str,
    payload: dict | None = None,
    occurred_at: datetime | None = None,
) -> dict:
    existing = db.scalar(select(WeComMessage).where(WeComMessage.msgid == msgid))
    if existing:
        return {"status": "duplicate", "message_id": existing.id}
    binding = _binding(db, external_userid, open_kfid)
    message = WeComMessage(
        msgid=msgid,
        external_userid=external_userid,
        open_kfid=open_kfid,
        customer_id=binding.customer_id if binding else None,
        direction="inbound",
        msg_type=(payload or {}).get("msgtype", "text"),
        content=content,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
        occurred_at=occurred_at or datetime.now(),
    )
    db.add(message)
    db.flush()
    if not binding:
        message.intent = "unbound"
        message.status = "needs_binding"
        reply = "暂未识别到您的客户资料，请联系订单员完成微信绑定后再下单。"
        db.commit()
        send_text(external_userid, open_kfid, reply)
        return {"status": "needs_binding", "reply": reply}

    binding.last_seen_at = datetime.now()
    refresh_binding_profile(binding)
    customer = binding.customer
    salutation = _salutation(binding)
    normalized = content.strip().replace("！", "").replace("。", "")
    if normalized in {"确认", "确认下单", "提交订单"}:
        draft = _latest_order_draft(db, customer.id, external_userid)
        if not draft:
            reply = f"{salutation}，我这边没找到等您确认的订单，您把商品、数量和单位再发我一下就行。"
            message.intent = "confirm"
            message.status = "no_draft"
        else:
            try:
                order, merged = _confirm_draft(db, draft)
                action = "已加到原来的订单里" if merged else "已经下好啦"
                reply = f"{salutation}，{action}，单号是{order.order_no}，后面有变化直接跟我说。"
                message.intent = "confirm"
                message.status = "processed"
            except ValueError as exc:
                reply = str(exc)
                message.intent = "confirm"
                message.status = "needs_review"
        db.commit()
        send_text(external_userid, open_kfid, reply)
        return {"status": message.status, "reply": reply}

    complaint = None
    complaint_reply = ""
    complaint_category, severity = _complaint_category(content)
    if complaint_category:
        complaint, complaint_reply = _create_complaint(
            db, message=message, customer=customer, category=complaint_category, severity=severity,
            salutation=salutation,
        )

    try:
        parsed = _extract_order(
            db,
            customer,
            content,
            base_date=(message.occurred_at or datetime.now()).date(),
        )
        parsed_intent = parsed.get("intent")
        if parsed_intent in {"complaint", "order_and_complaint"} and not complaint:
            allowed_categories = set(COMPLAINT_KEYWORDS) | {"其他"}
            category = parsed.get("complaint_category")
            category = category if category in allowed_categories else "其他"
            parsed_severity = parsed.get("severity")
            severity = parsed_severity if parsed_severity in {"P0", "P1", "P2"} else "P2"
            if category == "食品安全":
                severity = "P0"
            complaint, complaint_reply = _create_complaint(
                db, message=message, customer=customer, category=category, severity=severity,
                salutation=salutation,
            )
        has_order = parsed_intent in {"order", "order_and_complaint"} and bool(parsed.get("items"))
        if not has_order:
            if complaint:
                send_text(external_userid, open_kfid, complaint_reply)
                return {
                    "status": "complaint_created",
                    "complaint_id": complaint.id,
                    "reply": complaint_reply,
                }
            message.intent = parsed_intent or "other"
            message.status = "needs_review"
            db.commit()
            handler = customer.order_clerk.name if customer.order_clerk else "订单员"
            reply = f"{salutation}，我看到啦。这条我先转给{handler}，有需要下单的话直接发商品、数量和单位就行。"
            send_text(external_userid, open_kfid, reply)
            return {"status": "needs_review", "reply": reply}
        delivery_date = None
        if parsed.get("delivery_date"):
            try:
                delivery_date = date.fromisoformat(parsed["delivery_date"])
            except ValueError:
                pass
        draft = WeComOrderDraft(
            customer_id=customer.id,
            assigned_to=customer.order_clerk_id,
            source_msgid=msgid,
            external_userid=external_userid,
            open_kfid=open_kfid,
            raw_message=content,
            delivery_date=delivery_date,
            confidence=Decimal(str(parsed.get("confidence") or 0)),
            parse_notes=str(parsed.get("notes") or "") or None,
        )
        all_matched = True
        for incoming in parsed.get("items", []):
            product_id = incoming.get("product_id")
            product = db.get(Product, product_id) if product_id else None
            unit_id = incoming.get("unit_id")
            unit = db.get(ProductUnit, unit_id) if unit_id else None
            matched = bool(product and unit and unit.product_id == product.id and incoming.get("quantity"))
            price = _unit_sales_price(product, unit) if matched else None
            matched = matched and price is not None
            all_matched = all_matched and matched
            draft.items.append(
                WeComOrderDraftItem(
                    requested_name=str(incoming.get("requested_name") or (product.name if product else "未识别商品")),
                    product_id=product.id if product else None,
                    unit_id=unit.id if unit and product and unit.product_id == product.id else None,
                    quantity=Decimal(str(incoming.get("quantity") or 0)),
                    unit_price=price,
                    specification=str(incoming.get("specification") or "") or None,
                    remark=str(incoming.get("remark") or "") or None,
                    matched=matched,
                )
            )
        draft.status = "awaiting_confirmation" if all_matched and float(draft.confidence) >= 0.8 else "needs_review"
        db.add(draft)
        message.intent = "order_and_complaint" if complaint else "order"
        message.status = draft.status
        db.commit()
        db.refresh(draft)
        order_reply = _draft_reply(draft, "" if complaint else salutation)
        reply = f"{complaint_reply}\n\n{order_reply}" if complaint else order_reply
        send_text(external_userid, open_kfid, reply)
        result = {"status": draft.status, "draft_id": draft.id, "reply": reply}
        if complaint:
            result.update(complaint_id=complaint.id, combined=True)
        return result
    except Exception as exc:
        message.intent = "order_and_complaint" if complaint else "order_or_query"
        message.status = "failed"
        db.commit()
        if complaint:
            reply = f"{complaint_reply}\n\n另外订单内容我还没完全认准，已经请订单员帮您核对。"
        else:
            handler = customer.order_clerk.name if customer.order_clerk else "订单员"
            reply = f"{salutation}，这条我没完全认准，已经请{handler}帮您看一下，确认好马上回复您。"
        send_text(external_userid, open_kfid, reply)
        result = {"status": "failed", "error": str(exc), "reply": reply}
        if complaint:
            result.update(complaint_id=complaint.id, combined=True)
        return result


def process_sync_event(db: Session, event: dict):
    event_token = event.get("Token") or event.get("token") or ""
    open_kfid = event.get("OpenKfId") or event.get("open_kfid") or ""
    if not event_token:
        return
    for item in sync_messages(event_token, open_kfid):
        if not item.get("external_userid") or item.get("origin") not in {None, 3}:
            continue
        msg_type = item.get("msgtype", "unknown")
        if msg_type == "text":
            content = (item.get("text") or {}).get("content", "")
        elif msg_type == "voice":
            voice = item.get("voice") or {}
            try:
                content = transcribe_voice(str(voice.get("media_id") or ""))
                item["voice_transcription"] = content
            except Exception as exc:
                content = f"[语音识别失败：{str(exc)[:120]}，需人工处理]"
        else:
            content = f"[{msg_type}消息，需人工查看]"
        send_time = item.get("send_time")
        occurred_at = datetime.fromtimestamp(send_time) if send_time else datetime.now()
        process_inbound_message(
            db,
            msgid=item.get("msgid") or uuid4().hex,
            external_userid=item["external_userid"],
            open_kfid=item.get("open_kfid") or open_kfid,
            content=content,
            payload=item,
            occurred_at=occurred_at,
        )
