"""Turning the timeline into something you can work with.

Trade Republic replaced the timeline in 2024. Two things changed for anyone
who processed it:

* The events themselves became structured. Where the old format carried a
  German sentence in ``body`` and a number in ``cashChangeAmount``, an event
  now has ``eventType``, ``status`` and ``amount``.

* The details went the other way. ``timelineDetailV2`` no longer describes a
  transaction, it describes a screen: a list of ``sections``, most of them
  tables whose rows are a label and a rendered value. The share count of a
  trade is not a field any more, it is the row labelled "Anteile".

So the values have to be read out of labelled rows. :data:`LABELS` says which
labels to look for and is the one place to touch when Trade Republic renames
something or you run the API in another language.
"""

import csv
import re
from collections import OrderedDict
from datetime import datetime
from decimal import Decimal, InvalidOperation

__all__ = [
    "LABELS",
    "EVENT_TYPES",
    "Transaction",
    "detail_documents",
    "detail_isin",
    "detail_row",
    "detail_rows",
    "parse_decimal",
    "parse_timestamp",
    "sections_of",
    "transaction_of",
    "write_csv",
]


# ---------------------------------------------------------------- parsing

_NUMBER = re.compile(r"-?\d[\d.,\s ']*\d|-?\d")


def parse_decimal(text, decimal_separator=","):
    """Reads the number out of a rendered value.

    The API delivers values the way they are shown, so they carry a currency
    symbol, grouping and a locale specific decimal separator.

    >>> parse_decimal("1.234,56 EUR")
    Decimal('1234.56')
    >>> parse_decimal("1,234.56", decimal_separator=".")
    Decimal('1234.56')

    :param text: the rendered value
    :param decimal_separator: "," for German output, "." for English
    :return: the number, or None when there is none
    """
    if text is None:
        return None
    if isinstance(text, (int, float, Decimal)):
        return Decimal(str(text))

    match = _NUMBER.search(str(text))
    if not match:
        return None

    number = re.sub(r"[\s ']", "", match.group(0))
    grouping = "." if decimal_separator == "," else ","
    number = number.replace(grouping, "")
    number = number.replace(decimal_separator, ".")

    try:
        return Decimal(number)
    except InvalidOperation:
        return None


