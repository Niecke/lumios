# mail_texts.py — text catalogue of the user-facing transactional mails.
#
# Data only: the layout and sending live in services/mail.py. A language is
# added by adding an entry to FORMATS and MAILS (copy "en"); the parity test in
# tests/test_mail_texts.py fails when a language lacks a mail or field or uses
# other placeholders than German. Values are ``str.format`` templates.
#
# The admin / support mails to the operator are not here: they stay German.

from datetime import date

DEFAULT_LANG = "de"

# Dates and numbers per language.
#   date          pattern over {day}, {month}, {year}
#   months        the 12 month names
#   thousands_sep separator of the thousands in a number
FORMATS: dict[str, dict] = {
    "de": {
        "date": "{day}. {month} {year}",
        "months": (
            "Januar",
            "Februar",
            "März",
            "April",
            "Mai",
            "Juni",
            "Juli",
            "August",
            "September",
            "Oktober",
            "November",
            "Dezember",
        ),
        "thousands_sep": ".",
    },
    "en": {
        "date": "{month} {day}, {year}",
        "months": (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        "thousands_sep": ",",
    },
}

# lang -> mail -> field
MAILS: dict[str, dict[str, dict[str, str]]] = {
    "de": {
        "registration": {
            "subject": "Willkommen bei Lumios – Ihr Konto ist bereit",
            "heading": "Willkommen bei Lumios!",
            "body": (
                "Ihr Konto wurde erfolgreich eingerichtet.<br>\n"
                "           Sie können sich jetzt mit <strong>{user_email}</strong> anmelden."
            ),
            "button": "Zur Anmeldung",
            "body_after": "Falls Sie diese E-Mail nicht erwartet haben, können Sie sie ignorieren.",
        },
        "activation": {
            "subject": "Lumios – Konto aktivieren",
            "heading": "Willkommen bei Lumios!",
            "body": (
                "Vielen Dank für Ihre Registrierung. Bitte aktivieren Sie Ihr Konto\n"
                "           (<strong>{user_email}</strong>) durch Klick auf den folgenden Link."
            ),
            "button": "Konto aktivieren",
            "body_after": (
                "Der Link ist 72 Stunden gültig. Falls Sie sich nicht registriert haben,\n"
                "           können Sie diese E-Mail ignorieren."
            ),
        },
        "gallery_finished": {
            "subject": "Galerie abgeschlossen: {library_name} ({count} {photos} ausgewählt)",
            "heading": "Galerie abgeschlossen",
            "body": (
                "Ihr Kunde hat die Galerie <strong>{library_name}</strong> abgeschlossen\n"
                "           und <strong>{count} {photos}</strong> ausgewählt."
            ),
            "button": "Galerie öffnen",
            "photos_one": "Foto",
            "photos_other": "Fotos",
        },
        "account_cancellation": {
            "subject": "Ihr Lumios-Konto wurde deaktiviert",
            "heading": "Ihr Lumios-Konto wurde deaktiviert",
            "body": (
                "Wir bestätigen, dass Ihr Konto (<strong>{user_email}</strong>)\n"
                "           auf Ihren Wunsch hin deaktiviert wurde."
            ),
            "body_after": (
                "Ihre Daten werden gemäß unserer Datenschutzerklärung behandelt.\n"
                "           Bei Fragen wenden Sie sich bitte an unseren Support."
            ),
        },
        "agb_change": {
            "subject": "Lumios AGB-Änderung: {agb_version}",
            "heading": "Aktualisierung unserer Allgemeinen Geschäftsbedingungen",
            "body": (
                "Wir haben unsere AGB und/oder Datenschutzerklärung aktualisiert\n"
                "           (<strong>{agb_version}</strong>)."
            ),
            "summary": (
                "<strong>Zusammenfassung der Änderungen:</strong><br>\n"
                "           {summary}"
            ),
            "button_intro": "Die vollständigen Bedingungen finden Sie auf unserer Website:",
            "button": "AGB lesen",
            "body_after": (
                "Gemäß §13 unserer AGB sind Sie mit der weiteren Nutzung von Lumios\n"
                "           nach Inkrafttreten der neuen Bedingungen einverstanden."
            ),
            "effective": "Die neuen Bedingungen treten am {date} in Kraft.",
        },
    },
    "en": {
        "registration": {
            "subject": "Welcome to Lumios – your account is ready",
            "heading": "Welcome to Lumios!",
            "body": (
                "Your account has been set up successfully.<br>\n"
                "           You can now sign in with <strong>{user_email}</strong>."
            ),
            "button": "Sign in",
            "body_after": "If you did not expect this email, you can ignore it.",
        },
        "activation": {
            "subject": "Lumios – activate your account",
            "heading": "Welcome to Lumios!",
            "body": (
                "Thank you for registering. Please activate your account\n"
                "           (<strong>{user_email}</strong>) by clicking the link below."
            ),
            "button": "Activate account",
            "body_after": (
                "The link is valid for 72 hours. If you did not register,\n"
                "           you can ignore this email."
            ),
        },
        "gallery_finished": {
            "subject": "Library completed: {library_name} ({count} {photos} selected)",
            "heading": "Library completed",
            "body": (
                "Your customer has completed the library <strong>{library_name}</strong>\n"
                "           and selected <strong>{count} {photos}</strong>."
            ),
            "button": "Open library",
            "photos_one": "photo",
            "photos_other": "photos",
        },
        "account_cancellation": {
            "subject": "Your Lumios account has been deactivated",
            "heading": "Your Lumios account has been deactivated",
            "body": (
                "We confirm that your account (<strong>{user_email}</strong>)\n"
                "           has been deactivated at your request."
            ),
            "body_after": (
                "Your data is handled in accordance with our privacy policy.\n"
                "           If you have any questions, please contact our support."
            ),
        },
        "agb_change": {
            "subject": "Lumios Terms of Service update: {agb_version}",
            "heading": "Update to our Terms of Service",
            "body": (
                "We have updated our Terms of Service and/or privacy policy\n"
                "           (<strong>{agb_version}</strong>)."
            ),
            "summary": (
                "<strong>Summary of the changes:</strong><br>\n"
                "           {summary}"
            ),
            "button_intro": "You can find the full terms on our website:",
            "button": "Read the Terms",
            "body_after": (
                "Under §13 of our Terms, by continuing to use Lumios\n"
                "           after the new terms take effect you accept them."
            ),
            "effective": "The new terms take effect on {date}.",
        },
    },
}


def normalize_lang(value: object) -> str:
    """Return ``value`` when it is a language with a catalogue, else German."""
    if isinstance(value, str) and value in MAILS:
        return value
    return DEFAULT_LANG


def text(lang: str, mail: str, field: str, **values: object) -> str:
    """Format one catalogue entry."""
    return MAILS[normalize_lang(lang)][mail][field].format(**values)


def format_date(d: date, lang: str) -> str:
    fmt = FORMATS[normalize_lang(lang)]
    return fmt["date"].format(day=d.day, month=fmt["months"][d.month - 1], year=d.year)


def format_int(n: int, lang: str) -> str:
    sep = FORMATS[normalize_lang(lang)]["thousands_sep"]
    return f"{n:,}".replace(",", sep)


def plural(lang: str, mail: str, base: str, count: int) -> str:
    """``<base>_one`` for 1, else ``<base>_other`` (same convention as the SPA)."""
    suffix = "one" if count == 1 else "other"
    return text(lang, mail, f"{base}_{suffix}")
