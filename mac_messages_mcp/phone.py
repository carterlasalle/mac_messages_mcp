"""Canonical phone number handling for the Messages database.

Handle ids in ``chat.db`` are stored in whatever shape the sender, the carrier
or the address book happened to use: ``+33639980001``, ``0639980001``,
``+1 (555) 555-0142``, or a bare email address. Comparing those spellings as
raw strings makes lookups miss, so every comparison in this package goes
through :func:`canonical_handle`, which reduces an input to a single canonical
form (E.164 for phone numbers, the lowercased address for emails).

National-format numbers are interpreted against the region configured on this
Mac, see :func:`get_default_region`, instead of a hardcoded country. Assuming
North America was what turned French national numbers such as ``06 39 98 00 01``
into ``+10639980001``.
"""

import os
import re
import subprocess
from functools import lru_cache
from typing import List, Optional

import phonenumbers

# Explicit override for users whose Mac region does not match the region their
# phone numbers belong to (a French SIM on a Mac configured as en_US, say).
REGION_ENV_VAR = "MAC_MESSAGES_REGION"

# Used only when neither the environment nor macOS can tell us anything. It
# matches the historical behaviour of this package.
FALLBACK_REGION = "US"

# Pulls the ISO 3166-1 alpha-2 region out of a locale identifier: "fr_FR",
# "fr-FR", "en_US.UTF-8", "fr_FR@euro" or "zh-Hans-CN" all yield the trailing
# two-letter region rather than the language or the script subtag.
_LOCALE_REGION_RE = re.compile(r"[-_]([A-Za-z]{2})(?:[-_@.]|$)")


def _region_from_locale(locale_id: Optional[str]) -> Optional[str]:
    """
    Extract an ISO 3166-1 alpha-2 region code from a locale identifier.

    Parameters
    ----------
    locale_id : str or None
        A locale identifier such as ``"fr_FR"`` or ``"en_US.UTF-8"``.

    Returns
    -------
    str or None
        The uppercased region code when it is one phonenumbers knows about,
        ``None`` otherwise.
    """
    if not locale_id:
        return None

    match = _LOCALE_REGION_RE.search(locale_id.strip())
    if not match:
        return None

    region = match.group(1).upper()
    # A locale can carry a region phonenumbers has no metadata for; treating it
    # as unknown is better than parsing every national number against nothing.
    return region if region in phonenumbers.SUPPORTED_REGIONS else None


def _macos_locale() -> Optional[str]:
    """
    Read the region-bearing locale macOS is configured with.

    Returns
    -------
    str or None
        The value of ``AppleLocale`` in the global preference domain, or
        ``None`` when ``defaults`` is unavailable or reports nothing. This is
        the same setting Messages.app uses to expand national numbers, and it
        is readable even when the process was started without any ``LANG``
        environment variable, which is the usual case for an MCP server
        launched by a GUI client.
    """
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleLocale"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache(maxsize=1)
def get_default_region() -> str:
    """
    Determine the region national-format phone numbers should be parsed against.

    The first source that yields a region phonenumbers supports wins:

    1. the ``MAC_MESSAGES_REGION`` environment variable, an explicit override;
    2. the macOS ``AppleLocale`` preference;
    3. the ``LC_ALL`` / ``LC_CTYPE`` / ``LANG`` environment variables;
    4. :data:`FALLBACK_REGION`.

    Returns
    -------
    str
        An ISO 3166-1 alpha-2 region code.

    Notes
    -----
    The result is cached for the lifetime of the process. Call
    ``get_default_region.cache_clear()`` after changing the environment, which
    is what the tests do.
    """
    override = os.environ.get(REGION_ENV_VAR, "").strip().upper()
    if override in phonenumbers.SUPPORTED_REGIONS:
        return override

    region = _region_from_locale(_macos_locale())
    if region:
        return region

    for env_var in ("LC_ALL", "LC_CTYPE", "LANG"):
        region = _region_from_locale(os.environ.get(env_var))
        if region:
            return region

    return FALLBACK_REGION


def is_email_handle(value: str) -> bool:
    """
    Report whether a handle id is an email address rather than a phone number.

    Parameters
    ----------
    value : str
        A handle id, recipient string or address book entry.

    Returns
    -------
    bool
        ``True`` when the value should be compared as an email address.
    """
    return "@" in (value or "")


