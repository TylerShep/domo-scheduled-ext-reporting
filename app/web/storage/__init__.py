"""Persistence helpers for the web UI (YAML CRUD)."""

from __future__ import annotations

from app.web.storage.yaml_store import YamlStore, YamlStoreError

__all__ = ["YamlStore", "YamlStoreError"]
