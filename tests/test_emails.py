from unittest import mock

import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.templatetags.static import static
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from templated_email import get_connection

import saleor.account.emails as account_emails
import saleor.order.emails as emails
from saleor.core.emails import get_email_context
from saleor.core.utils import build_absolute_uri
from saleor.order.utils import add_variant_to_order


def test_get_email_context(site_settings):
    site = site_settings.site
    logo_url = build_absolute_uri(static("images/logo-light.svg"))

    expected_send_kwargs = {"from_email": site_settings.default_from_email}
    proper_context = {
        "domain": site.domain,
        "logo_url": logo_url,
        "site_name": site.name,
    }

    send_kwargs, received_context = get_email_context()
    assert send_kwargs == expected_send_kwargs
    assert proper_context == received_context


def test_collect_data_for_order_confirmation_email(order):
    """Order confirmation email requires extra data, which should be present
    in email's context.
    """
    template = emails.CONFIRM_ORDER_TEMPLATE
    email_data = emails.collect_data_for_email(order.pk, template)
    email_context = email_data["context"]
    assert email_context["order"] == order
    assert "schema_markup" in email_context


def test_collect_data_for_fullfillment_email(fulfilled_order):
    template = emails.CONFIRM_FULFILLMENT_TEMPLATE
    fulfillment = fulfilled_order.fulfillments.first()
    fulfillment_data = emails.collect_data_for_fullfillment_email(
        fulfilled_order.pk, template, fulfillment.pk
    )
    email_context = fulfillment_data["context"]
    assert email_context["fulfillment"] == fulfillment
    email_data = emails.collect_data_for_email(fulfilled_order.pk, template)
    assert all([key in email_context for key, item in email_data["context"].items()])


def test_collect_data_for_email(order):
    template = emails.CONFIRM_PAYMENT_TEMPLATE
    email_data = emails.collect_data_for_email(order.pk, template)
    email_context = email_data["context"]
    # This properties should be present only for order confirmation email
    assert "schema_markup" not in email_context


@pytest.mark.parametrize(
    "send_email,template",
    [
        (emails.send_payment_confirmation, emails.CONFIRM_PAYMENT_TEMPLATE),
        (emails.send_order_confirmation, emails.CONFIRM_ORDER_TEMPLATE),
    ],
)
@mock.patch("saleor.order.emails.send_templated_mail")
def test_send_emails(
    mocked_templated_email, order, template, send_email, site_settings
):
    send_email(order.pk)
    email_data = emails.collect_data_for_email(order.pk, template)

    recipients = [order.get_customer_email()]

    expected_call_kwargs = {
        "context": email_data["context"],
        "from_email": site_settings.default_from_email,
        "template_name": template,
    }

    mocked_templated_email.assert_called_once_with(
        recipient_list=recipients, **expected_call_kwargs
    )

    # Render the email to ensure there is no error
    email_connection = get_connection()
    email_connection.get_email_message(to=recipients, **expected_call_kwargs)


@mock.patch("saleor.order.emails.send_templated_mail")
def test_send_staff_emails_without_notification_recipient(
    mocked_templated_email, order, site_settings
):
    emails.send_staff_order_confirmation(order.pk)
    mocked_templated_email.assert_not_called()


@mock.patch("saleor.order.emails.send_templated_mail")
def test_send_staff_emails(
    mocked_templated_email, order, site_settings, staff_notification_recipient
):
    emails.send_staff_order_confirmation(order.pk)
    email_data = emails.collect_staff_order_notification_data(
        order.pk, emails.STAFF_CONFIRM_ORDER_TEMPLATE
    )

    recipients = [staff_notification_recipient.get_email()]

    expected_call_kwargs = {
        "context": email_data["context"],
        "from_email": site_settings.default_from_email,
        "template_name": emails.STAFF_CONFIRM_ORDER_TEMPLATE,
    }

    mocked_templated_email.assert_called_once_with(
        recipient_list=recipients, **expected_call_kwargs
    )

    # Render the email to ensure there is no error
    email_connection = get_connection()
    email_connection.get_email_message(to=recipients, **expected_call_kwargs)


