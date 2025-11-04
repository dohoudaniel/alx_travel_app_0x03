#!/usr/bin/env python3
"""
Serializers for the listings app: ListingSerializer, BookingSerializer.
"""
from rest_framework import serializers
from .models import Listing, Booking, Payment


class ListingSerializer(serializers.ModelSerializer):
    """Serializer for Listing model."""

    host = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Listing
        fields = [
            "id",
            "host",
            "title",
            "description",
            "location",
            "price_per_night",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "host", "created_at", "updated_at"]


class BookingSerializer(serializers.ModelSerializer):
    """Serializer for Booking model."""

    listing = serializers.PrimaryKeyRelatedField(
        queryset=Listing.objects.all())
    guest = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "listing",
            "guest",
            "start_date",
            "end_date",
            "total_price",
            "status",
            "created_at",
        ]
        read_only_fields = ["id", "guest", "created_at"]


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = "__all__"
        read_only_fields = ("status", "chapa_tx_id", "metadata", "created_at", "updated_at")


class InitiatePaymentSerializer(serializers.Serializer):
    booking_reference = serializers.CharField(required=True)
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=True)
    currency = serializers.CharField(required=True)
    return_url = serializers.URLField(required=False, allow_blank=True)


class ChapaWebhookSerializer(serializers.Serializer):
    """
    Accepts Chapa webhook payloads. Chapa sometimes nests fields under `data`.
    We accept:
      - top-level 'tx_ref' or 'reference'
      - or nested under 'data': 'data': {'tx_ref': ..., 'reference': ..., 'status': ...}
    """
    # allow arbitrary nested JSON under 'data' so Swagger shows the field structure
    data = serializers.DictField(child=serializers.JSONField(), required=False)
    tx_ref = serializers.CharField(required=False, allow_blank=True)
    reference = serializers.CharField(required=False, allow_blank=True)
    status = serializers.CharField(required=False, allow_blank=True)
