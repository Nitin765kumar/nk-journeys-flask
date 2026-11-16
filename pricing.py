"""Price calculation. The server always recalculates; it never trusts the browser's total.

All amounts are integers in paise. Percentages round half up.
"""
COUPONS = {"NKJ10": 10}      # coupon code -> percent off the trip fare
GST_PERCENT = 5
ADVANCE_PERCENT = 30
MAX_ADULTS = 8
MAX_CHILDREN = 4


def _percent(amount, percent):
    return (amount * percent + 50) // 100


def coupon_percent(code):
    return COUPONS.get((code or "").strip().upper(), 0)


def quote(price_rupees, adults, children, coupon="", pay_mode="full"):
    """Return the fare breakup for a package price (rupees per adult)."""
    unit = price_rupees * 100
    base = unit * adults + unit * children // 2          # children pay half fare
    discount = _percent(base, coupon_percent(coupon))
    gst = _percent(base - discount, GST_PERCENT)
    total = base - discount + gst
    pay_now = _percent(total, ADVANCE_PERCENT) if pay_mode == "advance" else total
    return {"base": base, "discount": discount, "gst": gst, "total": total, "pay_now": pay_now}
