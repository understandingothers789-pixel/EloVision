"""Real browser checks. Synthetic policy fixtures are confined to one rendering test."""

import json
import os

import chess
import pytest

pytestmark = pytest.mark.browser
BASE_URL = os.environ.get("ELOVISION_BROWSER_URL")


@pytest.fixture
def page():
    if not BASE_URL:
        pytest.skip("Set ELOVISION_BROWSER_URL to a running local ELO Vision server")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        executable = os.environ.get("ELOVISION_CHROMIUM")
        browser = pw.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        yield page
        browser.close()


def test_browser_real_pgn_navigation_fen_flip_and_slider(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE_URL)
    page.locator(".square").nth(63).wait_for()
    assert page.locator(".square").count() == 64
    assert page.locator(".piece").count() == 32
    page.locator("#pgn-file").set_input_files("samples/opera-game.pgn")
    page.get_by_role("button", name="e4", exact=True).wait_for()
    page.get_by_role("button", name="e4", exact=True).click()
    assert "black to move" in page.locator("#board").get_attribute("aria-label")
    assert page.locator('[data-square="e4"] img').get_attribute("alt") == "White pawn on e4"
    assert page.locator(".move-button.selected").text_content() == "e4"
    page.locator("h1").click()
    page.keyboard.press("ArrowRight")
    assert page.locator(".move-button.selected").text_content() == "e5"
    page.locator("#elo").fill("2200")
    assert page.locator("#matchup").text_content() == "2200 vs. 2200"
    assert page.locator(".move-button.selected").text_content() == "e5"
    page.locator("#flip").click()
    assert page.locator(".square").first.get_attribute("data-square") == "h1"
    page.locator("#last").click()
    assert "Checkmate" in page.locator("#turn").text_content()
    page.locator("#fen-open").click()
    page.locator("#fen-input").fill("invalid fen")
    page.get_by_role("button", name="Explore position").click()
    page.locator("#fen-error").filter(has_text="FEN").wait_for()
    page.locator("#fen-input").fill(chess.STARTING_FEN)
    page.get_by_role("button", name="Explore position").click()
    page.locator("#fen-dialog").wait_for(state="hidden")
    assert page.locator("#next").is_disabled()
    assert not errors
    # Both narrow layouts must keep the document within the viewport.
    for width in [1024, 390]:
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_browser_comparison_spectrum_chart_and_exports_with_test_fixture(page, tmp_path):
    """Validate presentation with an explicit test policy; does not validate Maia inference."""
    requested = []

    def fixture(route):
        data = json.loads(route.request.post_data)
        requested.append(data)
        board = chess.Board(data["fen"])
        legal = list(board.legal_moves)
        predictions = []
        matchups = data.get("matchups") or [
            {"player_elo": rating, "opponent_elo": rating} for rating in data["ratings"]
        ]
        for matchup in matchups:
            rating = matchup["player_elo"]
            values = [i + rating / 100 for i in range(len(legal))]
            total = sum(values)
            moves = sorted(
                [
                    {"uci": m.uci(), "san": board.san(m), "probability": v / total}
                    for m, v in zip(legal, values)
                ],
                key=lambda m: -m["probability"],
            )
            for rank, move in enumerate(moves, 1):
                move["rank"] = rank
            predictions.append(
                {
                    "schema_version": "1.0",
                    "player_elo": rating,
                    "opponent_elo": matchup["opponent_elo"],
                    "moves": moves,
                    "probability_sum": 1,
                    "model": {"id": "browser-test-fixture"},
                    "cached": False,
                }
            )
        route.fulfill(json={"predictions": predictions})

    page.route("**/api/v1/analyze", fixture)
    page.goto(BASE_URL)
    page.locator(".move-prediction").nth(4).wait_for()
    assert len(requested) and requested[0]["matchups"] == [
        {"player_elo": 1800, "opponent_elo": 1800}
    ]
    assert page.locator("#workspace-analysis").get_attribute("aria-selected") == "true"
    page.locator("#workspace-explorer").click()
    assert "explorer-layout" in page.locator(".workspace").get_attribute("class")
    page.locator("#tab-explore").click()
    page.locator(".move-prediction").nth(4).wait_for()
    page.locator("#maia-move-limit").select_option("all")
    assert page.locator(".move-prediction").count() == 20
    page.locator("#tab-compare").click()
    page.locator(".compare-table tbody tr").nth(19).wait_for()
    assert requested[-1]["ratings"] == [1000, 2400]
    page.locator("#compare-sort").select_option("positive")
    deltas = page.locator(".compare-table tbody tr td:last-child").all_text_contents()
    assert [float(v) for v in deltas] == sorted([float(v) for v in deltas], reverse=True)
    page.locator("#tab-spectrum").click()
    page.locator("#chart svg").wait_for()
    assert requested[-1]["ratings"] == list(range(400, 3001, 200))
    assert page.locator(".spectrum-table thead th").count() == 15
    assert page.locator(".chart-dot").count() == 14
    options = page.locator("#chart-move option").all_text_contents()
    page.locator("#chart-move").select_option(index=len(options) - 1)
    assert page.locator("#chart svg > title").text_content().startswith("Probability of")
    # The real API must export its own computed policy, not the browser fixture.
    page.route(
        "**/api/v1/export",
        lambda route: route.fulfill(
            body='{"schema_version":"test-fixture"}',
            content_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="fixture.json"'},
        ),
    )
    with page.expect_download() as download_info:
        page.locator("#export-json").click()
    download_info.value.save_as(tmp_path / "export.json")
    assert json.loads((tmp_path / "export.json").read_text())["schema_version"] == "test-fixture"
    page.locator("#workspace-analysis").click()
    assert "analysis-layout" in page.locator(".workspace").get_attribute("class")
    assert page.locator("#dual-view").is_visible()
    assert page.locator("#workspace-analysis").get_attribute("aria-selected") == "true"


