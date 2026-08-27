from django.db import migrations


CLASSIFIER_FLAG_CODES = {
    "inspection_request",
    "test_drive",
    "today",
    "vin_requested",
    "tuv_question",
    "service_history",
    "installment_payment",
    "courier_shipping",
    "risky_payment",
    "external_messenger",
    "export_request",
    "last_price",
    "aggressive_bargain",
    "odd_style",
}


def reclassify_buyer_messages(apps, schema_editor):
    from alerts.classifier import classify_marketplace_message

    LeadFlag = apps.get_model("alerts", "LeadFlag")
    MarketplaceAlert = apps.get_model("alerts", "MarketplaceAlert")

    flags_by_code = {
        flag.code: flag
        for flag in LeadFlag.objects.filter(code__in=CLASSIFIER_FLAG_CODES, is_active=True)
    }

    for alert in MarketplaceAlert.objects.filter(event_type="buyer_message").iterator():
        result = classify_marketplace_message(alert.message_text or "")

        # Replace only classifier-managed flags. Any future/manual flags outside this
        # set are preserved.
        alert.flags.remove(*alert.flags.filter(code__in=CLASSIFIER_FLAG_CODES))
        matched_flags = [flags_by_code[code] for code in result.flag_codes if code in flags_by_code]
        if matched_flags:
            alert.flags.add(*matched_flags)

        alert.priority = result.priority
        alert.classification_reason = result.reason
        alert.save(update_fields=["priority", "classification_reason"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("alerts", "0021_installment_payment_flag"),
    ]

    operations = [
        migrations.RunPython(reclassify_buyer_messages, noop_reverse),
    ]
