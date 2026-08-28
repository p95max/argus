from django.db import migrations


CLASSIFIER_FLAG_CODES = {
    "inspection_request",
    "test_drive",
    "today",
    "vin_requested",
    "tuv_question",
    "service_history",
    "installment_payment",
    "suspected_scam",
    "courier_shipping",
    "risky_payment",
    "external_messenger",
    "export_request",
    "last_price",
    "aggressive_bargain",
    "odd_style",
}


def reparse_direct_replies(apps, schema_editor):
    from alerts.parser import parse_kleinanzeigen_email

    LeadFlag = apps.get_model("alerts", "LeadFlag")
    MarketplaceAlert = apps.get_model("alerts", "MarketplaceAlert")

    scam_flag, _ = LeadFlag.objects.update_or_create(
        code="suspected_scam",
        defaults={
            "name": "🚨 Скам / поддержка",
            "category": "risk",
            "description": "Сильные признаки мошеннической схемы. Обращение следует отдельно проверить службе поддержки.",
            "is_active": True,
        },
    )

    flags_by_code = {
        flag.code: flag
        for flag in LeadFlag.objects.filter(code__in=CLASSIFIER_FLAG_CODES, is_active=True)
    }
    flags_by_code["suspected_scam"] = scam_flag

    for alert in MarketplaceAlert.objects.filter(event_type="system_notice").iterator():
        raw_body = alert.raw_body or alert.normalized_body or ""
        body_lower = raw_body.lower()
        if "mail.kleinanzeigen.de" not in body_lower or "kleinanzeigen" not in body_lower:
            continue

        parsed = parse_kleinanzeigen_email(
            alert.raw_subject or alert.subject or "",
            raw_body,
        )
        if parsed.event_type != "buyer_message":
            continue

        alert.flags.remove(*alert.flags.filter(code__in=CLASSIFIER_FLAG_CODES))
        matched_flags = [
            flags_by_code[code]
            for code in parsed.flag_codes
            if code in flags_by_code
        ]
        if matched_flags:
            alert.flags.add(*matched_flags)

        alert.event_type = parsed.event_type
        alert.parse_status = parsed.parse_status
        alert.parse_error = parsed.parse_error
        alert.listing_title = parsed.listing_title or alert.listing_title
        alert.listing_id = parsed.listing_id or alert.listing_id
        alert.buyer_name = parsed.buyer_name or alert.buyer_name
        alert.message_text = parsed.message_text
        alert.normalized_body = parsed.normalized_body
        alert.priority = parsed.priority
        alert.classification_reason = parsed.classification_reason
        alert.save(
            update_fields=[
                "event_type",
                "parse_status",
                "parse_error",
                "listing_title",
                "listing_id",
                "buyer_name",
                "message_text",
                "normalized_body",
                "priority",
                "classification_reason",
            ]
        )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0023_reclassify_compact_buyer_messages"),
    ]

    operations = [
        migrations.RunPython(reparse_direct_replies, noop_reverse),
    ]
