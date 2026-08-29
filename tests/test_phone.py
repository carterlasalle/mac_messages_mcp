"""
Tests for the phone module
"""

import os
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from mac_messages_mcp.phone import (
    FALLBACK_REGION,
    REGION_ENV_VAR,
    _region_from_locale,
    canonical_handle,
    digits_only,
    get_default_region,
    handle_variants,
    is_email_handle,
    to_e164,
)


@contextmanager
def region_pinned(region=None, clear_locale_env=False):
    """Temporarily control the environment get_default_region() reads.

    Both get_default_region and to_e164 are @lru_cache'd, so changing the
    environment alone is not enough: their caches must be cleared before and
    after the change or a value cached under a previous region would leak
    into (or out of) this test.

    Args:
        region: Value to set MAC_MESSAGES_REGION to. None leaves it untouched.
        clear_locale_env: When True, also remove MAC_MESSAGES_REGION, LC_ALL,
            LC_CTYPE and LANG from the environment so region resolution has
            nothing to read except what the test patches directly (e.g.
            _macos_locale).
    """
    env_backup = dict(os.environ)
    try:
        if clear_locale_env:
            for key in (REGION_ENV_VAR, "LC_ALL", "LC_CTYPE", "LANG"):
                os.environ.pop(key, None)
        if region is not None:
            os.environ[REGION_ENV_VAR] = region
        get_default_region.cache_clear()
        to_e164.cache_clear()
        yield
    finally:
        os.environ.clear()
        os.environ.update(env_backup)
        get_default_region.cache_clear()
        to_e164.cache_clear()


class TestToE164(unittest.TestCase):
    """Tests for to_e164, national numbers expanded against a configured region."""

    def test_fr_mobile_national_plain(self):
        """A plain-digit French mobile number expands against the FR region."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("0639980001"), "+33639980001")

    def test_fr_mobile_national_spaced(self):
        """A space-separated French mobile number expands the same way."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("07 39 98 00 02"), "+33739980002")

    def test_fr_landline_national(self):
        """A French landline number expands against the FR region."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("0539980003"), "+33539980003")

    def test_us_ten_digit_national(self):
        """A ten-digit US number expands against the US region."""
        with region_pinned("US"):
            self.assertEqual(to_e164("5555550142"), "+15555550142")

    def test_e164_input_unchanged_under_foreign_region(self):
        """An already-E.164 French number is untouched even under region US.

        This is the regression this module fixes: national expansion used to
        assume North America regardless of the number's own country code.
        """
        with region_pinned("US"):
            self.assertEqual(to_e164("+33639980001"), "+33639980001")

    def test_e164_input_unchanged_under_foreign_region_reverse(self):
        """An already-E.164 US number is untouched even under region FR."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("+15555550142"), "+15555550142")

    def test_input_with_spaces(self):
        """Space-separated national input is accepted."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("06 39 98 00 01"), "+33639980001")

    def test_input_with_dots(self):
        """Dot-separated national input is accepted."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("05.39.98.00.03"), "+33539980003")

    def test_input_with_spaces_and_plus(self):
        """Space-separated international input with a leading plus is accepted."""
        with region_pinned("FR"):
            self.assertEqual(to_e164("+33 6 39 98 00 01"), "+33639980001")


class TestCanonicalHandle(unittest.TestCase):
    """Tests for canonical_handle, the single comparison key for handle ids."""

    def test_round_trip_same_number_different_spellings(self):
        """Every spelling of the same FR number reduces to the same key."""
        with region_pinned("FR"):
            spellings = [
                "0639980001",
                "06 39 98 00 01",
                "+33639980001",
                "+33 6 39 98 00 01",
                "33639980001",
            ]
            keys = {canonical_handle(spelling) for spelling in spellings}
            self.assertEqual(keys, {"+33639980001"})

    def test_email_reduces_to_lowercased_form(self):
        """An email handle reduces to its lowercased, stripped form."""
        self.assertEqual(canonical_handle("  Hugo@Example.COM "), "hugo@example.com")

    def test_garbage_input_reduces_to_none(self):
        """Input that is neither an email nor a parseable number reduces to None."""
        with region_pinned("FR"):
            self.assertIsNone(canonical_handle("not a phone number"))

    def test_empty_input_reduces_to_none(self):
        """An empty string reduces to None."""
        self.assertIsNone(canonical_handle(""))


