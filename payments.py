"""A simulated payment gateway. No real money moves and card details are never stored.

process() only checks the details and decides the outcome. The caller records the result.
Test values:
    card 4111 1111 1111 1111  -> success
    card 4000 0000 0000 0002  -> declined
    UPI  fail@upi             -> declined (any other name@bank succeeds)
    bank "Test bank (payment fails)" -> declined
"""
import re
from dataclasses import dataclass
from datetime import date

BANKS = ["State Bank of India", "HDFC Bank", "ICICI Bank", "Axis Bank", "Test bank (payment fails)"]
WALLETS = ["Paytm", "PhonePe", "Amazon Pay"]
METHODS = {"upi": "UPI", "card": "Card", "nb": "Net banking", "wl": "Wallet"}
DECLINED_CARD = "4000000000000002"
DECLINED_UPI = "fail@upi"


@dataclass
class Result:
    ok: bool
    method: str
    last4: str = ""
    message: str = ""
    declined: bool = False   # True: the simulated bank refused. False: the input was invalid.


def _luhn(number):
    total, flip = 0, False
    for ch in reversed(number):
        digit = int(ch)
        if flip:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
        flip = not flip
    return len(number) >= 13 and total % 10 == 0


def _bad(method, message):
    return Result(False, method, message=message)


def _expired(month, year):
    today = date.today()
    return (2000 + year, month) < (today.year, today.month)


def process(method, form):
    label = METHODS.get(method)
    if label is None:
        return _bad("", "Choose a payment method.")

    if method == "upi":
        upi = form.get("upi", "").strip()
        if not re.fullmatch(r"[\w.\-]{2,}@[a-zA-Z]{2,}", upi):
            return _bad(label, "Enter a valid UPI ID like name@bank.")
        if upi.lower() == DECLINED_UPI:
            return Result(False, label, message="The UPI payment was declined (demo).", declined=True)
        return Result(True, label)

    if method == "card":
        number = re.sub(r"\s", "", form.get("card_number", ""))
        expiry = re.fullmatch(r"(\d\d)/(\d\d)", form.get("card_expiry", "").strip())
        if not number.isdigit() or not _luhn(number):
            return _bad(label, "That card number is not valid.")
        if len(form.get("card_name", "").strip()) < 2:
            return _bad(label, "Enter the name on the card.")
        if not expiry or not 1 <= int(expiry[1]) <= 12 or _expired(int(expiry[1]), int(expiry[2])):
            return _bad(label, "Enter a valid expiry date that has not passed.")
        if not re.fullmatch(r"\d{3}", form.get("card_cvv", "")):
            return _bad(label, "Enter the 3-digit CVV.")
        last4 = number[-4:]
        if number == DECLINED_CARD:
            return Result(False, label, last4, "The card was declined by the bank (demo).", declined=True)
        return Result(True, label, last4)

    if method == "nb":
        bank = form.get("bank", "")
        if bank not in BANKS:
            return _bad(label, "Choose a bank to continue.")
        if bank.startswith("Test bank"):
            return Result(False, label, message="The bank could not complete the payment (demo).", declined=True)
        return Result(True, label)

    wallet = form.get("wallet", "")
    if wallet not in WALLETS:
        return _bad(label, "Choose a wallet to continue.")
    return Result(True, label)
