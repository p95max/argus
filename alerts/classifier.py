from dataclasses import dataclass
import re

from .models import MarketplaceAlert


@dataclass(frozen=True)
class ClassificationResult:
    priority: str
    flag_codes: tuple[str, ...]
    reason: str


CLASSIFICATION_RULES = (
    {
        "code": "inspection_request",
        "priority": MarketplaceAlert.Priority.HIGH,
        "patterns": (r"\bbesichtigung\b", r"\banschauen\b", r"\bbesichtigen\b", r"\bvorbeikommen\b"),
        "reason": "интерес к осмотру",
    },
    {
        "code": "test_drive",
        "priority": MarketplaceAlert.Priority.HIGH,
        "patterns": (r"\bprobefahrt\b", r"\btestfahrt\b"),
        "reason": "интерес к тест-драйву",
    },
    {
        "code": "today",
        "priority": MarketplaceAlert.Priority.HIGH,
        "patterns": (r"\bheute\b", r"\bsofort\b", r"\bgleich\b"),
        "reason": "готовность действовать сегодня",
    },
    {
        "code": "vin_requested",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\bvin\b", r"\bfahrgestellnummer\b"),
        "reason": "запрос VIN",
    },
    {
        "code": "tuv_question",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\btüv\b", r"\btuv\b", r"\bhu\b", r"\bau\b"),
        "reason": "вопрос про TÜV/HU/AU",
    },
    {
        "code": "service_history",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\bscheckheft\b", r"\bserviceheft\b", r"\bservice historie\b", r"\bwartung\b"),
        "reason": "интерес к сервисной истории",
    },
    {
        "code": "courier_shipping",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\bkurier\b", r"\bspedition\b", r"\babholung durch\b", r"\bversand\b"),
        "reason": "упоминание курьера/пересылки",
    },
    {
        "code": "risky_payment",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\bpaypal freunde\b", r"\bwestern union\b", r"\büberweisung vorab\b", r"\bvorkasse\b"),
        "reason": "рискованный способ оплаты",
    },
    {
        "code": "external_messenger",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\bwhatsapp\b", r"\btelegram\b", r"\bsignal\b", r"\bhandynummer\b"),
        "reason": "уход во внешний мессенджер",
    },
    {
        "code": "export_request",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (r"\bexport\b", r"\bausfuhr\b", r"\bins ausland\b", r"\babholung im ausland\b"),
        "reason": "экспорт/вывоз",
    },
    {
        "code": "last_price",
        "priority": MarketplaceAlert.Priority.LOW,
        "patterns": (r"\bletzte preis\b", r"\bletzter preis\b", r"\bwas letzte\b", r"\bfinal price\b"),
        "reason": "сообщение про последнюю цену",
    },
    {
        "code": "aggressive_bargain",
        "priority": MarketplaceAlert.Priority.LOW,
        "patterns": (r"\bhalber preis\b", r"\b50 ?%\b", r"\bzu teuer\b", r"\bnehme für\b"),
        "reason": "сильный торг",
    },
    {
        "code": "odd_style",
        "priority": MarketplaceAlert.Priority.LOW,
        "patterns": (r"!!!{2,}", r"\?\?\?{1,}", r"\bdringend geld\b"),
        "reason": "странный стиль сообщения",
    },
)

RISK_FLAG_CODES = {"courier_shipping", "risky_payment", "external_messenger", "export_request"}
LOW_QUALITY_FLAG_CODES = {"last_price", "aggressive_bargain", "odd_style"}


def classify_marketplace_message(text: str) -> ClassificationResult:
    normalized = (text or "").lower()
    matched_codes = []
    matched_reasons = []
    matched_priorities = []

    for rule in CLASSIFICATION_RULES:
        if any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in rule["patterns"]):
            matched_codes.append(rule["code"])
            matched_reasons.append(rule["reason"])
            matched_priorities.append(rule["priority"])

    priority = MarketplaceAlert.Priority.NORMAL
    if any(item == MarketplaceAlert.Priority.HIGH for item in matched_priorities):
        priority = MarketplaceAlert.Priority.HIGH
    elif matched_codes and all(code in LOW_QUALITY_FLAG_CODES for code in matched_codes):
        priority = MarketplaceAlert.Priority.LOW

    if not matched_codes:
        return ClassificationResult(
            priority=priority,
            flag_codes=(),
            reason="Правила классификации не нашли сильных сигналов.",
        )

    reason = "Найдены признаки: " + ", ".join(matched_reasons) + "."
    risk_codes = [code for code in matched_codes if code in RISK_FLAG_CODES]
    if risk_codes:
        reason += " Есть risk flags: " + ", ".join(risk_codes) + "."

    return ClassificationResult(
        priority=priority,
        flag_codes=tuple(dict.fromkeys(matched_codes)),
        reason=reason,
    )