def parse_timestamp(value):
    """Reads an event timestamp.

    The timeline switched from milliseconds since the epoch to an ISO string,
    so both are accepted.

    :return: a datetime, or None when the value makes no sense
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000.0)

    text = str(value).strip()
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000.0)

    # "2026-08-13T09:41:02.123+0000" - Python wants the colon in the offset
    # and cannot do more than six digits of fraction.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


# ------------------------------------------------------------- detail access

def sections_of(detail, section_type=None):
    """The sections of a timelineDetailV2 response.

    :param section_type: only sections of this type, e.g. "table"
    """
    if not isinstance(detail, dict):
        return []
    sections = detail.get("sections") or []
    if not isinstance(sections, list):
        return []
    sections = [s for s in sections if isinstance(s, dict)]
    if section_type is None:
        return sections
    return [s for s in sections if s.get("type") == section_type]


def _row_text(row):
    detail = row.get("detail")
    if not isinstance(detail, dict):
        return None
    display = detail.get("displayValue")
    if isinstance(display, dict) and display.get("text") is not None:
        return display["text"]
    return detail.get("text")


def detail_rows(detail):
    """Every labelled row of every table, as label -> rendered value.

    Later rows win when a label appears twice, which is what the app shows
    last as well.
    """
    rows = OrderedDict()
    for section in sections_of(detail, "table"):
        data = section.get("data")
        if not isinstance(data, list):
            continue
        for row in data:
            if not isinstance(row, dict):
                continue
            label = row.get("title")
            if not label:
                continue
            rows[label] = _row_text(row)
    return rows


def detail_row(detail, *labels):
    """The value of the first row whose label matches.

    Matching ignores case and surrounding whitespace, so "Gebühr" also finds
    a row labelled "GEBÜHR ".
    """
    rows = detail_rows(detail)
    normalised = {str(k).strip().casefold(): v for k, v in rows.items()}
    for label in labels:
        value = normalised.get(str(label).strip().casefold())
        if value is not None:
            return value
    return None


def detail_isin(detail):
    """The isin of the instrument a detail belongs to.

    The header section links to the instrument, which is where the isin the
    events themselves never carried finally comes from.
    """
    for section in sections_of(detail, "header"):
        action = section.get("action")
        if isinstance(action, dict) and action.get("type") == "instrumentDetail":
            payload = action.get("payload")
            if payload:
                return str(payload)
    return None


def detail_documents(detail):
    """The documents of a detail as a list of {"title", "url"}.

    Everything that is not a link is skipped, so the result is safe to hand
    to a downloader.
    """
    documents = []
    for section in sections_of(detail):
        if section.get("type") not in ("documents", "documentGroup"):
            continue
        data = section.get("data")
        if not isinstance(data, list):
            continue
        for row in data:
            if not isinstance(row, dict):
                continue
            action = row.get("action")
            if not isinstance(action, dict):
                continue
            url = action.get("payload")
            if not isinstance(url, str) or not url.startswith("http"):
                continue
            documents.append({"title": row.get("title") or "", "url": url})
    return documents


# ------------------------------------------------------------------ mapping

#: Labels of the rows the export reads. Trade Republic renders them in the
#: language the API was asked for, so add your own when you use another one.
LABELS = {
    "shares": ("Anteile", "Aktien", "Anzahl", "Stück", "Shares", "Quantity"),
    "price": ("Aktienkurs", "Kurs", "Preis", "Share price", "Price"),
    "fee": ("Gebühr", "Gebühren", "Fremdkostenzuschlag", "Fee", "Fees"),
    "tax": ("Steuern", "Steuer", "Kapitalertragsteuer", "Tax", "Taxes"),
    "total": ("Gesamt", "Summe", "Total"),
}

#: eventType of an event -> what it means for an export. "trade" takes its
#: direction from the sign of the amount, everything else is fixed.
EVENT_TYPES = {
    "TRADING_TRADE_EXECUTED": "trade",
    "TRADING_SAVINGSPLAN_EXECUTED": "buy",
    "ORDER_EXECUTED": "trade",
    "SAVINGS_PLAN_EXECUTED": "buy",
    "BANK_TRANSACTION_INCOMING": "deposit",
    "BANK_TRANSACTION_OUTGOING": "removal",
    "PAYMENT_INBOUND": "deposit",
    "PAYMENT_OUTBOUND": "removal",
    "INTEREST_PAYOUT": "interest",
    "INTEREST_PAYOUT_CREATED": "interest",
    "SSP_CORPORATE_ACTION_INVOICE_CASH": "dividend",
    "CREDIT": "dividend",
}

#: Column titles, kept as they were so existing import profiles still match.
COLUMNS = {
    "de": ["Datum", "Typ", "Stück", "Kurs", "Wert", "Gebühren", "Steuern",
           "ISIN", "Name", "Buchungswährung"],
    "en": ["Date", "Type", "Shares", "Price", "Value", "Fees", "Taxes",
           "ISIN", "Name", "Currency"],
}

KINDS = {
    "de": {"buy": "Kauf", "sell": "Verkauf", "deposit": "Einlage",
           "removal": "Entnahme", "dividend": "Dividende",
           "interest": "Zinsen"},
    "en": {"buy": "Buy", "sell": "Sell", "deposit": "Deposit",
           "removal": "Removal", "dividend": "Dividend",
           "interest": "Interest"},
}


class Transaction(object):
    """One row of the export."""

    __slots__ = ("date", "kind", "shares", "price", "value", "fee", "tax",
                 "isin", "name", "currency", "event_type", "event_id")

    def __init__(self, **fields):
        for slot in self.__slots__:
            setattr(self, slot, fields.get(slot))

    def as_row(self, locale="de"):
        kinds = KINDS.get(locale, KINDS["en"])
        return [
            self.date.strftime("%Y-%m-%d") if self.date else "",
            kinds.get(self.kind, self.kind or ""),
            _plain(self.shares),
            _plain(self.price),
            _plain(self.value),
            _plain(self.fee),
            _plain(self.tax),
            self.isin or "",
            self.name or "",
            self.currency or "",
        ]

    def __repr__(self):
        return "<Transaction %s %s %s>" % (self.date, self.kind, self.value)


def _plain(value):
    return "" if value is None else str(value)


def transaction_of(event, detail=None, decimal_separator=","):
    """Turns a timeline event and its detail into a :class:`Transaction`.

    :param event: one entry of a timelineTransactions response
    :param detail: the matching timelineDetailV2 response, optional. Without
        it there are no shares, no price and no isin, because the event does
        not carry them.
    :param decimal_separator: the one the rendered values use
    :return: the transaction, or None when the event is not one - cancelled
        events, events the mapping does not know and events the customer
        deleted are skipped
    """
    if not isinstance(event, dict):
        return None
    if event.get("deleted"):
        return None

    status = (event.get("status") or "").upper()
    if status in ("CANCELED", "CANCELLED", "REJECTED", "FAILED"):
        return None

    kind = EVENT_TYPES.get(event.get("eventType"))
    if kind is None:
        return None

    amount = event.get("amount") or {}
    value = parse_decimal(amount.get("value"))

    if kind == "trade":
        if value is None:
            return None
        # Money leaving the account pays for something.
        kind = "buy" if value < 0 else "sell"

    def row(key):
        return parse_decimal(detail_row(detail, *LABELS[key]),
                             decimal_separator=decimal_separator)

    return Transaction(
        date=parse_timestamp(event.get("timestamp")),
        kind=kind,
        shares=row("shares") if detail else None,
        price=row("price") if detail else None,
        value=abs(value) if value is not None else None,
        fee=row("fee") if detail else None,
        tax=row("tax") if detail else None,
        isin=detail_isin(detail) if detail else None,
        name=event.get("title"),
        currency=amount.get("currency"),
        event_type=event.get("eventType"),
        event_id=event.get("id"),
    )


def write_csv(transactions, stream, locale="de"):
    """Writes the transactions in the format the old exporter produced.

    Unlike that one this goes through the csv module, so a name containing a
    semicolon no longer breaks the file apart.
    """
    writer = csv.writer(stream, delimiter=";", lineterminator="\n")
    writer.writerow(COLUMNS.get(locale, COLUMNS["en"]))
    for transaction in transactions:
        writer.writerow(transaction.as_row(locale))