class TestHandleVariants(unittest.TestCase):
    """Tests for handle_variants, the candidate list used for WHERE id IN (...)."""

    def test_phone_variants_include_e164_digits_and_national(self):
        """A FR number's variants include the E.164, bare-digit and national forms."""
        with region_pinned("FR"):
            variants = handle_variants("06 39 98 00 01")

        self.assertIn("+33639980001", variants)
        self.assertIn("33639980001", variants)
        self.assertIn("0639980001", variants)

    def test_email_variants_are_just_the_email(self):
        """An email handle's variants are its canonical and original forms only."""
        variants = handle_variants("Hugo@Example.com")

        self.assertEqual(variants, ["hugo@example.com", "Hugo@Example.com"])


class TestGetDefaultRegion(unittest.TestCase):
    """Tests for get_default_region's source priority."""

    def test_env_override_wins_over_locale(self):
        """MAC_MESSAGES_REGION wins even when the locale would resolve elsewhere."""
        with patch("mac_messages_mcp.phone._macos_locale", return_value="en_US"):
            with region_pinned("FR"):
                self.assertEqual(get_default_region(), "FR")

    def test_unsupported_env_value_is_ignored(self):
        """A garbage MAC_MESSAGES_REGION value is ignored, falling through."""
        with patch("mac_messages_mcp.phone._macos_locale", return_value="fr_FR"):
            with region_pinned("NOTAREGION"):
                self.assertEqual(get_default_region(), "FR")

    def test_falls_back_to_us_when_nothing_resolves(self):
        """With no env override and no usable locale, the region falls back to US."""
        with patch("mac_messages_mcp.phone._macos_locale", return_value=None):
            with region_pinned(clear_locale_env=True):
                self.assertEqual(get_default_region(), FALLBACK_REGION)


class TestRegionFromLocale(unittest.TestCase):
    """Tests for _region_from_locale's parsing of locale identifiers."""

    def test_underscore_locale(self):
        """A plain underscore locale yields its trailing region."""
        self.assertEqual(_region_from_locale("fr_FR"), "FR")

    def test_hyphen_locale(self):
        """A hyphen-separated locale yields its trailing region."""
        self.assertEqual(_region_from_locale("fr-FR"), "FR")

    def test_locale_with_encoding_suffix(self):
        """A locale with an encoding suffix still yields its region."""
        self.assertEqual(_region_from_locale("en_US.UTF-8"), "US")

    def test_locale_with_variant_suffix(self):
        """A locale with an @-variant suffix still yields its region."""
        self.assertEqual(_region_from_locale("fr_FR@euro"), "FR")

    def test_locale_with_script_subtag(self):
        """A locale carrying a script subtag yields the trailing region, not the script."""
        self.assertEqual(_region_from_locale("zh-Hans-CN"), "CN")

    def test_language_only_locale_yields_none(self):
        """A locale with no region subtag yields None."""
        self.assertIsNone(_region_from_locale("fr"))

    def test_empty_locale_yields_none(self):
        """An empty locale string yields None."""
        self.assertIsNone(_region_from_locale(""))

    def test_none_locale_yields_none(self):
        """A None locale yields None."""
        self.assertIsNone(_region_from_locale(None))

    def test_unsupported_region_yields_none(self):
        """A locale whose region phonenumbers has no metadata for yields None."""
        self.assertIsNone(_region_from_locale("xx_ZZ"))


class TestDigitsOnly(unittest.TestCase):
    """Tests for digits_only, the last-resort comparison key."""

    def test_strips_separators(self):
        """Spaces, dots, dashes, parentheses and the leading plus are all stripped."""
        self.assertEqual(digits_only("+33 6.39-98(00)01"), "33639980001")

    def test_empty_input(self):
        """An empty string yields an empty string."""
        self.assertEqual(digits_only(""), "")

    def test_none_input(self):
        """A None input yields an empty string."""
        self.assertEqual(digits_only(None), "")


class TestIsEmailHandle(unittest.TestCase):
    """Tests for is_email_handle."""

    def test_email_is_detected(self):
        """A value containing an '@' is treated as an email handle."""
        self.assertTrue(is_email_handle("hugo@example.com"))

    def test_phone_is_not_email(self):
        """A phone number is not treated as an email handle."""
        self.assertFalse(is_email_handle("0639980001"))

    def test_empty_value_is_not_email(self):
        """An empty value is not treated as an email handle."""
        self.assertFalse(is_email_handle(""))


if __name__ == "__main__":
    unittest.main()
