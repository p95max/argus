import re

from django.db import migrations


INSTALLMENT_PATTERNS = (
    r"\bratenzahlung\b",
    r"\bauf raten\b",
    r"\bin raten (?:zahlen|bezahlen)\b",
    r"\braten (?:zahlen|bezahlen)\b",
    r"\bmonatlich\s+\d+(?:[.,]\d+)?\s*€?\s*(?:zahlen|bezahlen)?\b",
    r"\bfinanzierung (?:möglich|machbar)\b",
    r"\bfinanzieren\b",
    r"\bрассроч",
    r"\bчастями\b",
)


def add_installment_flag(apps, schema_editor):
    LeadFlag = apps.get_model("alerts", "LeadFlag")
    MarketplaceAlert = apps.get_model("alerts", "MarketplaceAlert")

    flag, _ = LeadFlag.objects.update_or_create(
        code="installment_payment",
        defaults={
            "name": "Рассрочка",
            "category": "risk",
            "description": "Покупатель просит оплату автомобиля в рассрочку или частями.",
            "is_active": True,
        },
    )

    for alert in MarketplaceAlert.objects.filter(event_type="buyer_message").iterator():
        text = (alert.message_text or "").lower()
        if not any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in INSTALLMENT_PATTERNS):
            continue

        alert.flags.add(flag)
        reason = alert.classification_reason or ""
        marker = "запрос рассрочки/оплаты частями"
        if marker not in reason.lower():
            if reason and not reason.endswith(" "):
                reason += " "
            reason += "Найден risk flag: запрос рассрочки/оплаты частями."
            alert.classification_reason = reason
            alert.save(update_fields=["classification_reason"])


def remove_installment_flag(apps, schema_editor):
    LeadFlag = apps.get_model("alerts", "LeadFlag")
    LeadFlag.objects.filter(code="installment_payment").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0020_adminloginlog_access_log_details"),
    ]

    operations = [
        migrations.RunPython(add_installment_flag, remove_installment_flag),
    ]
