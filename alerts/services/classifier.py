from dataclasses import dataclass
import re

from ..models import MarketplaceAlert


@dataclass(frozen=True)
class ClassificationResult:
    priority: str
    flag_codes: tuple[str, ...]
    reason: str


BOILERPLATE_MARKERS = (
    "Beantworte diese Nachricht",
    "Schütze dich vor Betrug",
    "Dein Team von Kleinanzeigen",
    "Allgemeine Nutzungsbedingungen",
    "Datenschutzerklärung",
    "Impressum",
)


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
        "code": "installment_payment",
        "priority": MarketplaceAlert.Priority.NORMAL,
        "patterns": (
            r"\bratenzahlung\b",
            r"\bauf raten\b",
            r"\bin raten (?:zahlen|bezahlen)\b",
            r"\braten (?:zahlen|bezahlen)\b",
            r"\bmonatlich\s+\d+(?:[.,]\d+)?\s*€?\s*(?:zahlen|bezahlen)?\b",
            r"\bfinanzierung (?:möglich|machbar)\b",
            r"\bfinanzieren\b",
            r"\bрассроч",
            r"\bчастями\b",
        ),
        "reason": "запрос рассрочки/оплаты частями",
    },
    {
        "code": "suspected_scam",
        "priority": MarketplaceAlert.Priority.HIGH,
        "patterns": (
            r"\beurosender\b",
            r"\bnicht persönlich\b[\s\S]{0,350}\bspedition\b",
            r"\bim ausland\b[\s\S]{0,350}\büberweisung\b",
            r"\bspedition\b[\s\S]{0,250}\babholen\b",
            r"\bbevollmächtigt\b[\s\S]{0,250}\bkaufvertrag\b",
        ),
        "reason": "подозрение на скам — передать в службу поддержки",
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
        "patterns": (
            r"\bpaypal freunde\b",
            r"\bwestern union\b",
            r"\büberweisung vorab\b",
            r"\bvorkasse\b",
            r"\bper überweisung (?:zu )?zahlen\b",
        ),
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

RISK_FLAG_CODES = {
    "installment_payment",
    "suspected_scam",
    "courier_shipping",
    "risky_payment",
    "external_messenger",
    "export_request",
}
LOW_QUALITY_FLAG_CODES = {"last_price", "aggressive_bargain", "odd_style"}


def _compact_buyer_text(value: str) -> str:
    """Strip Kleinanzeigen wrapper text before classification."""
    text = " ".join(str(value or "").split())
    if not text:
        return ""

    patterns = (
        r"Antwort von\s+[^\s:]+\s+(.*?)(?=\s+Beantworte diese Nachricht|\s+Schütze dich vor Betrug|\s+Dein Team von Kleinanzeigen|$)",
        r"Nachricht von\s+[^\s:]+\s+(.*?)(?=\s+Beantworte diese Nachricht|\s+Schütze dich vor Betrug|\s+Dein Team von Kleinanzeigen|$)",
        r"(?:Nachricht|Message)\s*:\s*(.*?)(?=\s+Beantworte diese Nachricht|\s+Antworten\b|\s+Schütze dich vor Betrug|$)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.S)
        if match:
            candidate = match.group(1).strip(" -:·")
            if candidate:
                return candidate

    for marker in BOILERPLATE_MARKERS:
        position = text.lower().find(marker.lower())
        if position != -1:
            text = text[:position].strip()

    return text.strip(" -:·")


def classify_marketplace_message(text: str) -> ClassificationResult:
    normalized = _compact_buyer_text(text).lower()
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

    regular_reasons = [
        reason
        for code, reason in zip(matched_codes, matched_reasons)
        if code not in RISK_FLAG_CODES
    ]
    risk_pairs = [
        (code, reason)
        for code, reason in zip(matched_codes, matched_reasons)
        if code in RISK_FLAG_CODES
    ]
    if "suspected_scam" in matched_codes:
        risk_pairs = [pair for pair in risk_pairs if pair[0] == "suspected_scam"]
    risk_reasons = [reason for _, reason in risk_pairs]

    parts = []
    if regular_reasons:
        parts.append("Найдены признаки: " + ", ".join(regular_reasons) + ".")
    if risk_reasons:
        prefix = "🚩 Найден risk flag: " if len(risk_reasons) == 1 else "🚩 Найдены risk flags: "
        parts.append(prefix + ", ".join(risk_reasons) + ".")

    return ClassificationResult(
        priority=priority,
        flag_codes=tuple(dict.fromkeys(matched_codes)),
        reason=" ".join(parts),
    )
