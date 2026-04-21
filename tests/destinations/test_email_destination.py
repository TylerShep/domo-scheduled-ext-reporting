"""Tests for EmailDestination: buffering, MIME structure, SMTP."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.destinations.base import DatasetContext, DestinationContext
from app.destinations.email import EmailDestination, EmailDestinationError


def _basic_dest(**overrides):
    params = {
        "to_addrs": ["leadership@example.com"],
        "from_addr": "bot@example.com",
    }
    params.update(overrides)
    return EmailDestination(**params)


def _make_card_ctx(tmp_path, name: str = "Revenue"):
    path = tmp_path / f"{name}.png"
    path.write_bytes(b"\x89PNG fake")
    return DestinationContext(
        image_path=str(path),
        card_name=name,
        card_url="https://example.com/c/1",
        page_name="Sales",
    )


def _make_dataset_ctx(tmp_path, name: str = "Orders"):
    path = tmp_path / f"{name}.csv"
    path.write_text("a,b\n1,2\n", encoding="utf-8")
    return DatasetContext(
        file_path=str(path),
        dataset_name=name,
        dataset_id="abc",
        file_format="csv",
    )


def test_empty_to_addrs_raises():
    with pytest.raises(EmailDestinationError, match="to_addrs"):
        EmailDestination(to_addrs=[])


def test_invalid_attach_as_raises():
    with pytest.raises(EmailDestinationError, match="attach_as"):
        EmailDestination(to_addrs=["x@y.z"], attach_as="carved-in-stone")


def test_teardown_does_nothing_when_buffers_empty(tmp_path):
    dest = _basic_dest()
    dest.prepare()
    # Shouldn't try to open SMTP.
    with patch("app.destinations.email.smtplib.SMTP") as smtp:
        dest.teardown()
    smtp.assert_not_called()


def test_teardown_sends_one_email_per_run(monkeypatch, tmp_path):
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    dest = _basic_dest()
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path, "Revenue"))
    dest.send_image(_make_card_ctx(tmp_path, "Orders"))

    fake_smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()
    fake_smtp.send_message.assert_called_once()
    msg = fake_smtp.send_message.call_args.args[0]
    assert msg["To"] == "leadership@example.com"
    assert msg["Subject"].startswith("Domo report -- ")


def test_message_contains_inline_images(monkeypatch, tmp_path):
    dest = _basic_dest()
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path, "Revenue"))

    fake_smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()

    msg = fake_smtp.send_message.call_args.args[0]
    # Walk the MIME tree and confirm we have an inline image.
    found_image = False
    for part in msg.walk():
        if part.get_content_type() == "image/png":
            found_image = True
            assert part.get("Content-ID")
            assert "attachment" not in (part.get("Content-Disposition") or "")
    assert found_image, "Expected at least one inline image/png part"


def test_message_attaches_dataset(monkeypatch, tmp_path):
    dest = _basic_dest()
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path))
    dest.send_dataset(_make_dataset_ctx(tmp_path, "Orders"))

    fake_smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()

    msg = fake_smtp.send_message.call_args.args[0]
    csv_parts = [p for p in msg.walk() if p.get_content_type() == "text/csv"]
    assert len(csv_parts) == 1
    disposition = csv_parts[0].get("Content-Disposition") or ""
    assert "attachment" in disposition
    assert "Orders.csv" in disposition


def test_attach_datasets_false_skips_dataset(tmp_path):
    dest = _basic_dest(attach_datasets=False)
    dest.prepare()
    dest.send_dataset(_make_dataset_ctx(tmp_path))
    assert dest._pending_datasets == []


def test_subject_template_renders_today(tmp_path, monkeypatch):
    dest = _basic_dest(subject_template="KPIs for {{ today }}")
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path))

    fake_smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()
    msg = fake_smtp.send_message.call_args.args[0]
    subject = msg["Subject"]
    assert subject.startswith("KPIs for ")
    assert subject != "KPIs for {{ today }}"


def test_uses_tls_and_login_when_credentials_present(monkeypatch, tmp_path):
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_USE_TLS", "true")

    dest = _basic_dest()
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path))

    fake_smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()

    fake_smtp.starttls.assert_called_once()
    fake_smtp.login.assert_called_once_with("user@example.com", "secret")


def test_smtp_failure_wraps_in_destination_error(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_USER", raising=False)
    import smtplib

    dest = _basic_dest()
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path))

    cm = MagicMock()
    cm.__enter__.side_effect = smtplib.SMTPException("connection refused")
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        with pytest.raises(EmailDestinationError, match="SMTP send failed"):
            dest.teardown()


def test_from_addr_falls_back_to_smtp_from(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_FROM_ADDR", "noreply@example.com")
    monkeypatch.delenv("SMTP_USER", raising=False)

    dest = EmailDestination(to_addrs=["a@b.c"])
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path))

    fake_smtp = MagicMock()
    cm = MagicMock()
    cm.__enter__.return_value = fake_smtp
    cm.__exit__.return_value = False
    with patch("app.destinations.email.smtplib.SMTP", return_value=cm):
        dest.teardown()
    msg = fake_smtp.send_message.call_args.args[0]
    assert msg["From"] == "noreply@example.com"


def test_missing_from_addr_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("SMTP_USER", raising=False)
    monkeypatch.delenv("SMTP_FROM_ADDR", raising=False)
    dest = EmailDestination(to_addrs=["a@b.c"])
    dest.prepare()
    dest.send_image(_make_card_ctx(tmp_path))

    with patch("app.destinations.email.smtplib.SMTP"):
        with pytest.raises(EmailDestinationError, match="from_addr"):
            dest.teardown()


def test_registry_routes_email_type(monkeypatch):
    from app.destinations.registry import build_destination

    dest = build_destination({"type": "email", "to_addrs": ["x@y.z"], "from_addr": "b@y.z"})
    assert isinstance(dest, EmailDestination)
