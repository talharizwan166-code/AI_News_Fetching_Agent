"""Async connector contract and isolated HTTP/browser implementations."""

import asyncio
import os
import re
import time
from abc import ABC, abstractmethod
from urllib.parse import urlsplit

import httpx
from jsonpath_ng.ext import parse


class ConnectorError(Exception):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class Connector(ABC):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    @abstractmethod
    async def send(self, prompt: str) -> str:
        """Send one independent prompt. Must support concurrent calls and cancellation."""


def render_template(value, prompt):
    # Substitute in parsed JSON values, so quotes/newlines cannot break the payload.
    if isinstance(value, str):
        return value.replace("{{prompt}}", prompt)
    if isinstance(value, list):
        return [render_template(item, prompt) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, prompt) for key, item in value.items()}
    return value


def expand_header(value):
    def replace(match):
        name = match.group(1)
        if name not in os.environ:
            raise ValueError(f"Missing header environment variable: {name}")
        return os.environ[name]
    return re.sub(r"\$\{([A-Za-z_][A-Za-z_0-9]*)\}", replace, value)


class HTTPConnector(Connector):
    def __init__(self, config):
        self.url = config["url"]
        method = config.get("method", "POST")
        if not isinstance(method, str):
            raise ValueError("HTTP method must be a string")
        self.method = method.upper()
        if self.method not in {"POST", "PUT", "PATCH"}:
            raise ValueError("HTTP method must be POST, PUT or PATCH (JSON request body)")
        headers = config.get("headers", {})
        if not isinstance(headers, dict) or any(not isinstance(v, str) for v in headers.values()):
            raise ValueError("headers must be an object of string values")
        self.headers = {key: expand_header(value) for key, value in headers.items()}
        self.template = config.get("request_template", {"message": "{{prompt}}"})
        if not isinstance(self.template, (dict, list)):
            raise ValueError("request_template must be a JSON object or array")
        try:
            self.path = parse(config.get("response_json_path", "$.reply"))
        except Exception as exc:
            raise ValueError("Invalid response_json_path") from exc
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(headers=self.headers, timeout=None, trust_env=False)
        return self

    async def __aexit__(self, *args):
        if self.client is not None:
            await self.client.aclose()

    async def send(self, prompt):
        if self.client is None:
            raise RuntimeError("Use the connector as an async context manager")
        try:
            response = await self.client.request(self.method, self.url, json=render_template(self.template, prompt))
        except httpx.TransportError as exc:
            raise ConnectorError(f"HTTP transport failure ({type(exc).__name__})", retryable=True) from exc
        if not 200 <= response.status_code < 300:
            status = response.status_code
            raise ConnectorError(f"HTTP {status}", retryable=status in {408, 429} or status >= 500)
        try:
            matches = self.path.find(response.json())
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            raise ConnectorError("Response is not valid JSON or does not match the configured path") from exc
        if len(matches) != 1 or not isinstance(matches[0].value, str):
            raise ConnectorError("response_json_path must select exactly one string")
        return matches[0].value


class WidgetConnector(Connector):
    def __init__(self, config):
        self.url = config["url"]
        self.input_selector = config.get("input_selector")
        self.reply_selector = config.get("reply_selector")
        self.submit_selector = config.get("submit_selector")
        for name in ("input_selector", "reply_selector"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"widget requires {name}")
        if self.submit_selector is not None and (not isinstance(self.submit_selector, str) or not self.submit_selector):
            raise ValueError("submit_selector must be a nonempty string")
        self.headless = config.get("headless", True)
        if type(self.headless) is not bool:
            raise ValueError("headless must be boolean")
        self.playwright = self.browser = None

    async def __aenter__(self):
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        try:
            self.browser = await self.playwright.chromium.launch(headless=self.headless)
        except BaseException:
            await self.playwright.stop()
            raise
        return self

    async def __aexit__(self, *args):
        try:
            if self.browser:
                await self.browser.close()
        finally:
            if self.playwright:
                await self.playwright.stop()

    async def send(self, prompt):
        from playwright.async_api import Error as PlaywrightError

        context = await self.browser.new_context()
        try:
            page = await context.new_page()
            page.set_default_timeout(0)  # The runner owns the total attempt deadline.
            await page.goto(self.url, wait_until="domcontentloaded")
            entry = page.locator(self.input_selector)
            await entry.fill(prompt)
            replies = page.locator(self.reply_selector)
            before = await replies.all_text_contents()
            if self.submit_selector:
                await page.locator(self.submit_selector).click()
            else:
                await entry.press("Enter")
            last, stable_since = None, time.monotonic()
            while True:
                current = await replies.all_text_contents()
                if current != before and current and current[-1].strip():
                    if current != last:
                        last, stable_since = current, time.monotonic()
                    elif time.monotonic() - stable_since >= 0.5:
                        return current[-1]
                else:
                    last = None
                await asyncio.sleep(0.05)
        except PlaywrightError as exc:
            # Do not persist page dumps, URLs with tokens or raw browser diagnostics.
            raise ConnectorError(f"Widget operation failed ({type(exc).__name__})") from exc
        finally:
            await context.close()


def create_connector(config) -> Connector:
    if not isinstance(config, dict):
        raise ValueError("Target config must be an object")
    url = config.get("url")
    if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ValueError("Target url must be an absolute HTTP(S) URL")
    kind = config.get("type")
    common = {"name", "type", "url", "runner"}
    specific = {
        "http": {"method", "headers", "request_template", "response_json_path"},
        "widget": {"input_selector", "reply_selector", "submit_selector", "headless"},
    }
    if kind not in specific:
        raise ValueError("Target type must be 'http' or 'widget'")
    unknown = set(config) - common - specific[kind]
    if unknown:
        raise ValueError(f"Unknown target fields: {sorted(unknown)}")
    return HTTPConnector(config) if kind == "http" else WidgetConnector(config)
