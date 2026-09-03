#!/usr/bin/env python3
"""Short Atheris fuzz of phone/handle parsers.

Scorecard's Fuzzing check looks for ``import atheris`` in Python sources.
This harness is also run in CI for a bounded number of iterations.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import atheris

ROOT = Path(__file__).resolve().parents[1]
PHONE_PATH = ROOT / "mac_messages_mcp" / "phone.py"


def _load_phone():
    spec = importlib.util.spec_from_file_location("mac_messages_mcp_phone", PHONE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PHONE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


phone = _load_phone()


@atheris.instrument_func
def TestOneInput(data: bytes) -> None:
    fdp = atheris.FuzzedDataProvider(data)
    text = fdp.ConsumeUnicodeNoSurrogates(512)
    phone.canonical_handle(text)
    phone.to_e164(text)
    phone.to_dialable_e164(text)
    phone.handle_variants(text)
    phone.is_email_handle(text)


def main() -> None:
    atheris.instrument_all()
    atheris.Setup(sys.argv, TestOneInput)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