@lru_cache(maxsize=4096)
def to_e164(value: str, region: Optional[str] = None) -> Optional[str]:
    """
    Convert a phone number written in any format to its E.164 representation.

    Parameters
    ----------
    value : str
        A phone number in national, international or E.164 format. Separators
        (spaces, dots, dashes, parentheses) and international prefixes such as
        ``00`` or ``011`` are accepted.
    region : str, optional
        Region to interpret national-format numbers against. Defaults to
        :func:`get_default_region`.

    Returns
    -------
    str or None
        The number as ``+<country code><national number>``, or ``None`` when
        the input cannot be read as a phone number.

    Notes
    -----
    Only *possible* numbers are required, not *valid* ones. Validity depends on
    the ranges an operator has actually been assigned, which lags reality and
    would reject both freshly allocated ranges and the documentation ranges
    used in the tests.

    Results are cached because handle lookups normalize the same numbers over
    and over. Call ``to_e164.cache_clear()`` after changing the region, which
    is what the tests do.
    """
    if not value or is_email_handle(value):
        return None

    try:
        parsed = phonenumbers.parse(value, region or get_default_region())
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_possible_number(parsed):
        return None

    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def canonical_handle(value: str, region: Optional[str] = None) -> Optional[str]:
    """
    Reduce a recipient or handle id to the form used for every comparison.

    Parameters
    ----------
    value : str
        A phone number, an email address, or a raw ``handle.id`` from the
        Messages database.
    region : str, optional
        Region to interpret national-format numbers against. Defaults to
        :func:`get_default_region`.

    Returns
    -------
    str or None
        The lowercased address for an email handle, the E.164 number for a
        phone handle, or ``None`` when the value is neither.

    Examples
    --------
    With the region set to ``FR``, ``"06 39 98 00 01"``, ``"0639980001"`` and
    ``"+33 6 39 98 00 01"`` all reduce to ``"+33639980001"``.
    """
    if not value:
        return None

    if is_email_handle(value):
        return value.strip().lower()

    return to_e164(value, region)


def digits_only(value: str) -> str:
    """
    Strip everything but the digits from a phone number.

    Parameters
    ----------
    value : str
        Any phone number spelling.

    Returns
    -------
    str
        The digits, in order. Used as a last-resort comparison key for inputs
        no region can make sense of.
    """
    if not value:
        return ""
    return "".join(c for c in value if c.isdigit())


def handle_variants(value: str, region: Optional[str] = None) -> List[str]:
    """
    Build the handle ids the Messages database may have recorded for a recipient.

    Parameters
    ----------
    value : str
        A phone number or email address.
    region : str, optional
        Region to interpret national-format numbers against. Defaults to
        :func:`get_default_region`.

    Returns
    -------
    list of str
        Candidate handle ids, most canonical first: the E.164 form, the same
        digits without the leading ``+``, the national form as the local
        carrier would write it, and the original input. Duplicates are removed
        while preserving that order.

    Notes
    -----
    Used to build ``WHERE id IN (...)`` clauses. It is a fast path only:
    matching still falls back to comparing :func:`canonical_handle` values,
    which catches spellings this list does not anticipate.
    """
    variants: List[str] = []

    def add(candidate: Optional[str]) -> None:
        if candidate and candidate not in variants:
            variants.append(candidate)

    if is_email_handle(value):
        add(canonical_handle(value, region))
        add((value or "").strip())
        return variants

    e164 = to_e164(value, region)
    if e164:
        add(e164)
        add(e164.lstrip("+"))
        try:
            parsed = phonenumbers.parse(e164, None)
        except phonenumbers.NumberParseException:
            parsed = None
        if parsed is not None:
            # Some handles are stored the way the number is dialled locally,
            # e.g. "0639980001" in France or "(555) 555-0142" in the US.
            national = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.NATIONAL
            )
            add(digits_only(national))

    # Keep the input verbatim as well as stripped: alphanumeric sender ids
    # ("SHORTCODE", a brand name) are handles too, and some carry padding that
    # is part of the stored id.
    add(value)
    add((value or "").strip())
    add(digits_only(value))
    return [v for v in variants if v]
