from scripts.build_preview import build_preview


def test_preview_is_self_contained_and_has_no_fake_policy(tmp_path):
    html = build_preview(tmp_path / "preview.html").read_text()
    assert '<link rel="stylesheet"' not in html
    assert "<script src=" not in html
    assert "globalThis.ELOVISION_PREVIEW =" in html
    assert "data:image/svg+xml;base64," in html
    assert "No probabilities are simulated." in html
    assert "Paul Morphy" in html
    assert '"probability":' not in html


def test_preview_inside_sandbox_without_network(tmp_path):
    import os

    import pytest

    executable = os.environ.get("ELOVISION_CHROMIUM")
    if not executable:
        pytest.skip("Set ELOVISION_CHROMIUM to run the standalone sandbox preview test")
    from playwright.sync_api import sync_playwright

    html = build_preview(tmp_path / "preview.html").read_text()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        errors, requests = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/*", lambda route: (requests.append(route.request.url), route.abort()))
        # srcdoc with an opaque origin reproduces a chat visualization's isolation.
        page.set_content(
            '<iframe sandbox="allow-scripts" style="width:100%;height:950px"></iframe>'
        )
        page.locator("iframe").evaluate("(frame, html) => frame.srcdoc = html", html)
        frame = page.frame_locator("iframe")
        frame.locator(".square").nth(63).wait_for()
        assert frame.locator(".piece").count() == 32
        assert (
            frame.locator("body").evaluate("el => getComputedStyle(el).backgroundColor")
            == "rgb(17, 22, 20)"
        )
        assert frame.locator(".piece").first.evaluate("el => el.complete && el.naturalWidth > 0")
        frame.locator("#sample").click()
        frame.get_by_role("button", name="e4", exact=True).click()
        assert frame.locator(".move-button.selected").text_content() == "e4"
        frame.locator("#elo").fill("2200")
        assert frame.locator("#matchup").text_content() == "2200 vs. 2200"
        frame.locator("#flip").click()
        assert frame.locator(".square").first.get_attribute("data-square") == "h1"
        frame.get_by_text("Analysis runs in the local app.", exact=True).wait_for()
        assert frame.locator("#import").is_disabled()
        assert not frame.locator(".move-prediction").count()
        assert not requests and not errors
        browser.close()
