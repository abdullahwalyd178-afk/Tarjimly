#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tarjimly | ترجملي — translate any text on your screen.

Two ways to use it (from anywhere, any app):
  Ctrl+Alt+T  ->  drag a rectangle over the text on screen (works on images,
                  videos, PDFs, games ... anything you can see)
  Ctrl+Alt+S  ->  translate the text you have already selected with the mouse

Reading the screen is done locally (Tesseract OCR).  Only the extracted TEXT
is sent to the online translator - never the screenshot.
"""
from __future__ import annotations

import argparse
import ctypes
import platform
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import tarjimly_core as core


def set_dpi_aware() -> None:
    """Make screenshot pixels match Tk coordinates on scaled Windows screens."""
    if platform.system() != "Windows":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# --------------------------------------------------------------------------
# Full-screen overlay to drag a rectangle
# --------------------------------------------------------------------------
class RegionSelector:
    def __init__(self, root: tk.Tk, shot, callback):
        from PIL import ImageEnhance, ImageTk

        self.shot, self.callback = shot, callback
        self.start = None
        self.rect = None

        self.top = tk.Toplevel(root)
        self.top.attributes("-topmost", True)
        self.top.attributes("-fullscreen", True)
        self.top.update_idletasks()
        sw, sh = self.top.winfo_screenwidth(), self.top.winfo_screenheight()
        self.sx, self.sy = shot.width / sw, shot.height / sh

        dim = ImageEnhance.Brightness(shot).enhance(0.5).resize((sw, sh))
        self.photo = ImageTk.PhotoImage(dim)  # keep a reference
        self.canvas = tk.Canvas(self.top, width=sw, height=sh, highlightthickness=0, cursor="cross")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.canvas.create_text(sw // 2, 40, fill="white", font=("Segoe UI", 16, "bold"),
                                text="اسحب لتحديد النص  |  Drag to select  |  Esc = cancel")

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.top.bind("<Escape>", lambda e: self._finish(None))
        self.top.focus_force()

    def _press(self, e):
        self.start = (e.x, e.y)
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#00e676", width=2)

    def _drag(self, e):
        if self.start:
            self.canvas.coords(self.rect, self.start[0], self.start[1], e.x, e.y)

    def _release(self, e):
        if not self.start:
            return
        x0, x1 = sorted((self.start[0], e.x))
        y0, y1 = sorted((self.start[1], e.y))
        if x1 - x0 < 8 or y1 - y0 < 8:  # an accidental click
            self._finish(None)
            return
        box = (int(x0 * self.sx), int(y0 * self.sy), int(x1 * self.sx), int(y1 * self.sy))
        self._finish(self.shot.crop(box))

    def _finish(self, img):
        self.top.destroy()
        self.callback(img)


# --------------------------------------------------------------------------
# Main window
# --------------------------------------------------------------------------
SENTINEL = "\u200b__tarjimly__\u200b"


class App:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.events: "queue.Queue[tuple]" = queue.Queue()
        self.busy = False
        self.selecting = False

        self.root = tk.Tk()
        self.root.title("ترجملي | Tarjimly")
        self.root.geometry("560x620")
        self.root.attributes("-topmost", bool(cfg["always_on_top"]))
        self._build_ui()
        self._start_hotkeys()
        self.root.after(100, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.set_status("جاري تجهيز ملفات اللغات ...")
        threading.Thread(target=self._prepare, daemon=True).start()

    # ---- UI ---------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        font = ("Segoe UI", 11)

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Button(top, text="ترجمة منطقة من الشاشة", command=self.start_region).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(top, text="ترجمة النص المحدد", command=self.start_selection).pack(side="left", expand=True, fill="x", padx=2)

        row = ttk.Frame(self.root)
        row.pack(fill="x", **pad)
        ttk.Label(row, text="الترجمة إلى:").pack(side="left")
        self.target = tk.StringVar(value=self.cfg["default_target"])
        for code, label in core.TARGETS.items():
            ttk.Radiobutton(row, text=label, value=code, variable=self.target,
                            command=self.retranslate).pack(side="left", padx=8)
        self.topmost = tk.BooleanVar(value=bool(self.cfg["always_on_top"]))
        ttk.Checkbutton(row, text="فوق كل النوافذ", variable=self.topmost,
                        command=lambda: self.root.attributes("-topmost", self.topmost.get())).pack(side="right")

        names = " · ".join(core.LANGS[c][0] for c in self.cfg["source_languages"])
        ttk.Label(self.root, text=f"اللغات: {names}", foreground="#666").pack(anchor="w", **pad)

        ttk.Label(self.root, text="النص الأصلي (تقدر تعدّله ثم اضغط إعادة الترجمة):").pack(anchor="w", **pad)
        self.src = tk.Text(self.root, height=9, wrap="word", font=font)
        self.src.pack(fill="both", expand=True, **pad)

        row2 = ttk.Frame(self.root)
        row2.pack(fill="x", **pad)
        ttk.Button(row2, text="إعادة الترجمة", command=self.retranslate).pack(side="left", padx=2)
        ttk.Button(row2, text="نسخ الأصل", command=lambda: self.copy(self.src)).pack(side="left", padx=2)

        ttk.Label(self.root, text="الترجمة:").pack(anchor="w", **pad)
        self.out = tk.Text(self.root, height=9, wrap="word", font=("Segoe UI", 12))
        self.out.tag_configure("rtl", justify="right")
        self.out.pack(fill="both", expand=True, **pad)
        ttk.Button(self.root, text="نسخ الترجمة", command=lambda: self.copy(self.out)).pack(anchor="w", **pad)

        self.status = ttk.Label(self.root, text="", foreground="#0a7")
        self.status.pack(fill="x", padx=10, pady=6)

    def set_status(self, msg: str):
        self.status.config(text=msg)

    def copy(self, widget: tk.Text):
        self.root.clipboard_clear()
        self.root.clipboard_append(widget.get("1.0", "end").strip())
        self.set_status("تم النسخ ✓")

    def show_result(self, original: str, translated: str, target: str):
        self.src.delete("1.0", "end")
        self.src.insert("1.0", original)
        self.show_translation(translated, target)
        self.root.deiconify()
        self.root.lift()

    def show_translation(self, translated: str, target: str):
        self.out.delete("1.0", "end")
        tags = ("rtl",) if target == "ar" else ()
        self.out.insert("1.0", translated, tags)

    # ---- startup ----------------------------------------------------------
    def _prepare(self):
        if not core.find_tesseract():
            self.events.put(("error", "Tesseract غير مثبت. شغّل Install-And-Run.bat أو ثبّته من README."))
            return
        codes = core.tess_codes(self.cfg["source_languages"])
        failed = core.download_tessdata(codes, lambda m: self.events.put(("status", m)))
        if failed:
            self.events.put(("error", "تعذّر تحميل ملفات اللغة: " + ", ".join(failed) + " — تأكد من الإنترنت."))
        else:
            self.events.put(("status", "جاهز ✓  اضغط Ctrl+Alt+T أو Ctrl+Alt+S"))

    def _start_hotkeys(self):
        try:
            from pynput import keyboard

            self.hotkeys = keyboard.GlobalHotKeys({
                self.cfg["hotkey_region"]: lambda: self.events.put(("region",)),
                self.cfg["hotkey_selection"]: lambda: self.events.put(("selection",)),
            })
            self.hotkeys.daemon = True
            self.hotkeys.start()
        except Exception as exc:
            self.hotkeys = None
            self.set_status(f"الاختصارات غير شغالة ({exc}) — استخدم الأزرار.")

    # ---- event loop (everything touching Tk happens here) -----------------
    def _poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "region":
                    self.start_region()
                elif kind == "selection":
                    self.start_selection()
                elif kind == "status":
                    self.set_status(ev[1])
                elif kind == "error":
                    self.busy = False
                    self.set_status("⚠ " + ev[1])
                    self.root.deiconify()
                elif kind == "result":
                    self.busy = False
                    self.show_result(ev[1], ev[2], ev[3])
                    self.set_status("تمت الترجمة ✓")
                elif kind == "translation":
                    self.busy = False
                    self.show_translation(ev[1], ev[2])
                    self.set_status("تمت الترجمة ✓")
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # ---- region mode ------------------------------------------------------
    def start_region(self):
        if self.busy or self.selecting:
            return
        from PIL import ImageGrab

        self.root.withdraw()  # keep this window out of the screenshot
        self.root.update()
        time.sleep(0.2)
        try:
            shot = ImageGrab.grab()
        except Exception as exc:
            self.root.deiconify()
            self.set_status(f"⚠ تعذّر أخذ لقطة الشاشة: {exc}")
            return
        self.selecting = True
        RegionSelector(self.root, shot, self._region_done)

    def _region_done(self, img):
        self.selecting = False
        if img is None:
            self.root.deiconify()
            self.set_status("تم الإلغاء")
            return
        self.busy = True
        self.set_status("جاري قراءة النص ...")
        threading.Thread(target=self._ocr_and_translate, args=(img, self.target.get()), daemon=True).start()

    def _ocr_and_translate(self, img, target: str):
        try:
            text = core.ocr_image(img, self.cfg["source_languages"])
            text = core.clean_text(text, self.cfg["join_lines"])
            if not text:
                self.events.put(("error", "ما قدرتش أقرا نص في المنطقة دي. جرّب تحديد أوضح أو أكبر."))
                return
            self.events.put(("status", "جاري الترجمة ..."))
            translated = core.translate_text(text, target, ollama_fallback=self.cfg.get("ollama_fallback", True), ollama_url=self.cfg.get("ollama_url", "http://127.0.0.1:11434"), ollama_model=self.cfg.get("ollama_model", ""), status_callback=lambda message: self.events.put(("status", message)))
            self.events.put(("result", text, translated, target))

        except Exception as exc:
            self.events.put(("error", f"{exc}"))

    # ---- selected-text mode ----------------------------------------------
    def _clip_get(self):
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            return None

    def start_selection(self):
        if self.busy or self.selecting:
            return
        self.busy = True
        self.set_status("جاري نسخ النص المحدد ...")
        self._prev_clip = self._clip_get()
        self.root.clipboard_clear()
        self.root.clipboard_append(SENTINEL)
        self.root.update()
        self.root.after(250, self._send_copy)  # let the user release the hotkey

    def _restore_clipboard(self):
        """Restore the previous text clipboard, including an originally empty clipboard."""
        previous = getattr(self, "_prev_clip", None)
        try:
            self.root.clipboard_clear()
            if previous is not None:
                self.root.clipboard_append(previous)
        except tk.TclError:
            pass
        finally:
            self._prev_clip = None

    def _send_copy(self):
        try:
            from pynput.keyboard import Controller, Key

            kb = Controller()
            for k in (Key.alt, Key.alt_l, Key.alt_r, Key.shift, Key.ctrl, Key.ctrl_l, Key.ctrl_r):
                try:
                    kb.release(k)
                except Exception:
                    pass
            time.sleep(0.05)
            with kb.pressed(Key.ctrl):
                kb.press("c")
                kb.release("c")
        except Exception as exc:
            self._restore_clipboard()
            self.busy = False
            self.set_status(f"⚠ تعذّر النسخ التلقائي: {exc}")
            return
        self.root.after(350, self._read_copy)

    def _read_copy(self):
        text = self._clip_get()
        self._restore_clipboard()
        if not text or text == SENTINEL or not text.strip():
            self.busy = False
            self.set_status("ما لقيتش نص محدد. حدّد نص بالماوس وجرّب تاني.")
            return
        text = core.clean_text(text, join=False)
        self.set_status("جاري الترجمة ...")
        threading.Thread(target=self._translate_only, args=(text, True, self.target.get()), daemon=True).start()

    def _translate_only(self, text: str, with_original: bool, target: str):
        try:
            translated = core.translate_text(text, target, ollama_fallback=self.cfg.get("ollama_fallback", True), ollama_url=self.cfg.get("ollama_url", "http://127.0.0.1:11434"), ollama_model=self.cfg.get("ollama_model", ""))
            if with_original:
                self.events.put(("result", text, translated, target))
            else:
                self.events.put(("translation", translated, target))

        except Exception as exc:
            self.events.put(("error", f"{exc}"))

    # ---- re-translate (target switched or original edited) ----------------
    def retranslate(self):
        text = self.src.get("1.0", "end").strip()
        if not text or self.busy:
            return
        self.busy = True
        self.set_status("جاري الترجمة ...")
        threading.Thread(target=self._translate_only, args=(text, False, self.target.get()), daemon=True).start()

    def quit(self):
        self.cfg["default_target"] = self.target.get()
        self.cfg["always_on_top"] = bool(self.topmost.get())
        core.save_config(self.cfg)
        if getattr(self, "hotkeys", None):
            self.hotkeys.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Tarjimly - translate text on your screen")
    parser.add_argument("--check", action="store_true", help="diagnose Tesseract, languages and internet, then exit")
    args = parser.parse_args()

    cfg = core.load_config()
    if args.check:
        return core.run_check(cfg)
    set_dpi_aware()
    App(cfg).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