@pytest.mark.parametrize(
    "send_email,template",
    [
        (emails.send_payment_confirmation, emails.CONFIRM_PAYMENT_TEMPLATE),
        (emails.send_order_confirmation, emails.CONFIRM_ORDER_TEMPLATE),
    ],
)
@mock.patch("saleor.order.emails.send_templated_mail")
def test_send_confirmation_emails_without_addresses(
    mocked_templated_email, order, template, send_email, site_settings, digital_content
):

    assert not order.lines.count()

    add_variant_to_order(order, digital_content.product_variant, quantity=1)
    order.shipping_address = None
    order.shipping_method = None
    order.billing_address = None
    order.save(update_fields=["shipping_address", "shipping_method", "billing_address"])

    send_email(order.pk)
    email_data = emails.collect_data_for_email(order.pk, template)

    recipients = [order.get_customer_email()]

    expected_call_kwargs = {
        "context": email_data["context"],
        "from_email": site_settings.default_from_email,
        "template_name": template,
    }

    mocked_templated_email.assert_called_once_with(
        recipient_list=recipients, **expected_call_kwargs
    )

    # Render the email to ensure there is no error
    email_connection = get_connection()
    email_connection.get_email_message(to=recipients, **expected_call_kwargs)


@pytest.mark.parametrize(
    "send_email,template",
    [
        (
            emails.send_fulfillment_confirmation,
            emails.CONFIRM_FULFILLMENT_TEMPLATE,
        ),  # noqa
        (emails.send_fulfillment_update, emails.UPDATE_FULFILLMENT_TEMPLATE),
    ],
)
@mock.patch("saleor.order.emails.send_templated_mail")
def test_send_fulfillment_emails(
    mocked_templated_email, template, send_email, fulfilled_order, site_settings
):
    fulfillment = fulfilled_order.fulfillments.first()
    send_email(order_pk=fulfilled_order.pk, fulfillment_pk=fulfillment.pk)
    email_data = emails.collect_data_for_fullfillment_email(
        fulfilled_order.pk, template, fulfillment.pk
    )

    recipients = [fulfilled_order.get_customer_email()]

    expected_call_kwargs = {
        "context": email_data["context"],
        "from_email": site_settings.default_from_email,
        "template_name": template,
    }

    mocked_templated_email.assert_called_once_with(
        recipient_list=recipients, **expected_call_kwargs
    )

    # Render the email to ensure there is no error
    email_connection = get_connection()
    email_connection.get_email_message(to=recipients, **expected_call_kwargs)


def test_email_having_display_name_in_settings(customer_user, site_settings, settings):
    expected_from_email = "Info <hello@mirumee.com>"

    site_settings.default_mail_sender_name = None
    site_settings.default_mail_sender_address = None

    settings.DEFAULT_FROM_EMAIL = expected_from_email

    assert site_settings.default_from_email == expected_from_email


def test_send_dummy_email_with_utf_8(customer_user, site_settings):
    site_settings.default_mail_sender_address = "hello@example.com"
    site_settings.default_mail_sender_name = "徐 欣"
    site_settings.save(
        update_fields=["default_mail_sender_address", "default_mail_sender_name"]
    )

    account_emails.send_account_delete_confirmation_email(customer_user)

    assert len(mail.outbox) > 0
    message: mail.EmailMessage = mail.outbox[-1]
    assert message.from_email == "徐 欣 <hello@example.com>"
    assert message.extra_headers == {}


@pytest.mark.parametrize(
    "sender_name, sender_address",
    (("徐 欣", "hello@example.com\nOopsie: Hello"), ("徐\n欣", "hello@example.com")),
)
def test_send_dummy_email_with_header_injection(
    customer_user, site_settings, sender_name, sender_address
):
    site_settings.default_mail_sender_address = sender_name
    site_settings.default_mail_sender_name = sender_address
    site_settings.save(
        update_fields=["default_mail_sender_address", "default_mail_sender_name"]
    )

    account_emails.send_account_delete_confirmation_email(customer_user)
    assert len(mail.outbox) == 0


def test_email_with_email_not_configured_raises_error(settings, site_settings):
    """Ensure an exception is thrown when not default sender is set;
    both missing in the settings.py and in the site settings table.
    """
    site_settings.default_mail_sender_address = None
    settings.DEFAULT_FROM_EMAIL = None

    with pytest.raises(ImproperlyConfigured) as exc:
        _ = site_settings.default_from_email

    assert exc.value.args == ("No sender email address has been set-up",)


def test_send_set_password_email(staff_user, site_settings):
    uid = urlsafe_base64_encode(force_bytes(staff_user.pk))
    token = default_token_generator.make_token(staff_user)
    password_set_url = build_absolute_uri(
        reverse(
            "account:reset-password-confirm", kwargs={"token": token, "uidb64": uid}
        )
    )
    template_name = "dashboard/staff/set_password"
    recipient_email = staff_user.email

    account_emails._send_set_password_email(
        recipient_email, password_set_url, template_name
    )

    assert len(mail.outbox) == 1
    generated_link = reverse(
        "account:reset-password-confirm", kwargs={"uidb64": uid, "token": token}
    )
    absolute_generated_link = build_absolute_uri(generated_link)
    sended_message = mail.outbox[0].body
    assert absolute_generated_link in sended_message