def test_browser_does_not_display_stale_analysis(page):
    calls = []

    def fixture(route):
        data = json.loads(route.request.post_data)
        rating = data.get("matchups", [{"player_elo": data.get("ratings", [1600])[0]}])[0][
            "player_elo"
        ]
        calls.append(rating)
        route.fulfill(status=503, json={"error": {"message": f"Test rating {rating}"}})

    page.route("**/api/v1/analyze", fixture)
    page.goto(BASE_URL)
    page.get_by_text("Test rating 1800", exact=True).wait_for()
    page.locator("#elo").fill("1000")
    page.locator("#elo").fill("2400")
    page.get_by_text("Test rating 2400", exact=True).wait_for()
    assert not page.get_by_text("Test rating 1000", exact=True).count()
    assert calls[-1] == 2400


def test_browser_switches_between_dual_and_pure_stockfish_views(page):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def fixture(route):
        data = json.loads(route.request.post_data)
        board = chess.Board(data["fen"])
        matchups = data.get("matchups") or [
            {"player_elo": rating, "opponent_elo": rating} for rating in data["ratings"]
        ]
        predictions = []
        for matchup in matchups:
            moves = [
                {
                    "uci": move.uci(),
                    "san": board.san(move),
                    "probability": 1 / board.legal_moves.count(),
                    "rank": rank,
                }
                for rank, move in enumerate(board.legal_moves, 1)
            ]
            predictions.append(
                {
                    "player_elo": matchup["player_elo"],
                    "opponent_elo": matchup["opponent_elo"],
                    "moves": moves,
                    "cached": False,
                    "elapsed_ms": 1,
                }
            )
        route.fulfill(json={"predictions": predictions})

    page.route("**/api/v1/analyze", fixture)
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={
                "available": True,
                "name": "Stockfish 19 browser fixture",
                "channel": "official19",
            }
        ),
    )
    page.route(
        "**/api/v1/engine/analyze",
        lambda route: route.fulfill(
            json={
                "engine": "Stockfish 19 browser fixture",
                "channel": "official19",
                "depth": 16,
                "lines": [
                    {
                        "rank": 1,
                        "uci": "e2e4",
                        "san": "e4",
                        "score_cp": 35,
                        "mate": None,
                        "score": "+0.35",
                        "pv": ["e4", "e5", "Nf3"],
                        "depth": 16,
                    },
                    {
                        "rank": 2,
                        "uci": "d2d4",
                        "san": "d4",
                        "score_cp": 21,
                        "mate": None,
                        "score": "+0.21",
                        "pv": ["d4", "d5", "c4"],
                        "depth": 16,
                    },
                ],
            }
        ),
    )
    page.goto(BASE_URL)
    page.locator("#dual-human-moves .move-prediction").nth(4).wait_for()
    page.locator("#stockfish-results .stockfish-line").nth(1).wait_for()
    assert page.locator("#dual-results .dual-column").count() == 2
    assert page.locator("#maia-gauge-marker").text_content().endswith("%")
    assert page.locator("#sf-gauge-marker").text_content() == "+0.35"
    assert page.locator(".stockfish-line .engine-pv").first.is_hidden()
    page.locator("#show-variations").check()
    assert page.locator(".stockfish-line .engine-pv").first.is_visible()
    page.locator("#view-stockfish").click()
    assert "pure-stockfish" in page.locator("#dual-results").get_attribute("class")
    assert page.locator(".human-column").is_hidden()
    page.locator("#view-dual").click()
    assert "pure-stockfish" not in page.locator("#dual-results").get_attribute("class")
    assert page.locator(".human-column").is_visible()
    page.locator("#stockfish-panel > summary").click()
    assert page.locator("#stockfish-channel").is_visible()
    page.locator("#stockfish-channel").select_option("development")
    assert "tests.stockfishchess.org" in page.locator("#stockfish-download").get_attribute("href")
    assert not errors


def test_browser_upload_accepts_150_mib_engine_file(page):
    requested = []
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={"available": False, "name": None, "channel": "official19"}
        ),
    )

    def install(route):
        requested.append(route.request.headers.get("x-engine-filename"))
        route.fulfill(
            json={
                "available": True,
                "name": "Stockfish 19 browser fixture",
                "channel": "official19",
            }
        )

    page.route("**/api/v1/engine/install", install)
    page.goto(BASE_URL)
    page.locator("#workspace-explorer").click()
    page.locator("#stockfish-panel summary").click()
    page.locator("#stockfish-file").evaluate(
        "input => { const file = new File(['MZ'], "
        "'stockfish-windows-x86-64-universal.exe'); "
        "Object.defineProperty(file, 'size', { configurable: true, "
        "value: 150 * 1024 * 1024 }); const transfer = new DataTransfer(); "
        "transfer.items.add(file); input.files = transfer.files; "
        "input.dispatchEvent(new Event('change', { bubbles: true })); }"
    )
    page.get_by_text("Stockfish 19 browser fixture · ready", exact=True).wait_for()
    assert requested == ["stockfish-windows-x86-64-universal.exe"]
