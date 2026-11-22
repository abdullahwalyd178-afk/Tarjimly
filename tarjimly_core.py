# -*- coding: utf-8 -*-
"""
Tarjimly | ترجملي — core logic (no GUI here, so it can be tested headless)

Pipeline:  screenshot region -> local OCR (Tesseract) -> clean text -> online translation.
Text that is already selected (copied) skips the OCR step.
"""
from __future__ import annotations

import json
import os
import platform
import re
import shutil
import sys
import urllib.request
from typing import Dict, List, Optional, Tuple

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
TESSDATA_DIR = os.path.join(APP_DIR, "tessdata")
TESSDATA_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{code}.traineddata"

# --------------------------------------------------------------------------
# Languages.  code (Google Translate) -> (label, Tesseract code)
# --------------------------------------------------------------------------
LANGS: Dict[str, Tuple[str, str]] = {
    "en": ("English", "eng"),
    "zh-CN": ("中文 Chinese", "chi_sim"),
    "ja": ("日本語 Japanese", "jpn"),
    "ko": ("한국어 Korean", "kor"),
    "fr": ("Français French", "fra"),
    "es": ("Español Spanish", "spa"),
    "de": ("Deutsch German", "deu"),
    "ru": ("Русский Russian", "rus"),
    "tr": ("Türkçe Turkish", "tur"),
    "it": ("Italiano Italian", "ita"),
    "pt": ("Português Portuguese", "por"),
    "ar": ("العربية Arabic", "ara"),
}
TARGETS = {"ar": "العربية", "en": "English"}
MAX_SOURCE_LANGS = 4

DEFAULT_CONFIG = {
    # The 4 languages the OCR can read (English + 3 others). Change freely,
    # use the codes from LANGS above, e.g. ["en", "fr", "es", "de"].
    "source_languages": ["en", "zh-CN", "ja", "ko"],
    "default_target": "ar",             # ar | en
    "hotkey_region": "<ctrl>+<alt>+t",  # drag a rectangle on the screen
    "hotkey_selection": "<ctrl>+<alt>+s",  # translate the currently selected text
    "always_on_top": True,
    "join_lines": True,                 # merge OCR line breaks inside paragraphs
}


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------
def normalize_config(user_cfg: dict) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(user_cfg, dict):
        cfg.update(user_cfg)

    raw_langs = cfg.get("source_languages", [])
    # A hand-edited or partially written config must not prevent startup.
    if not isinstance(raw_langs, (list, tuple)):
        raw_langs = []
    langs = [c for c in raw_langs if isinstance(c, str) and c in LANGS]
    seen: List[str] = []
    for c in langs:
        if c not in seen:
            seen.append(c)
    cfg["source_languages"] = seen[:MAX_SOURCE_LANGS] or list(DEFAULT_CONFIG["source_languages"])
    if cfg.get("default_target") not in TARGETS:
        cfg["default_target"] = "ar"
    return cfg


def load_config() -> dict:
    user_cfg = {}
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                user_cfg = json.load(fh)
    except Exception as exc:  # a broken config must never kill the app
        print(f"[config] could not read config.json ({exc}); using defaults")
    return normalize_config(user_cfg)


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
    except Exception as exc:
        print(f"[config] could not save config.json ({exc})")


# --------------------------------------------------------------------------
# Tesseract + language data
# --------------------------------------------------------------------------
def find_tesseract() -> Optional[str]:
    path = shutil.which("tesseract")
    if path:
        return path
    if platform.system() == "Windows":
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ]
        for c in candidates:
            if os.path.exists(c):
                return c
    return None


def tess_codes(source_languages: List[str]) -> List[str]:
    return [LANGS[c][1] for c in source_languages if c in LANGS]


def missing_tessdata(codes: List[str]) -> List[str]:
    return [c for c in codes if not os.path.exists(os.path.join(TESSDATA_DIR, f"{c}.traineddata"))]


