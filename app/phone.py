"""Mobile-number handling for payments.

Cashfree's Orders API rejects an order when customer_details.customer_phone
is missing, so every paying user needs a mobile number on their account.
Numbers are stored as plain 10-digit Indian mobiles (no +91, no spaces).
"""
import re


def normalize_phone(raw) -> str | None:
    """Return the 10-digit mobile, or None when the input is not usable."""
    if raw is None:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    elif digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]
    if len(digits) != 10 or not digits.isdigit():
        return None
    return digits
