"""Tests for the timeline parsing.

The fixtures follow the shape timelineTransactions and timelineDetailV2
actually answer with, recorded against the live API in August 2026.
"""

import io
import unittest
from datetime import datetime
from decimal import Decimal

from trapi.timeline import (
    Transaction,
    detail_documents,
    detail_isin,
    detail_row,
    detail_rows,
    parse_decimal,
    parse_timestamp,
    sections_of,
    transaction_of,
    write_csv,
)


def trade_detail(rows=None, isin="US0378331005", documents=True):
    sections = [
        {
            "type": "header",
            "title": "Apple Inc",
            "data": {"icon": {"asset": "logos/x", "badge": None},
                     "subtitleText": "Kauf", "status": "executed"},
            "action": {"type": "instrumentDetail", "payload": isin},
        },
        {
            "type": "table",
            "title": "Übersicht",
            "data": rows if rows is not None else [
                {"title": "Status",
                 "detail": {"text": "Ausgeführt", "type": "status"},
                 "style": "plain"},
                {"title": "Anteile",
                 "detail": {"text": "0,347", "type": "text"},
                 "style": "plain"},
                {"title": "Aktienkurs",
                 "detail": {"text": "265,50 €", "type": "text"},
                 "style": "plain"},
                {"title": "Gebühr",
                 "detail": {"text": "1,00 €", "type": "text"},
                 "style": "plain"},
            ],
        },
    ]
    if documents:
        sections.append({
            "type": "documents",
            "title": "Dokumente",
            "data": [
                {"title": "Abrechnung",
                 "action": {"type": "browserModal",
                            "payload": "https://tr.example/a.pdf"}},
                {"title": "Kein Link",
                 "action": {"type": "instrumentDetail", "payload": "US123"}},
                {"title": "Ohne action"},
            ],
        })
    return {"id": "detail-id", "sections": sections}


def event(**overrides):
    base = {
        "id": "event-id",
        "timestamp": "2026-08-13T09:41:02.123+0000",
        "title": "Apple Inc",
        "subtitle": "Kauforder",
        "amount": {"currency": "EUR", "value": -92.13, "fractionDigits": 2},
        "status": "EXECUTED",
        "action": {"type": "timelineDetail", "payload": "detail-id"},
        "eventType": "TRADING_TRADE_EXECUTED",
        "hidden": False,
        "deleted": False,
    }
    base.update(overrides)
    return base


class ParseDecimalTest(unittest.TestCase):
    def test_german_rendering(self):
        self.assertEqual(parse_decimal("1.234,56 €"), Decimal("1234.56"))
        self.assertEqual(parse_decimal("0,347"), Decimal("0.347"))
        self.assertEqual(parse_decimal("-9,99 EUR"), Decimal("-9.99"))

    def test_english_rendering(self):
        self.assertEqual(parse_decimal("1,234.56", decimal_separator="."),
                         Decimal("1234.56"))

    def test_grouping_with_spaces(self):
        self.assertEqual(parse_decimal("1 234,56 €"), Decimal("1234.56"))

    def test_numbers_pass_through(self):
        self.assertEqual(parse_decimal(-92.13), Decimal("-92.13"))
        self.assertEqual(parse_decimal(5), Decimal("5"))

    def test_nothing_to_read(self):
        self.assertIsNone(parse_decimal(None))
        self.assertIsNone(parse_decimal(""))
        self.assertIsNone(parse_decimal("Ausgeführt"))


class ParseTimestampTest(unittest.TestCase):
    def test_iso_with_offset(self):
        parsed = parse_timestamp("2026-08-13T09:41:02.123+0000")
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.month, 8)
        self.assertEqual(parsed.day, 13)

    def test_iso_with_z(self):
        self.assertIsNotNone(parse_timestamp("2026-08-13T09:41:02Z"))

    def test_epoch_milliseconds_still_work(self):
        # The old timeline delivered these, and exported files still hold them.
        parsed = parse_timestamp(1616811300786)
        self.assertEqual(parsed.year, 2021)
        self.assertEqual(parse_timestamp("1616811300786"), parsed)

    def test_nonsense(self):
        self.assertIsNone(parse_timestamp("morgen"))
        self.assertIsNone(parse_timestamp(None))


class DetailAccessTest(unittest.TestCase):
    def test_sections_can_be_filtered(self):
        detail = trade_detail()
        self.assertEqual(len(sections_of(detail)), 3)
        self.assertEqual(len(sections_of(detail, "table")), 1)
        self.assertEqual(sections_of(detail, "header")[0]["type"], "header")

    def test_rows_are_collected_by_label(self):
        rows = detail_rows(trade_detail())
        self.assertEqual(rows["Anteile"], "0,347")
        self.assertEqual(rows["Gebühr"], "1,00 €")

    def test_lookup_ignores_case_and_spacing(self):
        self.assertEqual(detail_row(trade_detail(), " gebÜhr "), "1,00 €")

    def test_lookup_takes_the_first_label_that_matches(self):
        self.assertEqual(detail_row(trade_detail(), "Stück", "Anteile"), "0,347")
        self.assertIsNone(detail_row(trade_detail(), "gibt es nicht"))

    def test_display_value_wins_over_text(self):
        detail = trade_detail(rows=[{
            "title": "Anteile",
            "detail": {"text": "0,3", "type": "text",
                       "displayValue": {"text": "0,347"}},
        }])
        self.assertEqual(detail_row(detail, "Anteile"), "0,347")

    def test_isin_comes_from_the_header_link(self):
        # The events themselves never carried it.
        self.assertEqual(detail_isin(trade_detail()), "US0378331005")

    def test_no_isin_without_an_instrument_link(self):
        detail = trade_detail()
        detail["sections"][0].pop("action")
        self.assertIsNone(detail_isin(detail))

    def test_documents_are_links_only(self):
        documents = detail_documents(trade_detail())
        self.assertEqual(len(documents), 1)
        self.assertEqual(documents[0]["title"], "Abrechnung")
        self.assertTrue(documents[0]["url"].startswith("https://"))

    def test_no_documents_section(self):
        self.assertEqual(detail_documents(trade_detail(documents=False)), [])

    def test_survives_a_response_that_makes_no_sense(self):
        for junk in (None, {}, {"sections": None}, {"sections": ["x", 3]}):
            self.assertEqual(detail_rows(junk), {})
            self.assertIsNone(detail_isin(junk))
            self.assertEqual(detail_documents(junk), [])


