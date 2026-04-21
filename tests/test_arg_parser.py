"""Tests for the CLI argument parser."""

from __future__ import annotations

import pytest

from app.configuration.arg_parser.arg_parser_config import configure_arg_parser


def test_list_mode_accepts_multiple_names():
    parser = configure_arg_parser()
    args = parser.parse_args(["--list", "alpha", "beta"])
    assert args.list == ["alpha", "beta"]


def test_modes_are_mutually_exclusive():
    parser = configure_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--list", "alpha", "--all"])


def test_one_mode_required():
    parser = configure_arg_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_scaffold_with_name():
    parser = configure_arg_parser()
    args = parser.parse_args(["--scaffold", "--name", "my_report"])
    assert args.scaffold is True
    assert args.name == "my_report"


def test_validate_flag():
    parser = configure_arg_parser()
    args = parser.parse_args(["--validate"])
    assert args.validate is True


def test_scheduler_flag():
    parser = configure_arg_parser()
    args = parser.parse_args(["--scheduler"])
    assert args.scheduler is True


def test_all_flag():
    parser = configure_arg_parser()
    args = parser.parse_args(["--all"])
    assert args.all is True
