from django.shortcuts import render

# Create your views here.
import os
import requests
import uuid
import logging
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, viewsets
from .models import Payment, Booking
from .serializers import PaymentSerializer, BookingSerializer, InitiatePaymentSerializer, ChapaWebhookSerializer
from .tasks import send_payment_confirmation_email  # celery task
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view, action
from .tasks import send_booking_confirmation
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi


logger = logging.getLogger(__name__)


CHAPA_BASE = getattr(settings, "CHAPA_BASE_URL", "https://api.chapa.co/v1")
CHAPA_INIT_ENDPOINT = f"{CHAPA_BASE}/transaction/initialize"
CHAPA_VERIFY_ENDPOINT = f"{CHAPA_BASE}/transaction/verify"  # append /{tx_ref}


class InitiatePaymentView(APIView):
    permission_classes = [permissions.AllowAny]  # adjust as needed

    @swagger_auto_schema(request_body=InitiatePaymentSerializer,
                         responses={
                             200: openapi.Response(
                                 description="Init successful",
                                 schema=openapi.Schema(
                                     type=openapi.TYPE_OBJECT,
                                     properties={
                                         "checkout_url": openapi.Schema(type=openapi.TYPE_STRING, description="URL to complete payment"),
                                         "tx_ref": openapi.Schema(type=openapi.TYPE_STRING),
                                         "payment_id": openapi.Schema(type=openapi.TYPE_INTEGER),
                                         "raw": openapi.Schema(type=openapi.TYPE_OBJECT),
                                     }
                                 )
                             ),
                             400: "Bad Request",
                             502: "Payment initialization failed"
                         })
    def post(self, request):
        """
        Create a Payment record and call Chapa to initialize a transaction.
        Expected payload: { booking_reference, amount, currency, return_url (optional) }
        """
        # Use the serializer for validation + parsing
        serializer = InitiatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booking_reference = data.get("booking_reference") or f"booking-{uuid.uuid4().hex[:8]}"
        amount = data["amount"]
        currency = data.get("currency", "ETB")
        return_url = data.get("return_url")
        customer_email = request.user.email if request.user.is_authenticated else request.data.get("email")

        # create unique tx_ref
        tx_ref = f"{booking_reference}-{uuid.uuid4().hex}"

        payment = Payment.objects.create(
            user=request.user if request.user.is_authenticated else None,
            booking_reference=booking_reference,
            amount=amount,
            currency=currency,
            tx_ref=tx_ref,
            status="PENDING",
        )

        payload = {
            "tx_ref": tx_ref,
            "amount": float(amount),
            "currency": currency,
            "email": customer_email,
            "first_name": request.data.get("first_name", ""),
            "last_name": request.data.get("last_name", ""),
        }

        if return_url:
            payload["return_url"] = return_url

        callback_url = request.data.get("callback_url")
        if callback_url:
            payload["callback_url"] = callback_url

        headers = {
            "Authorization": f"Bearer {settings.CHAPA_SECRET_KEY}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(CHAPA_INIT_ENDPOINT, json=payload, headers=headers, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.exception("Chapa initialize failed")
            payment.mark_failed(reason=str(e))
            return Response({"detail": "Payment initialization failed", "error": str(e)}, status=502)

        body = resp.json()
        payment.metadata = body
        chapa_tx_id = body.get("data", {}).get("id") or body.get("data", {}).get("tx_id") or body.get("data", {}).get("reference")
        checkout_url = body.get("data", {}).get("checkout_url") or body.get("data", {}).get("payment_link")

        if chapa_tx_id:
            payment.chapa_tx_id = chapa_tx_id
        payment.save(update_fields=["chapa_tx_id", "metadata", "updated_at"])

        return Response({
            "checkout_url": checkout_url,
            "tx_ref": tx_ref,
            "payment_id": payment.id,
            "raw": body
        }, status=status.HTTP_200_OK)


class VerifyPaymentView(APIView):
    permission_classes = [permissions.AllowAny]  # you may restrict to your internal services

    def get(self, request, tx_ref):
        """
        Query Chapa verify endpoint and update Payment status.
        """
        try:
            payment = Payment.objects.get(tx_ref=tx_ref)
        except Payment.DoesNotExist:
            return Response({"detail": "Payment not found"}, status=status.HTTP_404_NOT_FOUND)

        headers = {
            "Authorization": f"Bearer {settings.CHAPA_SECRET_KEY}"
        }
        url = f"{CHAPA_VERIFY_ENDPOINT}/{tx_ref}"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            logger.exception("Chapa verify failed")
            return Response({"detail": "verify failed", "error": str(e)}, status=502)

        body = resp.json()
        # The response should include success & status
        status_data = body.get("data", {}).get("status") or body.get("message")
        chapa_reference = body.get("data", {}).get("reference") or body.get("data", {}).get("tx_ref")

        payment.metadata = {**(payment.metadata or {}), "verify_response": body}

        if status_data and str(status_data).lower() in ("successful", "success", "completed", "paid"):
            payment.mark_completed(chapa_tx_id=chapa_reference, extra={"verify_response": body})
            # kick off email send asynchronously
            try:
                send_payment_confirmation_email.delay(payment.id)
            except Exception:
                logger.exception("Could not enqueue confirmation email")
            return Response({"detail": "Payment completed", "payment_status": payment.status}, status=200)
        else:
            payment.mark_failed(reason=body.get("message") or "not successful")
            return Response({"detail": "Payment not successful", "raw": body, "payment_status": payment.status}, status=200)


@csrf_exempt
@swagger_auto_schema(
    method='post',
    request_body=ChapaWebhookSerializer,
    responses={
        200: openapi.Response(description="Webhook processed"),
        201: openapi.Response(description="Created/Processed"),
        400: "Bad Request",
        404: "Payment not found",
    },
)
@api_view(["POST"])
def chapa_webhook(request):
    """
    Endpoint to receive Chapa callback (if you configured callback_url on init).
    This implementation:
     - accepts JSON payloads,
     - looks for tx_ref/reference in several common places,
     - verifies a Payment with that tx_ref and marks it completed/failed.
    """

    payload = request.data or {}
    # Try multiple locations where chapa may put the reference:
    tx_ref = (
        payload.get("tx_ref")
        or payload.get("reference")
        or (payload.get("data") or {}).get("tx_ref")
        or (payload.get("data") or {}).get("reference")
        or request.GET.get("reference")
        or request.GET.get("tx_ref")
    )

    if not tx_ref:
        # return the same shape swagger currently expects for errors
        return Response({"detail": "tx_ref missing"}, status=400)

    # optional: allow simple status lookup from payload
    status_from_payload = (
        (payload.get("data") or {}).get("status")
        or payload.get("status")
        or payload.get("message")
    )

    # find the payment and update
    try:
        payment = Payment.objects.get(tx_ref=tx_ref)
    except Payment.DoesNotExist:
        return Response({"detail": "Payment not found"}, status=404)

    # Recommended: if you want to be strict, call verify endpoint here.
    # For now: rely on webhook's status field if present.
    try:
        if status_from_payload and str(status_from_payload).lower() in ("successful", "success", "completed", "paid"):
            payment.mark_completed(chapa_tx_id=(payload.get("data") or {}).get("reference") or payment.chapa_tx_id, extra={"webhook": payload})
            # async email
            try:
                send_payment_confirmation_email.delay(payment.id)
            except Exception:
                logger.exception("Could not enqueue confirmation email")
        else:
            # treat everything else as failed (or you can inspect other statuses)
            payment.mark_failed(reason=f"Webhook status: {status_from_payload}", extra={"webhook": payload})
    except Exception as exc:
        logger.exception("Error while updating payment from webhook: %s", exc)
        return Response({"detail": "internal error processing webhook", "error": str(exc)}, status=500)

    return Response({"ok": True, "tx_ref": tx_ref}, status=201)


class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer

    def perform_create(self, serializer):
        # Save booking instance
        booking = serializer.save()
        # Trigger the asynchronous email task
        try:
            send_booking_confirmation.delay(booking.id)
        except Exception as exc:
            # If the broker is down, decide how to handle: log, set flag, or fallback to immediate send
            # Example: log the exception and continue
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Failed to dispatch booking confirmation task: %s", exc)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = serializer.save()
        send_booking_confirmation.delay(booking.id)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class PaymentViewSet(viewsets.ViewSet):
    @swagger_auto_schema(
        method='post',
        request_body=InitiatePaymentSerializer,
        responses={
            201: openapi.Response('Created', schema=openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'tx_ref': openapi.Schema(type=openapi.TYPE_STRING)
                }
            )),
            400: 'Bad Request'
        }
    )
    @action(detail=False, methods=['post'], url_path='initiate')
    def initiate(self, request):
        serializer = InitiatePaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        # ... your existing logic to create Payment and call Chapa ...
        return Response({'tx_ref': 'abc123'}, status=status.HTTP_201_CREATED)
