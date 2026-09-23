"""OTP (One-Time Password) verification for registration."""
import random
import string
from datetime import timedelta

from django.utils import timezone
from .models import OTPVerification


OTP_LENGTH = 6
OTP_EXPIRY_MINUTES = 10


def generate_otp():
    """Generate a random 6-digit OTP code."""
    return ''.join(random.choices(string.digits, k=OTP_LENGTH))


def send_otp(identifier, channel):
    """
    Send OTP to email or phone.

    Args:
        identifier: Email address or phone number
        channel: "email" or "phone"

    Returns:
        OTPVerification object if successful, None otherwise
    """
    # Generate or get existing OTP
    otp_code = generate_otp()
    expires_at = timezone.now() + timedelta(minutes=OTP_EXPIRY_MINUTES)

    # Create or update OTP record
    otp_obj, created = OTPVerification.objects.update_or_create(
        identifier=identifier,
        channel=channel,
        defaults={
            "code": otp_code,
            "verified": False,
            "expires_at": expires_at,
        }
    )

    # TODO: Implement actual email/SMS sending
    # For now, this is a placeholder that would integrate with email/SMS services
    if channel == "email":
        # Send via email
        # from django.core.mail import send_mail
        # send_mail(
        #     "Your Music ConnectZ Verification Code",
        #     f"Your verification code is: {otp_code}\n\nThis code expires in {OTP_EXPIRY_MINUTES} minutes.",
        #     "noreply@musicconnectz.com",
        #     [identifier],
        # )
        pass
    elif channel == "phone":
        # Send via SMS
        # from twilio.rest import Client
        # client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        # client.messages.create(
        #     body=f"Your Music ConnectZ verification code is: {otp_code}",
        #     from_=settings.TWILIO_PHONE_NUMBER,
        #     to=identifier,
        # )
        pass

    return otp_obj


def verify_otp(identifier, channel, code):
    """
    Verify an OTP code.

    Args:
        identifier: Email address or phone number
        channel: "email" or "phone"
        code: The OTP code to verify

    Returns:
        Tuple (success: bool, message: str)
    """
    try:
        otp_obj = OTPVerification.objects.get(
            identifier=identifier,
            channel=channel,
        )
    except OTPVerification.DoesNotExist:
        return False, "No verification code found for this identifier."

    # Check if expired
    if timezone.now() > otp_obj.expires_at:
        otp_obj.delete()
        return False, "Verification code has expired. Please request a new one."

    # Check if code matches
    if otp_obj.code != code:
        return False, "Verification code is incorrect."

    # Mark as verified
    otp_obj.verified = True
    otp_obj.save(update_fields=["verified"])

    return True, "Verified successfully."


def is_verified(identifier, channel):
    """
    Check if an identifier has been verified via OTP.

    Args:
        identifier: Email address or phone number
        channel: "email" or "phone"

    Returns:
        True if verified and not expired, False otherwise
    """
    try:
        otp_obj = OTPVerification.objects.get(
            identifier=identifier,
            channel=channel,
            verified=True,
        )
        # Check if not expired
        if timezone.now() <= otp_obj.expires_at:
            return True
        else:
            otp_obj.delete()
            return False
    except OTPVerification.DoesNotExist:
        return False


def cleanup_verified(identifier, channel):
    """
    Clean up a verified OTP record after account creation.

    Args:
        identifier: Email address or phone number
        channel: "email" or "phone"
    """
    try:
        otp_obj = OTPVerification.objects.get(
            identifier=identifier,
            channel=channel,
        )
        otp_obj.delete()
    except OTPVerification.DoesNotExist:
        pass
