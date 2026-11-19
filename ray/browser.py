"""A real browser window Ray can drive, like Comet's assistant.

Uses Playwright with a persistent profile in ~/.ray/browser, so anything you
sign in to (Gmail, LinkedIn, booking sites...) stays signed in next time.
Runs on its own thread because Playwright objects must stay on one thread.
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import Path
from typing import Any, Callable, Optional

PROFILE_DIR = Path.home() / ".ray" / "browser"
MAX_TEXT = 6000

# Tags every visible interactive element with a number Claude can refer to.
_SCAN_JS = r"""
() => {
  const selector = 'a[href], button, input:not([type=hidden]), textarea, select, summary, [role=button], [role=link], [role=tab], [role=menuitem], [role=option], [role=checkbox], [role=radio], [role=combobox], [contenteditable=true]';
  document.querySelectorAll('[data-ray-id]').forEach(e => e.removeAttribute('data-ray-id'));
  const items = [];
  let n = 0;
  for (const el of document.querySelectorAll(selector)) {
    const r = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    if (r.width < 2 || r.height < 2 || style.visibility === 'hidden' || style.display === 'none') continue;
    if (r.bottom < 0 || r.top > innerHeight * 3) continue;
    n += 1;
    el.setAttribute('data-ray-id', String(n));
    const tag = el.tagName.toLowerCase();
    const kind = el.getAttribute('role') || (tag === 'input' ? 'input:' + (el.type || 'text') : tag);
    let label = (el.getAttribute('aria-label') || el.innerText || el.value || el.placeholder || el.title || el.name || el.alt || '').trim().replace(/\s+/g, ' ');
    if (tag === 'select') label = (el.getAttribute('aria-label') || el.name || el.id || 'dropdown') + ' = "' + (el.selectedOptions[0] ? el.selectedOptions[0].text.trim() : '') + '"';
    if (tag === 'select') label += ' [options: ' + Array.from(el.options).slice(0, 15).map(o => o.text.trim()).join(' | ') + ']';
    if (el.checked) label += ' [checked]';
    items.push('[' + n + '] ' + kind + ' "' + label.slice(0, 90) + '"');
    if (n >= 150) break;
  }
  return { title: document.title, url: location.href, text: document.body ? document.body.innerText : '', elements: items };
}
"""


class BrowserError(RuntimeError):
    pass


class Browser:
    def __init__(self) -> None:
        self._tasks: "queue.Queue[tuple[Callable[[], Any], queue.Queue]]" = queue.Queue()
        self._thread: Optional[threading.Thread] = None
        self._context = None
        self._page = None

    @staticmethod
    def available() -> bool:
        try:
            import playwright  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------ threading
    def _call(self, fn: Callable[[], Any], timeout: float = 60) -> Any:
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True, name="ray-browser")
            self._thread.start()
        reply: queue.Queue = queue.Queue()
        self._tasks.put((fn, reply))
        try:
            ok, value = reply.get(timeout=timeout)
        except queue.Empty as exc:
            raise BrowserError("The browser took too long to respond.") from exc
        if not ok:
            raise value
        return value

    def _loop(self) -> None:
        while True:
            fn, reply = self._tasks.get()
            try:
                reply.put((True, fn()))
            except Exception as exc:  # report to the caller, keep the thread alive
                reply.put((False, exc if isinstance(exc, BrowserError) else BrowserError(str(exc))))

    # --------------------------------------------------------------- pages
    def _ensure(self):
        if self._context is not None:
            try:
                if self._page is None or self._page.is_closed():
                    pages = [p for p in self._context.pages if not p.is_closed()]
                    self._page = pages[-1] if pages else self._context.new_page()
                return self._page
            except Exception:
                self._context = None  # the window was closed by the user
        from playwright.sync_api import sync_playwright

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        playwright = sync_playwright().start()
        last_error: Optional[Exception] = None
        custom = os.getenv("RAY_BROWSER_PATH")  # any Chromium-based browser, e.g. Brave
        options = [{"executable_path": custom}] if custom else [{"channel": "chrome"}, {"channel": "msedge"}, {}]
        for option in options:  # your installed Chrome/Edge first
            try:
                self._context = playwright.chromium.launch_persistent_context(
                    str(PROFILE_DIR), headless=False, no_viewport=True, args=["--start-maximized"], **option,
                )
                break
            except Exception as exc:
                last_error = exc
        if self._context is None:
            raise BrowserError(f"Could not start a browser: {last_error}")
        self._context.on("page", self._on_new_page)
        pages = self._context.pages
        self._page = pages[0] if pages else self._context.new_page()
        return self._page

    def _on_new_page(self, page) -> None:
        self._page = page  # follow links that open in a new tab

    def _settle(self, page) -> None:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
            page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

    def _snapshot(self) -> str:
        page = self._ensure()
        self._settle(page)
        data = page.evaluate(_SCAN_JS)
        text = " ".join(data["text"].split())
        if len(text) > MAX_TEXT:
            text = text[:MAX_TEXT] + " ...[more below, scroll to see it]"
        elements = "\n".join(data["elements"]) or "(none visible)"
        return f"URL: {data['url']}\nTITLE: {data['title']}\n\nPAGE TEXT:\n{text}\n\nINTERACTIVE ELEMENTS:\n{elements}"

    def _element(self, ref: int):
        locator = self._ensure().locator(f'[data-ray-id="{int(ref)}"]')
        if locator.count() == 0:
            raise BrowserError(f"Element [{ref}] is gone. Read the page again to get fresh numbers.")
        return locator.first

    # ------------------------------------------------------------- actions
    def open(self, url: str) -> str:
        if not url.startswith(("http://", "https://", "about:", "file:")):
            url = "https://" + url

        def go():
            self._ensure().goto(url, timeout=30000)
            return self._snapshot()

        return self._call(go)

    def read(self) -> str:
        return self._call(self._snapshot)

    def click(self, ref: int) -> str:
        def go():
            self._element(ref).click(timeout=8000)
            return self._snapshot()

        return self._call(go)

    def type(self, ref: int, text: str, submit: bool = False) -> str:
        def go():
            el = self._element(ref)
            try:
                el.fill(text, timeout=8000)
            except Exception:
                el.click(timeout=5000)
                self._page.keyboard.type(text, delay=20)
            if submit:
                el.press("Enter")
            return self._snapshot()

        return self._call(go)

    def select(self, ref: int, option: str) -> str:
        def go():
            self._element(ref).select_option(label=option, timeout=8000)
            return self._snapshot()

        return self._call(go)

    def press(self, key: str) -> str:
        def go():
            self._ensure().keyboard.press(key)
            return self._snapshot()

        return self._call(go)

    def scroll(self, direction: str = "down") -> str:
        def go():
            page = self._ensure()
            page.mouse.wheel(0, -900 if direction == "up" else 900)
            page.wait_for_timeout(600)
            return self._snapshot()

        return self._call(go)

    def back(self) -> str:
        def go():
            self._ensure().go_back(timeout=15000)
            return self._snapshot()

        return self._call(go)
