# listings/tasks.py
from __future__ import absolute_import, unicode_literals
from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings

from .models import Payment, Booking
import logging

# from __future__ import absolute_import, unicode_literals
from django.template.loader import render_to_string
from django.utils import timezone
# from django.contrib.sites.models import Site


logger = logging.getLogger(__name__)

@shared_task
def send_payment_confirmation_email(payment_id):
    try:
        payment = Payment.objects.get(id=payment_id)
    except Payment.DoesNotExist:
        logger.error("Payment not found for email task: %s", payment_id)
        return

    subject = f"Payment confirmation for booking {payment.booking_reference}"
    message = f"""
    Hello,

    Your payment for booking {payment.booking_reference} has been received.
    Amount: {payment.amount} {payment.currency}
    Reference: {payment.tx_ref}
    Status: {payment.status}

    Thank you.
    """
    recipient = payment.user.email if payment.user and payment.user.email else None
    if not recipient:
        logger.error("No recipient email for payment %s", payment_id)
        return

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [recipient],
        fail_silently=False,
    )
    logger.info("Payment confirmation email sent for payment %s", payment_id)


@shared_task(bind=True)
def send_booking_confirmation(self, booking_id):
    # Import Site here to avoid module-level import errors during startup
    try:
        from django.contrib.sites.models import Site
        site = Site.objects.get_current()
    except Exception:
        site = None

    try:
        booking = Booking.objects.select_related("user", "listing").get(pk=booking_id)
    except Booking.DoesNotExist:
        return {"status": "error", "message": f"Booking {booking_id} does not exist"}

    # Build message (use site if available)
    if site:
        site_info = {"domain": getattr(site, "domain", ""), "name": getattr(site, "name", "")}
    else:
        site_info = {"domain": "localhost", "name": "Local"}

    # render templates safely
    try:
        message = render_to_string("emails/booking_confirmation.txt", {"booking": booking, "site": site_info})
        html_message = render_to_string("emails/booking_confirmation.html", {"booking": booking, "site": site_info})
    except Exception:
        message = f"Your booking #{booking.id} has been confirmed."
        html_message = None

    recipient = None
    if hasattr(booking, "user") and booking.user and booking.user.email:
        recipient = booking.user.email
    elif hasattr(booking, "guest_email") and booking.guest_email:
        recipient = booking.guest_email

    if not recipient:
        return {"status": "error", "message": "No recipient email found for booking"}

    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")

    send_mail(
        subject=f"Booking Confirmation - #{booking.id}",
        message=message,
        from_email=from_email,
        recipient_list=[recipient],
        fail_silently=False,
        html_message=html_message,
    )

    return {"status": "ok", "booking_id": booking_id}


# @shared_task(bind=True)
# @def send_booking_confirmation(self, booking_id):
#     """
#     Sends a booking confirmation email for booking with id=booking_id.
#    This runs in a Celery worker.
#    """
#    try:
#        booking = Booking.objects.select_related("user", "listing").get(pk=booking_id)
#    except Booking.DoesNotExist:
#        # Optionally retry or log
#        return {"status": "error", "message": f"Booking {booking_id} does not exist"}
#
#    # Build email content - adapt to your Booking model fields
#    site = Site.objects.get_current()
#    subject = f"Booking Confirmation - #{booking.id}"
#    # render a template if you have one (optional)
#    try:
#        message = render_to_string(
#            "emails/booking_confirmation.txt",
#            {"booking": booking, "site": site}
#        )
#        html_message = render_to_string(
#            "emails/booking_confirmation.html",
#            {"booking": booking, "site": site}
#        )
#    except Exception:
#        # Fallback plain text
#        message = f"Your booking #{booking.id} has been confirmed."
#        html_message = None
#
#    # Who to send to: use email on booking.user or booking.guest_email etc.
#    recipient = None
#    # adjust according to your Booking model fields
#    if hasattr(booking, "user") and booking.user and booking.user.email:
#        recipient = booking.user.email
#    elif hasattr(booking, "guest_email") and booking.guest_email:
#        recipient = booking.guest_email
#
#    if not recipient:
#        return {"status": "error", "message": "No recipient email found for booking"}
#
#    from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@example.com")
#
#    # send the email using Django email backend (console or SMTP)
#    send_mail(
#        subject=subject,
#        message=message,
#        from_email=from_email,
#        recipient_list=[recipient],
#        fail_silently=False,
#        html_message=html_message,
#    )
#
#    return {"status": "ok", "booking_id": booking_id}
