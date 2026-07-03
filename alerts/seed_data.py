from .models import LeadFlag, MailboxAccount, MarketplaceAlert


STARTER_LEAD_FLAGS = (
    {
        "code": "inspection_request",
        "name": "Осмотр",
        "category": LeadFlag.Category.POSITIVE,
        "description": "Покупатель хочет посмотреть автомобиль лично.",
    },
    {
        "code": "test_drive",
        "name": "Тест-драйв",
        "category": LeadFlag.Category.POSITIVE,
        "description": "Покупатель спрашивает о пробной поездке.",
    },
    {
        "code": "today",
        "name": "Сегодня",
        "category": LeadFlag.Category.POSITIVE,
        "description": "Покупатель готов действовать сегодня или очень быстро.",
    },
    {
        "code": "vin_requested",
        "name": "VIN",
        "category": LeadFlag.Category.POSITIVE,
        "description": "Покупатель спрашивает VIN или Fahrgestellnummer.",
    },
    {
        "code": "tuv_question",
        "name": "TÜV / HU",
        "category": LeadFlag.Category.POSITIVE,
        "description": "Покупатель спрашивает про TÜV, HU или AU.",
    },
    {
        "code": "service_history",
        "name": "Сервисная история",
        "category": LeadFlag.Category.POSITIVE,
        "description": "Покупатель интересуется обслуживанием, Scheckheft или историей сервиса.",
    },
    {
        "code": "courier_shipping",
        "name": "Курьер / пересылка",
        "category": LeadFlag.Category.RISK,
        "description": "Сообщение содержит курьера, пересылку, Spedition или нетипичную доставку.",
    },
    {
        "code": "risky_payment",
        "name": "Рискованная оплата",
        "category": LeadFlag.Category.RISK,
        "description": "Упоминается предоплата, Western Union, PayPal Freunde или другой рискованный платёж.",
    },
    {
        "code": "external_messenger",
        "name": "Уход в мессенджер",
        "category": LeadFlag.Category.RISK,
        "description": "Покупатель пытается увести общение в WhatsApp, Telegram, Signal или телефон.",
    },
    {
        "code": "export_request",
        "name": "Экспорт",
        "category": LeadFlag.Category.RISK,
        "description": "Сообщение связано с экспортом или вывозом за границу.",
    },
    {
        "code": "last_price",
        "name": "Последняя цена",
        "category": LeadFlag.Category.LOW_QUALITY,
        "description": "Слабый запрос в стиле 'последняя цена'.",
    },
    {
        "code": "aggressive_bargain",
        "name": "Сильный торг",
        "category": LeadFlag.Category.LOW_QUALITY,
        "description": "Покупатель сразу предлагает сильное снижение цены.",
    },
    {
        "code": "odd_style",
        "name": "Странный стиль",
        "category": LeadFlag.Category.LOW_QUALITY,
        "description": "Сообщение выглядит подозрительно или неестественно.",
    },
)


def seed_lead_flags() -> tuple[int, int]:
    created_count = 0
    updated_count = 0

    for flag in STARTER_LEAD_FLAGS:
        _, created = LeadFlag.objects.update_or_create(
            code=flag["code"],
            defaults={
                "name": flag["name"],
                "category": flag["category"],
                "description": flag["description"],
                "is_active": True,
            },
        )
        if created:
            created_count += 1
        else:
            updated_count += 1

    return created_count, updated_count


def seed_demo_alerts() -> tuple[int, int]:
    flags_by_code = {flag.code: flag for flag in LeadFlag.objects.filter(is_active=True)}
    mailbox, _ = MailboxAccount.objects.update_or_create(
        email="local-demo@example.local",
        defaults={
            "name": "Local demo mailbox",
            "is_active": True,
            "gmail_search_query": "from:(kleinanzeigen.de)",
            "connection_status": MailboxAccount.ConnectionStatus.NOT_CONNECTED,
            "last_error": "",
        },
    )

    fixtures = (
        {
            "gmail_message_id": "dev-msg-001",
            "gmail_thread_id": "dev-thread-001",
            "buyer_name": "Max",
            "listing_title": "BMW 320d Touring",
            "listing_id": "123456789",
            "subject": 'Neue Nachricht von Max zu "BMW 320d Touring"',
            "message_text": "Ich kann heute zur Besichtigung kommen. Ist das Auto noch verfügbar?",
            "event_type": MarketplaceAlert.EventType.BUYER_MESSAGE,
            "alert_status": MarketplaceAlert.AlertStatus.UNREAD,
            "priority": MarketplaceAlert.Priority.HIGH,
            "parse_status": MarketplaceAlert.ParseStatus.SUCCESS,
            "classification_reason": "Найдены признаки: интерес к осмотру, готовность действовать сегодня.",
            "flag_codes": ("inspection_request", "today"),
        },
        {
            "gmail_message_id": "dev-msg-002",
            "gmail_thread_id": "dev-thread-002",
            "buyer_name": "Ivan",
            "listing_title": "Audi A4 Avant",
            "listing_id": "987654321",
            "subject": 'Neue Nachricht von Ivan zu "Audi A4 Avant"',
            "message_text": "Ich schicke einen Kurier zur Abholung und zahle per Überweisung vorab.",
            "event_type": MarketplaceAlert.EventType.BUYER_MESSAGE,
            "alert_status": MarketplaceAlert.AlertStatus.UNREAD,
            "priority": MarketplaceAlert.Priority.NORMAL,
            "parse_status": MarketplaceAlert.ParseStatus.SUCCESS,
            "classification_reason": "Есть risk flags: courier_shipping, risky_payment.",
            "flag_codes": ("courier_shipping", "risky_payment"),
        },
        {
            "gmail_message_id": "dev-msg-003",
            "gmail_thread_id": "dev-thread-003",
            "buyer_name": "Anna",
            "listing_title": "VW Golf GTI",
            "listing_id": "555777999",
            "subject": 'Neue Nachricht von Anna zu "VW Golf GTI"',
            "message_text": "Was letzter Preis???",
            "event_type": MarketplaceAlert.EventType.BUYER_MESSAGE,
            "alert_status": MarketplaceAlert.AlertStatus.IN_WORK,
            "priority": MarketplaceAlert.Priority.LOW,
            "parse_status": MarketplaceAlert.ParseStatus.SUCCESS,
            "classification_reason": "Найдены признаки: сообщение про последнюю цену, странный стиль сообщения.",
            "flag_codes": ("last_price", "odd_style"),
        },
    )

    created_count = 0
    updated_count = 0
    for fixture in fixtures:
        flag_codes = fixture["flag_codes"]
        defaults = {key: value for key, value in fixture.items() if key != "flag_codes"}
        alert, created = MarketplaceAlert.objects.update_or_create(
            mailbox=mailbox,
            gmail_message_id=fixture["gmail_message_id"],
            defaults={
                **defaults,
                "mailbox": mailbox,
                "raw_subject": fixture["subject"],
                "raw_body": fixture["message_text"],
                "normalized_body": fixture["message_text"],
                "parse_error": "",
            },
        )
        alert.flags.set([flags_by_code[code] for code in flag_codes if code in flags_by_code])
        if created:
            created_count += 1
        else:
            updated_count += 1

    return created_count, updated_count
