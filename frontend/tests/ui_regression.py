"""Check the five UI review fixes without creating payment records.

Run with Python Playwright and Google Chrome installed:
    python3 -B tests/ui_regression.py
"""

import json
import tempfile
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def check_readability(page):
    samples = page.locator(".stat small, .tx span, .lede, .leg-main span, .payment-notice").evaluate_all("""elements => elements.map(el => {
        const style = getComputedStyle(el);
        let parent = el;
        while (getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent = parent.parentElement;
        return {text: el.textContent, font: parseFloat(style.fontSize), foreground: style.color.match(/[\\d.]+/g).slice(0, 3).map(Number),
                background: getComputedStyle(parent).backgroundColor.match(/[\\d.]+/g).slice(0, 3).map(Number)};
    })""")
    for sample in samples:
        luminances = []
        for rgb in (sample["foreground"], sample["background"]):
            channels = [value / 255 for value in rgb]
            linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
            luminances.append(sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722))))
        ratio = (max(luminances) + 0.05) / (min(luminances) + 0.05)
        assert sample["font"] >= 14, sample
        assert ratio >= 4.5, (sample, ratio)


def check_ui(browser, width, height, artifacts):
    context = browser.new_context(viewport={"width": width, "height": height}, has_touch=width < 620)
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto("http://127.0.0.1:5180/", wait_until="networkidle")
    nav = page.get_by_role("navigation", name="Main navigation")
    expect(nav.get_by_role("button", name="Split rules")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    check_readability(page)
    if width < 620:
        assert page.get_by_role("button", name="Edit", exact=True).bounding_box()["y"] < height - 84
    page.screenshot(path=str(artifacts / f"overview-{width}.png"), full_page=True)

    nav.get_by_role("button", name="Split rules").click()
    stock = page.get_by_role("spinbutton", name="Stock reserve")
    expect(stock).to_have_value("20")
    expect(page.get_by_text("Reloading restores the default split", exact=False)).to_be_visible()
    stock.focus()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.matches(':focus-visible')")
    assert page.evaluate("parseFloat(getComputedStyle(document.activeElement.parentElement).outlineWidth) >= 2")
    page.screenshot(path=str(artifacts / f"rules-{width}.png"), full_page=True)
    stock.fill("80")
    page.get_by_role("button", name="Back", exact=True).click()
    nav.get_by_role("button", name="Split rules").click()
    expect(stock).to_have_value("20")

    stock.fill("101")
    expect(page.get_by_role("alert")).to_contain_text("exceed 100%")
    expect(page.get_by_role("button", name="Use this split")).to_be_disabled()
    stock.fill("80")
    page.get_by_role("spinbutton", name="Salaries").fill("0")
    page.get_by_role("spinbutton", name="Maintenance").fill("0")
    page.get_by_role("button", name="Use this split").click()
    expect(page.locator(".mini-rule")).to_contain_text("80% stock")
    page.get_by_label("Sale total").focus()
    assert page.evaluate("parseFloat(getComputedStyle(document.activeElement.parentElement).outlineWidth) >= 2")
    page.get_by_label("Sale total").fill("0")
    page.get_by_role("button", name="Calculate & save sale").click()
    expect(page.get_by_role("alert")).to_contain_text("Enter a valid sale amount")
    page.get_by_label("Sale total").fill("100.00")
    check_readability(page)
    page.screenshot(path=str(artifacts / f"checkout-{width}.png"), full_page=True)

    requests = []
    page.route("**/api/sales", lambda route: requests.append(route))
    page.get_by_role("button", name="Calculate & save sale").click()
    expect(page.get_by_role("button", name="Preparing…")).to_be_disabled()
    requests.pop().fulfill(status=502, content_type="application/json", body='{"detail":"Payment service unavailable. Try again."}')
    expect(page.get_by_role("alert")).to_contain_text("Try again")
    expect(page.get_by_label("Sale total")).to_have_value("100.00")

    fixture = {"amount": 100, "split": {"supplier": 80, "salaries": 0, "maintenance": 0, "profit": 20},
               "payment": {"id": "ui-check-payment-not-persisted", "status": "PENDING", "shopId": "kwikpay-demo-shop"}}
    for action in ("New sale", "Done"):
        page.get_by_role("button", name="Calculate & save sale").click()
        expect(page.get_by_role("button", name="Preparing…")).to_be_disabled()
        request = requests.pop()
        assert request.request.post_data_json["supplier"] == 80
        request.fulfill(status=201, content_type="application/json", body=json.dumps(fixture))
        expect(page.get_by_role("status")).to_have_text("Sale saved · Payment pending")
        expect(page.get_by_text("No funds have moved.", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Wallet integration pending")).to_have_count(0)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        check_readability(page)
        if action == "New sale":
            reference = page.get_by_text("ui-check-payment-not-persisted", exact=True)
            expect(reference).not_to_be_visible()
            page.locator("summary").click()
            expect(reference).to_be_visible()
            page.locator("summary").click()
            page.screenshot(path=str(artifacts / f"pending-{width}.png"), full_page=True)
        page.get_by_role("main").get_by_role("button", name=action, exact=True).click()

    nav.get_by_role("button", name="Split rules").click()
    expect(stock).to_have_value("80")
    page.reload()
    nav.get_by_role("button", name="Split rules").click()
    expect(stock).to_have_value("20")
    assert not errors, errors
    context.close()
    print(f"PASS {width}x{height}: labels, focus, readable text/contrast, navigation, draft/apply, loading/error/retry, pending actions")


if __name__ == "__main__":
    artifacts = Path(tempfile.gettempdir()) / "kwikpay-ui-taste"
    artifacts.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        for width, height in ((1440, 1000), (390, 844), (320, 800), (768, 1024)):
            check_ui(browser, width, height, artifacts)
        browser.close()
    print(f"Screenshots: {artifacts}")
