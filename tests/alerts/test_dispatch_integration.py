"""Integration tests: send_when gating inside DomoBase._dispatch."""

from __future__ import annotations

from app.destinations.base import Destination, DestinationContext
from app.history.base import DestinationOutcome, RunRecord
from app.services.base import DomoBase


class _StubDestination(Destination):
    """Captures every send_image call so tests can assert fan-out."""

    key = "stub"
    label = "Stub"

    def __init__(self, *, send_when: str | None = None, name: str = "stub") -> None:
        super().__init__(send_when=send_when)
        self._name = name
        self.sent: list[str] = []

    def describe(self) -> str:  # type: ignore[override]
        return f"stub({self._name})"

    def send_image(self, ctx: DestinationContext) -> None:
        self.sent.append(ctx.card_name)


class _Report(DomoBase):
    name = "AlertsTest"

    def file_name(self) -> str:
        return "ignored"

    def list_of_cards(self):  # type: ignore[override]
        return []


def _run_record(destinations: list[Destination] | None = None) -> RunRecord:
    run = RunRecord(report_name="AlertsTest")
    for dest in destinations or []:
        run.destinations.append(
            DestinationOutcome(
                destination_label=dest.describe(),
                destination_type=dest.key or "unknown",
            )
        )
    return run


def _resolved(name: str, *, overrides=None) -> dict:
    return {
        "card_id": 99,
        "card_url": f"https://domo.example.com/c/{name}",
        "page_name": "Sales",
        "card_name": name,
        "viz_type": "Bar",
        "image_path": f"/tmp/{name}.png",
        "overrides": overrides or {},
    }


# ---- card-level send_when ----


def test_card_level_send_when_false_skips_all_destinations(monkeypatch, tmp_path):
    # Stub out image editing so tests don't touch real files.
    monkeypatch.setattr("app.utils.image_util.edit_card_images", lambda **kwargs: None)
    report = _Report()
    a = _StubDestination(name="a")
    b = _StubDestination(name="b")
    run = _run_record([a, b])

    # card.value == 0 -> send_when false -> skipped before edit/send
    resolved = [_resolved("X", overrides={"send_when": "card.value > 0", "value": 0})]

    report._dispatch(resolved, [a, b], run)

    assert a.sent == []
    assert b.sent == []

    card_outcomes = run.cards
    assert len(card_outcomes) == 1
    assert card_outcomes[0].skipped is True
    assert "send_when" in (card_outcomes[0].skip_reason or "")


def test_card_level_send_when_true_sends_normally(monkeypatch):
    monkeypatch.setattr("app.utils.image_util.edit_card_images", lambda **kwargs: None)
    report = _Report()
    a = _StubDestination(name="a")
    run = _run_record([a])

    resolved = [_resolved("X", overrides={"send_when": "1 == 1"})]
    report._dispatch(resolved, [a], run)
    assert a.sent == ["X"]


# ---- destination-level send_when ----


def test_destination_level_send_when_splits_traffic(monkeypatch):
    monkeypatch.setattr("app.utils.image_util.edit_card_images", lambda **kwargs: None)
    report = _Report()
    a = _StubDestination(name="execs", send_when="card.page_name == 'Sales'")
    b = _StubDestination(name="data", send_when="card.page_name == 'Marketing'")
    run = _run_record([a, b])

    resolved = [_resolved("Revenue")]  # page_name="Sales"
    report._dispatch(resolved, [a, b], run)

    assert a.sent == ["Revenue"]
    assert b.sent == []
    # The "b" destination records a skip (cards_skipped=1, cards_attempted=0).
    skipped = next(d for d in run.destinations if d.destination_label == b.describe())
    assert skipped.cards_skipped == 1
    assert skipped.cards_attempted == 0


def test_destination_level_invalid_expression_fails_open(monkeypatch):
    monkeypatch.setattr("app.utils.image_util.edit_card_images", lambda **kwargs: None)
    report = _Report()
    a = _StubDestination(name="broken", send_when="card.value > (")
    run = _run_record([a])
    resolved = [_resolved("X", overrides={"value": 100})]
    report._dispatch(resolved, [a], run)
    # Broken expression => allow-send => card delivered
    assert a.sent == ["X"]


def test_card_level_take_precedence_over_destination(monkeypatch):
    monkeypatch.setattr("app.utils.image_util.edit_card_images", lambda **kwargs: None)
    report = _Report()
    a = _StubDestination(name="all", send_when="True")
    b = _StubDestination(name="exec", send_when="True")
    run = _run_record([a, b])

    resolved = [_resolved("X", overrides={"send_when": "False"})]
    report._dispatch(resolved, [a, b], run)

    assert a.sent == []
    assert b.sent == []


# ---- destination send_when plumbs via Destination.__init__ ----


def test_destination_base_extracts_send_when_kwarg():
    d = _StubDestination(send_when="1 == 1")
    assert d.send_when == "1 == 1"
    assert d.dry_run is False


def test_destination_base_empty_send_when_normalized_to_none():
    d = _StubDestination(send_when="")
    assert d.send_when is None


# ---- registry integration ----


def test_registry_wires_send_when_through_yaml_spec():
    from app.destinations.registry import build_destination

    d = build_destination(
        {
            "type": "slack",
            "channel_name": "x",
            "send_when": "card.page_name == 'Sales'",
        }
    )
    assert d.send_when == "card.page_name == 'Sales'"


# ---- fail-open on evaluator errors ----


def test_card_send_when_with_error_fails_open(monkeypatch):
    monkeypatch.setattr("app.utils.image_util.edit_card_images", lambda **kwargs: None)
    report = _Report()
    a = _StubDestination(name="a")
    run = _run_record([a])
    resolved = [_resolved("X", overrides={"send_when": "card.value > ("})]
    report._dispatch(resolved, [a], run)
    # Invalid expression => allow => delivered.
    assert a.sent == ["X"]
