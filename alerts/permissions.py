def can_manage_mailboxes(user):
    return user.is_active and (
        user.is_superuser
        or (
            user.has_perm("alerts.add_mailboxaccount")
            and user.has_perm("alerts.change_mailboxaccount")
            and user.has_perm("alerts.delete_mailboxaccount")
        )
    )


def can_view_mailbox_operations(user):
    return user.is_active and user.is_staff