def download_tessdata(codes: List[str], progress=None) -> List[str]:
    """Download missing Tesseract language files. Returns the codes that failed."""
    os.makedirs(TESSDATA_DIR, exist_ok=True)
    failed = []
    for code in missing_tessdata(codes):
        url = TESSDATA_URL.format(code=code)
        dest = os.path.join(TESSDATA_DIR, f"{code}.traineddata")
        tmp = dest + ".part"
        try:
            if progress:
                progress(f"تحميل ملف اللغة {code} ...")
            req = urllib.request.Request(url, headers={"User-Agent": "Tarjimly/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out)
            if os.path.getsize(tmp) < 100_000:  # an error page, not a model
                raise RuntimeError("downloaded file is too small")
            os.replace(tmp, dest)
        except Exception as exc:
            failed.append(code)
            print(f"[tessdata] failed to download {code}: {exc}")
            if os.path.exists(tmp):
                os.remove(tmp)
    return failed


# --------------------------------------------------------------------------
# Image preprocessing + OCR
# --------------------------------------------------------------------------
def preprocess(img):
    """Grayscale, upscale small crops, fix dark-mode (light text on dark)."""
    from PIL import Image, ImageOps, ImageStat

    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
    img = img.convert("L")
    w, h = img.size
    scale = 3 if (h < 120 or w < 300) else 2 if h < 400 else 1
    if scale > 1:
        img = img.resize((w * scale, h * scale), resample)
    if ImageStat.Stat(img).mean[0] < 110:  # dark background -> invert
        img = ImageOps.invert(img)
    return ImageOps.autocontrast(img)


def ocr_image(img, source_languages: List[str]) -> str:
    import pytesseract

    exe = find_tesseract()
    if not exe:
        raise RuntimeError("Tesseract غير مثبت")
    pytesseract.pytesseract.tesseract_cmd = exe
    os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR

    lang = "+".join(tess_codes(source_languages))
    prepared = preprocess(img)
    text = pytesseract.image_to_string(prepared, lang=lang, config="--psm 6").strip()
    if not text:  # scattered words: try sparse-text mode
        text = pytesseract.image_to_string(prepared, lang=lang, config="--psm 11").strip()
    return text


# --------------------------------------------------------------------------
# Text cleanup
# --------------------------------------------------------------------------
_CJK = r"\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af"
_CJK_SPACE = re.compile(rf"(?<=[{_CJK}]) +(?=[{_CJK}])")
_SENT_END = tuple(".!?:;。！？：；؟…")


def _is_cjk(ch: str) -> bool:
    return bool(re.match(rf"[{_CJK}]", ch))


def join_lines(text: str) -> str:
    """OCR breaks lines where the *screen* wrapped, not where sentences end.
    Merge those breaks so the translator sees whole sentences."""
    out: List[str] = []
    buf = ""
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            if buf:
                out.append(buf)
                buf = ""
            continue
        if not buf:
            buf = line
        elif buf.endswith(_SENT_END):
            out.append(buf)
            buf = line
        elif buf.endswith("-") and line[:1].islower():  # hyphenated word
            buf = buf[:-1] + line
        elif _is_cjk(buf[-1]) or _is_cjk(line[0]):
            buf += line
        else:
            buf += " " + line
    if buf:
        out.append(buf)
    return "\n".join(out)


def clean_text(text: str, join: bool = True) -> str:
    text = _CJK_SPACE.sub("", text)  # Tesseract puts spaces between CJK characters
    text = text.replace("\u200b", "").strip()
    return join_lines(text) if join else text


# --------------------------------------------------------------------------
# Translation (online)
# --------------------------------------------------------------------------
def split_chunks(text: str, limit: int = 4500) -> List[str]:
    chunks, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:  # a single giant line
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks


def translate_text(text: str, target: str, translator_factory=None) -> str:
    """Translate `text` (source language auto-detected) into `target` ('ar' or 'en')."""
    if target not in TARGETS:
        raise ValueError(f"unsupported target language: {target}")
    text = text.strip()
    if not text:
        return ""
    if translator_factory is None:
        from deep_translator import GoogleTranslator

        translator_factory = lambda: GoogleTranslator(source="auto", target=target)
    translator = translator_factory()

    parts = []
    for chunk in split_chunks(text):
        last_exc = None
        for _ in range(2):  # one retry for flaky connections
            try:
                parts.append(translator.translate(chunk) or "")
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
        if last_exc is not None:
            raise last_exc
    return "\n".join(parts)


def internet_ok(timeout: float = 4.0) -> bool:
    try:
        urllib.request.urlopen("https://translate.google.com", timeout=timeout)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------
# Diagnostics:  python tarjimly.py --check
# --------------------------------------------------------------------------
def run_check(cfg: dict) -> int:
    ok = True
    print("Tarjimly check")
    print("=" * 40)
    exe = find_tesseract()
    print(f"Tesseract    : {exe or 'NOT FOUND'}")
    ok &= bool(exe)
    codes = tess_codes(cfg["source_languages"])
    miss = missing_tessdata(codes)
    print(f"Languages    : {', '.join(cfg['source_languages'])}")
    print(f"Language data: {'all present' if not miss else 'missing ' + ', '.join(miss) + ' (downloaded on first run)'}")
    net = internet_ok()
    print(f"Internet     : {'OK' if net else 'cannot reach translate.google.com'}")
    ok &= net
    for mod in ("PIL", "pytesseract", "deep_translator", "pynput"):
        try:
            __import__(mod)
            print(f"{mod:<13}: OK")
        except Exception as exc:
            print(f"{mod:<13}: MISSING ({exc})")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(run_check(load_config()))