class TransactionTest(unittest.TestCase):
    def test_money_leaving_the_account_is_a_buy(self):
        tx = transaction_of(event(), trade_detail())
        self.assertEqual(tx.kind, "buy")
        self.assertEqual(tx.shares, Decimal("0.347"))
        self.assertEqual(tx.price, Decimal("265.50"))
        self.assertEqual(tx.fee, Decimal("1.00"))
        self.assertEqual(tx.value, Decimal("92.13"))
        self.assertEqual(tx.isin, "US0378331005")
        self.assertEqual(tx.currency, "EUR")

    def test_money_arriving_is_a_sell(self):
        tx = transaction_of(
            event(amount={"currency": "EUR", "value": 92.13}), trade_detail())
        self.assertEqual(tx.kind, "sell")
        self.assertEqual(tx.value, Decimal("92.13"))

    def test_value_is_reported_without_a_sign(self):
        # The kind already says which way the money went.
        tx = transaction_of(event(), trade_detail())
        self.assertGreater(tx.value, 0)

    def test_deposits_and_payouts(self):
        deposit = transaction_of(event(eventType="BANK_TRANSACTION_INCOMING",
                                       amount={"currency": "EUR", "value": 500}))
        self.assertEqual(deposit.kind, "deposit")
        self.assertIsNone(deposit.isin)

        payout = transaction_of(event(eventType="BANK_TRANSACTION_OUTGOING",
                                      amount={"currency": "EUR", "value": -20}))
        self.assertEqual(payout.kind, "removal")
        self.assertEqual(payout.value, Decimal("20"))

    def test_cancelled_and_deleted_events_are_left_out(self):
        self.assertIsNone(transaction_of(event(status="CANCELED")))
        self.assertIsNone(transaction_of(event(status="REJECTED")))
        self.assertIsNone(transaction_of(event(deleted=True)))

    def test_unknown_event_types_are_left_out(self):
        # Silently dropping them was how the old converter lost entries, so
        # callers get None and can report it.
        self.assertIsNone(transaction_of(event(eventType="SOMETHING_NEW")))

    def test_works_without_a_detail(self):
        tx = transaction_of(event())
        self.assertEqual(tx.kind, "buy")
        self.assertIsNone(tx.shares)
        self.assertIsNone(tx.isin)

    def test_junk_in_junk_out(self):
        self.assertIsNone(transaction_of(None))
        self.assertIsNone(transaction_of("nope"))


class WriteCsvTest(unittest.TestCase):
    def rows_of(self, transactions, locale="de"):
        stream = io.StringIO()
        write_csv(transactions, stream, locale=locale)
        return stream.getvalue().splitlines()

    def test_header_matches_the_old_export(self):
        lines = self.rows_of([])
        self.assertTrue(lines[0].startswith("Datum;Typ;Stück;"))
        self.assertTrue(lines[0].endswith("Buchungswährung"))

    def test_english_header_lines_up_with_the_german_one(self):
        # The old exporter wrote Amount/Value/Price against
        # Stück/Wechselkurs/Wert, so the two did not describe the same columns.
        de = self.rows_of([], locale="de")[0].split(";")
        en = self.rows_of([], locale="en")[0].split(";")
        self.assertEqual(len(de), len(en))
        self.assertEqual(en[2], "Shares")
        self.assertEqual(en[4], "Value")

    def test_a_transaction_becomes_one_line(self):
        tx = transaction_of(event(), trade_detail())
        lines = self.rows_of([tx])
        self.assertEqual(len(lines), 2)
        fields = lines[1].split(";")
        self.assertEqual(fields[1], "Kauf")
        self.assertEqual(fields[2], "0.347")
        self.assertEqual(fields[7], "US0378331005")

    def test_a_semicolon_in_a_name_does_not_split_the_line(self):
        # The old exporter formatted the line by hand and broke on this.
        tx = transaction_of(event(title="Rheinmetall; AG"), trade_detail())
        stream = io.StringIO()
        write_csv([tx], stream)
        line = stream.getvalue().splitlines()[1]
        self.assertIn('"Rheinmetall; AG"', line)

        import csv
        parsed = list(csv.reader(io.StringIO(line), delimiter=";"))[0]
        self.assertEqual(len(parsed), 10)
        self.assertEqual(parsed[8], "Rheinmetall; AG")

    def test_missing_values_stay_empty(self):
        tx = Transaction(date=datetime(2026, 8, 13), kind="deposit",
                         value=Decimal("500"), currency="EUR")
        fields = self.rows_of([tx])[1].split(";")
        self.assertEqual(fields[0], "2026-08-13")
        self.assertEqual(fields[2], "")
        self.assertEqual(fields[7], "")


if __name__ == "__main__":
    unittest.main()
