# -*- coding: utf-8 -*-
"""Headless tests for the GUI controller's worker-to-UI event contract."""
import queue

import tarjimly
import tarjimly_core as core


def make_app():
    app = object.__new__(tarjimly.App)
    app.events = queue.Queue()
    app.cfg = {"source_languages": ["en"], "join_lines": True}
    return app


def test_translate_only_emits_full_result(monkeypatch):
    app = make_app()
    monkeypatch.setattr(core, "translate_text", lambda text, target, **kwargs: "translated")
    app._translate_only("original", True, "ar")
    assert app.events.get_nowait() == ("result", "original", "translated", "ar")


def test_translate_only_emits_translation_for_retranslate(monkeypatch):
    app = make_app()
    monkeypatch.setattr(core, "translate_text", lambda text, target: "translated")
    app._translate_only("edited", False, "en")
    assert app.events.get_nowait() == ("translation", "translated", "en")


def test_ocr_worker_emits_full_result(monkeypatch):
    app = make_app()
    monkeypatch.setattr(core, "ocr_image", lambda image, languages: "recognized text")
    monkeypatch.setattr(core, "clean_text", lambda text, join: text)
    monkeypatch.setattr(core, "translate_text", lambda text, target: "translated")
    app._ocr_and_translate(object(), "ar")
    assert app.events.get_nowait() == ("status", "جاري الترجمة ...")
    assert app.events.get_nowait() == ("result", "recognized text", "translated", "ar")


def test_worker_errors_are_forwarded_to_ui(monkeypatch):
    app = make_app()

    def fail(*args, **kwargs):
        raise RuntimeError("translation failed")

    monkeypatch.setattr(core, "translate_text", fail)
    app._translate_only("original", True, "ar")
    assert app.events.get_nowait() == ("error", "translation failed")
