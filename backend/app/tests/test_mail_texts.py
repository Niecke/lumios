"""Catalogue checks for services/mail_texts.py (no app context needed)."""

from datetime import date
from string import Formatter

import pytest

from blueprints.api.auth import SUPPORTED_LANGUAGES
from services.mail_texts import (
    DEFAULT_LANG,
    FORMATS,
    MAILS,
    format_date,
    format_int,
    normalize_lang,
    plural,
    text,
)


def _placeholders(value: str) -> set[str]:
    return {name for _, name, _, _ in Formatter().parse(value) if name is not None}


def test_languages_match_the_supported_languages():
    assert set(MAILS) == set(FORMATS) == set(SUPPORTED_LANGUAGES)
    assert DEFAULT_LANG in MAILS


@pytest.mark.parametrize("lang", sorted(set(MAILS) - {DEFAULT_LANG}))
def test_every_language_has_every_mail_and_field_like_german(lang):
    german = MAILS[DEFAULT_LANG]
    assert set(MAILS[lang]) == set(german)
    for mail, fields in german.items():
        assert set(MAILS[lang][mail]) == set(fields), mail


@pytest.mark.parametrize("lang", sorted(MAILS))
def test_texts_are_not_empty_and_use_the_german_placeholders(lang):
    for mail, fields in MAILS[lang].items():
        for field, value in fields.items():
            assert isinstance(value, str) and value.strip(), (lang, mail, field)
            expected = _placeholders(MAILS[DEFAULT_LANG][mail][field])
            assert _placeholders(value) == expected, (lang, mail, field)


@pytest.mark.parametrize("lang", sorted(FORMATS))
def test_formats_are_complete(lang):
    fmt = FORMATS[lang]
    assert len(fmt["months"]) == 12 and all(m.strip() for m in fmt["months"])
    assert _placeholders(fmt["date"]) == {"day", "month", "year"}
    assert fmt["thousands_sep"]


def test_normalize_lang():
    assert normalize_lang("en") == "en"
    assert normalize_lang("de") == "de"
    for bad in ("fr", "", None, 1, [], ["en"], {"en"}):
        assert normalize_lang(bad) == "de"


def test_format_date():
    assert format_date(date(2026, 12, 1), "de") == "1. Dezember 2026"
    assert format_date(date(2026, 12, 1), "en") == "December 1, 2026"
    assert format_date(date(2026, 3, 9), "fr") == "9. März 2026"


def test_format_int():
    assert format_int(1234, "de") == "1.234"
    assert format_int(1234, "en") == "1,234"
    assert format_int(12, "en") == "12"
    assert format_int(1234567, "de") == "1.234.567"


def test_plural():
    assert plural("de", "gallery_finished", "photos", 1) == "Foto"
    assert plural("de", "gallery_finished", "photos", 2) == "Fotos"
    assert plural("en", "gallery_finished", "photos", 1) == "photo"
    assert plural("en", "gallery_finished", "photos", 0) == "photos"


def test_text_formats_placeholders():
    assert "a@b.de" in text("en", "registration", "body", user_email="a@b.de")
