"""Busca o HTML de uma URL: httpx por padrão, Playwright para sites que dependem de JavaScript."""

import httpx

USER_AGENT = "Mozilla/5.0 (compatible; BJJCrawler/0.1)"
TIMEOUT_SECONDS = 30


def fetch_html(url: str, use_js: bool = False) -> str:
    if use_js:
        return _fetch_with_browser(url)
    with httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _fetch_with_browser(url: str) -> str:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.goto(url, wait_until="networkidle", timeout=TIMEOUT_SECONDS * 1000)
            return page.content()
        finally:
            browser.close()
