"""Références de paiement par restaurant et curseur de pagination (sans base)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.utils.payment_references import (
    ALPHABET,
    PREFIX_PATTERN,
    InvalidCursor,
    belongs_to_prefix,
    decode_cursor,
    encode_cursor,
    net_amount_fcfa,
    new_reference_prefix,
    new_vendor_reference,
)


class TestPrefix:
    def test_format_is_readable_and_unambiguous(self):
        for _ in range(200):
            prefix = new_reference_prefix()
            assert PREFIX_PATTERN.match(prefix), prefix
            assert not set(prefix.split("-")[1]) & set("01OILU")

    def test_prefixes_are_effectively_unique(self):
        assert len({new_reference_prefix() for _ in range(5000)}) == 5000

    def test_alphabet_has_no_ambiguous_characters(self):
        assert not set(ALPHABET) & set("01OILU")


class TestVendorReference:
    def test_it_carries_the_prefix_the_date_and_a_random_part(self):
        moment = datetime(2026, 10, 7, 23, 59, tzinfo=timezone.utc)
        reference = new_vendor_reference("MRD-7KQ2XA9P", moment)
        prefix, date, random_part = reference.rsplit("-", 2)
        assert prefix == "MRD-7KQ2XA9P"
        assert date == "20261007"
        assert len(random_part) == 12 and random_part == random_part.upper()

    def test_it_respects_the_gateway_limit_of_100_characters(self):
        assert len(new_vendor_reference("MRD-" + "A" * 29)) <= 100

    def test_two_references_of_the_same_restaurant_never_collide(self):
        refs = {new_vendor_reference("MRD-7KQ2XA9P") for _ in range(5000)}
        assert len(refs) == 5000

    def test_the_date_is_utc_whatever_the_timezone_given(self):
        local = datetime.fromisoformat("2026-10-08T00:30:00+02:00")  # 22:30 UTC la veille
        assert "-20261007-" in new_vendor_reference("MRD-AAAAAAAA", local)


class TestBelongsToPrefix:
    def test_a_reference_belongs_to_its_own_prefix(self):
        assert belongs_to_prefix(new_vendor_reference("MRD-7KQ2XA9P"), "MRD-7KQ2XA9P")

    def test_one_prefix_is_never_mistaken_for_the_start_of_another(self):
        assert not belongs_to_prefix("MRD-7KQ2XA9PZ-20261007-ABC", "MRD-7KQ2XA9P")
        assert not belongs_to_prefix("MRD-OTHER222-20261007-ABC", "MRD-7KQ2XA9P")


class TestNetAmount:
    def test_inclusive_fees_are_deducted(self):
        assert net_amount_fcfa(104, Decimal("2"), True) == Decimal("102")

    def test_fees_paid_on_top_leave_the_amount_untouched(self):
        assert net_amount_fcfa(100, Decimal("2"), False) == Decimal("100")

    def test_unknown_fees_mean_unknown_net(self):
        assert net_amount_fcfa(100, None, True) is None
        assert net_amount_fcfa(100, Decimal("2"), None) is None


class TestCursor:
    def test_round_trip(self):
        when, row_id = datetime(2026, 10, 7, 12, 30, 5, 123456, tzinfo=timezone.utc), uuid.uuid4()
        assert decode_cursor(encode_cursor(when, row_id)) == (when, row_id)

    @pytest.mark.parametrize("garbage", ["", "not-base64!!", "e30", "eyJ0IjoiMSJ9", "AAAA"])
    def test_garbage_is_rejected_cleanly(self, garbage):
        with pytest.raises(InvalidCursor):
            decode_cursor(garbage)

    def test_the_cursor_is_url_safe(self):
        cursor = encode_cursor(datetime.now(timezone.utc), uuid.uuid4())
        assert all(c.isalnum() or c in "-_" for c in cursor)
