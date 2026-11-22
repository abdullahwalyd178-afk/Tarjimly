# -*- coding: utf-8 -*-
"""Headless tests - no screen, no internet needed (translation is mocked).

Run:  python test_core.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tarjimly_core as core


def test_config():
    cfg = core.normalize_config({"source_languages": ["en", "xx", "fr", "fr", "de", "es", "ja"],
                                 "default_target": "zz"})
    assert cfg["source_languages"] == ["en", "fr", "de", "es"], cfg  # unknown dropped, dedup, max 4
    assert cfg["default_target"] == "ar"
    assert core.normalize_config({"source_languages": []})["source_languages"] == core.DEFAULT_CONFIG["source_languages"]
    assert core.normalize_config({"source_languages": None})["source_languages"] == core.DEFAULT_CONFIG["source_languages"]
    assert core.normalize_config({"source_languages": "en"})["source_languages"] == core.DEFAULT_CONFIG["source_languages"]
    assert len(core.DEFAULT_CONFIG["source_languages"]) == 4
    assert "en" in core.DEFAULT_CONFIG["source_languages"]
    print("ok config")


def test_join_lines():
    t = "This is a long sentence that was\nwrapped by the screen and keeps\ngoing here.\nNew sentence."
    assert core.join_lines(t) == (
        "This is a long sentence that was wrapped by the screen and keeps going here.\nNew sentence."
    )
    assert core.join_lines("inter-\nnational") == "international"
    assert core.join_lines("你好\n世界") == "你好世界"
    assert core.join_lines("a\n\nb") == "a\nb"
    print("ok join_lines")


def test_clean_text_cjk_spaces():
    assert core.clean_text("你 好 世 界") == "你好世界"
    assert core.clean_text("こ ん に ち は hello world") == "こんにちは hello world"
    assert core.clean_text("line one\nline two", join=False) == "line one\nline two"
    print("ok clean_text")


def test_chunks():
    text = "\n".join(["word " * 50] * 40)
    chunks = core.split_chunks(text, limit=1000)
    assert all(len(c) <= 1000 for c in chunks)
    assert "\n".join(chunks).replace("\n", " ").split() == text.replace("\n", " ").split()
    assert core.split_chunks("x" * 2500, limit=1000) == ["x" * 1000, "x" * 1000, "x" * 500]
    print("ok chunks")


class FakeTranslator:
    def __init__(self, fail_first=0):
        self.calls, self.fail_first = [], fail_first

    def translate(self, text):
        self.calls.append(text)
        if self.fail_first:
            self.fail_first -= 1
            raise ConnectionError("flaky")
        return "T:" + text


def test_translate():
    fake = FakeTranslator()
    assert core.translate_text("hello", "ar", lambda: fake) == "T:hello"
    assert core.translate_text("   ", "ar", lambda: fake) == ""
    flaky = FakeTranslator(fail_first=1)  # one failure is retried
    assert core.translate_text("hi", "en", lambda: flaky) == "T:hi"
    dead = FakeTranslator(fail_first=99)  # persistent failure is reported
    try:
        core.translate_text("hi", "en", lambda: dead, ollama_fallback=False)
        raise AssertionError("should have raised")
    except ConnectionError:
        pass
    try:
        core.translate_text("hi", "fr", lambda: fake)
        raise AssertionError("fr is not a supported target")
    except ValueError:
        pass
    # A Google rate-limit response should use Ollama immediately, without retrying Google.
    rate_limited = FakeTranslator(fail_first=99)
    original_fallback = core.translate_with_ollama
    try:
        core.translate_with_ollama = lambda text, target, base_url, model: "LOCAL:" + text
        assert core.translate_text("hello", "ar", lambda: rate_limited) == "LOCAL:hello"
        assert len(rate_limited.calls) == 1
    finally:
        core.translate_with_ollama = original_fallback
    print("ok translate (mocked)")


def test_real_translator_object_accepts_our_codes():
    try:
        from deep_translator import GoogleTranslator
    except ImportError:
        print("skip deep_translator not installed")
        return
    for tgt in core.TARGETS:
        GoogleTranslator(source="auto", target=tgt)  # raises if the code is invalid
    print("ok deep_translator accepts ar/en")


def test_ocr_roundtrip():
    from PIL import Image, ImageDraw, ImageFont

    if not core.find_tesseract():
        print("skip OCR: tesseract not installed")
        return
    failed = core.download_tessdata(["eng"])
    if failed:
        print("skip OCR: could not download eng.traineddata (offline?)")
        return

    def render(text, dark=False, size=34):
        bg, fg = ((20, 20, 20), (235, 235, 235)) if dark else ((255, 255, 255), (0, 0, 0))
        font = None
        for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "DejaVuSans.ttf", "arial.ttf"):
            try:
                font = ImageFont.truetype(p, size)
                break
            except Exception:
                pass
        img = Image.new("RGB", (900, 130), bg)
        ImageDraw.Draw(img).text((20, 20), text, fill=fg, font=font)
        return img

    for dark in (False, True):  # normal and dark-mode screens
        got = core.ocr_image(render("Hello world from the screen", dark), ["en"])
        assert "Hello world" in got and "screen" in got, (dark, got)
    print("ok OCR light + dark backgrounds")


if __name__ == "__main__":
    test_config()
    test_join_lines()
    test_clean_text_cjk_spaces()
    test_chunks()
    test_translate()
    test_real_translator_object_accepts_our_codes()
    test_ocr_roundtrip()
    print("ALL TESTS PASSED")
