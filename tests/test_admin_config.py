from alerts.admin import MarketplaceAlertAdmin


def test_marketplace_alert_admin_has_event_type_filter():
    assert "event_type" in MarketplaceAlertAdmin.list_filter
