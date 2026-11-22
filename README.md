# Tarjimly | ترجملي

A lightweight Windows desktop utility that translates text visible anywhere on your screen.

## How it works

- **Screen region:** take a local screenshot, select a rectangle, and extract text with Tesseract OCR.
- **Selected text:** select text in any app and use the selection shortcut to copy and translate it.
- Translate into **Arabic** or **English**.

**Privacy:** screenshots are processed locally. Tarjimly sends the extracted text—not the screenshot—to Google Translate for translation. An internet connection is required for translation and first-time OCR language downloads.

## Install and run

1. Install [Tesseract OCR for Windows](https://github.com/UB-Mannheim/tesseract/wiki), or let the installer try to install it with `winget`.
2. Download or clone this repository.
3. Double-click `Install-And-Run.bat`.

The installer creates a local `.venv`, installs the Python dependencies, and starts Tarjimly. The first launch downloads the selected Tesseract language files into `tessdata/`.

## Shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+Alt+T` | Drag a rectangle around text on the screen and translate it. |
| `Ctrl+Alt+S` | Translate text currently selected in another app. |
| `Esc` | Cancel region selection. |

You can also use the two buttons in the app window.

## OCR source languages

English, Chinese (Simplified), Japanese, Korean, French, Spanish, German, Russian, Turkish, Italian, Portuguese, and Arabic are supported. Up to four source languages are active at once; the default set is English, Chinese, Japanese, and Korean.

After the first run, edit `config.json` beside the app to change `source_languages` (use the language keys from `tarjimly_core.py`). The target language, always-on-top setting, and shortcuts are also stored there.

## Diagnostics

Run `Install-And-Run.bat --check` to check Tesseract, required Python packages, language data, and internet connectivity.

## Development and tests

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pytest -q -k "not ocr_roundtrip"
```

The OCR round-trip test is optional and requires a working Tesseract installation plus the English trained-data file. GitHub Actions runs the headless test suite on Python 3.10–3.13.

## Requirements

- Windows 10/11
- Python 3.9 or newer with Tkinter
- Tesseract OCR
- Internet access for Google Translate and initial language-data downloads
