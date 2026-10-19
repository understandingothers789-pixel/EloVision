"""Real browser checks. Synthetic Maia/engine responses are confined to test routes."""

import json
import os

import chess
import pytest
from playwright.sync_api import expect

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
    page.locator(".game-panel h2").click()
    page.keyboard.press("ArrowRight")
    assert page.locator(".move-button.selected").text_content() == "e5"
    page.locator("#settings-tab-options").click()
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
    for tab in ["analysis", "explorer"]:
        page.locator(f"#workspace-{tab}").click()
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
    page.locator(".spectrum-table thead th").nth(14).wait_for()
    assert page.locator("#results-title").text_content() == "The full rating spectrum"
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


def test_maia_explorer_matches_analysis_layout_and_keeps_board_in_view(page):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(BASE_URL)
    analysis_background = page.locator("body").evaluate(
        "element => getComputedStyle(element).getPropertyValue('--bg').trim()"
    )
    page.locator("#workspace-explorer").click()
    page.locator("#tab-explore").click()
    assert page.locator(".workspace").evaluate(
        "element => element.classList.contains('analysis-layout') && "
        "element.classList.contains('explorer-layout')"
    )
    assert page.locator("body").evaluate(
        "element => getComputedStyle(element).getPropertyValue('--bg').trim()"
    ) == analysis_background
    board = page.locator("#board").bounding_box()
    assert board is not None
    assert board["y"] + board["height"] <= 900
    assert page.locator("#maia-view").is_visible()
    assert page.locator("#dual-view").is_hidden()


def test_analysis_and_explorer_mode_switches_keep_the_right_panel_visible(page):
    page.goto(BASE_URL)
    assert page.locator(".analysis-views").is_visible()
    for view in ("stockfish", "dual"):
        page.locator(f"#view-{view}").click()
        assert page.locator("#dual-view").is_visible()
        assert page.locator("#maia-view").is_hidden()

    page.locator("#workspace-explorer").click()
    assert page.locator(".analysis-views").is_hidden()
    assert page.locator("#maia-tabs").is_visible()
    for mode in ("triple", "explore", "compare", "spectrum"):
        page.locator(f"#tab-{mode}").click()
        assert page.locator("#maia-view").is_visible()
        assert page.locator("#dual-view").is_hidden()

    # A stale or scripted click on an Analysis-only tab must not blank Explorer.
    page.locator("#view-stockfish").evaluate("element => element.click()")
    assert page.locator("#maia-view").is_visible()

    page.locator("#workspace-analysis").click()
    assert page.locator(".analysis-views").is_visible()
    assert page.locator("#dual-view").is_visible()
    assert page.locator("#maia-view").is_hidden()
    page.locator("#view-stockfish").click()
    assert page.locator("#dual-view").is_visible()
    assert page.locator(".rating-chart-panel").is_visible()
    page.set_viewport_size({"width": 820, "height": 900})
    page.locator("#workspace-explorer").click()
    assert page.locator(".analysis-views").is_hidden()
    page.locator("#view-stockfish").evaluate("element => element.click()")
    assert page.locator("#maia-view").is_visible()
    board_y = page.locator("#board").bounding_box()["y"]
    analysis_y = page.locator(".analysis-panel").bounding_box()["y"]
    game_y = page.locator(".game-panel").bounding_box()["y"]
    assert board_y < analysis_y < game_y


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
    page.locator("#settings-tab-options").click()
    page.locator("#elo").fill("1000")
    page.locator("#elo").fill("2400")
    page.get_by_text("Test rating 2400", exact=True).wait_for()
    assert not page.get_by_text("Test rating 1000", exact=True).count()
    assert calls[-1] == 2400


def test_switching_games_aborts_unneeded_maia_requests(page):
    page.add_init_script(
        """(() => {
          window.__maiaRequests = 0;
          window.__maiaAborts = 0;
          const fetch = window.fetch.bind(window);
          window.fetch = (input, init = {}) => {
            if (String(input).includes('/api/v1/analyze')) {
              window.__maiaRequests += 1;
              return new Promise((resolve, reject) => {
                const abort = () => {
                  window.__maiaAborts += 1;
                  reject(new DOMException('Aborted for test', 'AbortError'));
                };
                if (init.signal?.aborted) abort();
                else init.signal?.addEventListener('abort', abort, { once: true });
              });
            }
            return fetch(input, init);
          };
        })();"""
    )
    page.goto(BASE_URL)
    for _ in range(40):
        if page.evaluate("window.__maiaRequests > 0"):
            break
        page.wait_for_timeout(50)
    assert page.evaluate("window.__maiaRequests > 0")
    page.locator("#pgn-file").set_input_files("samples/opera-game.pgn")
    for _ in range(40):
        if page.evaluate("window.__maiaAborts > 0"):
            break
        page.wait_for_timeout(50)
    assert page.evaluate("window.__maiaAborts > 0")


def test_latest_pgn_import_wins_when_responses_arrive_out_of_order(page):
    page.add_init_script(
        """(() => {
          window.__pgnResolvers = [];
          window.__pgnCalls = 0;
          const fetch = window.fetch.bind(window);
          window.fetch = async (input, init = {}) => {
            const response = await fetch(input, init);
            if (String(input).includes('/api/v1/pgn')) {
              window.__pgnCalls += 1;
              await new Promise(resolve => window.__pgnResolvers.push(resolve));
            }
            return response;
          };
        })();"""
    )
    page.goto(BASE_URL)
    older = '[Event "Older Import"]\n[White "Player A"]\n[Black "Player B"]\n\n1. e4 e5 *\n'
    newer = '[Event "Newer Import"]\n[White "Player C"]\n[Black "Player D"]\n\n1. d4 d5 *\n'
    page.locator("#pgn-file").set_input_files(
        {"name": "older.pgn", "mimeType": "application/x-chess-pgn", "buffer": older.encode()}
    )
    for _ in range(40):
        if page.evaluate("window.__pgnCalls === 1"):
            break
        page.wait_for_timeout(50)
    assert page.evaluate("window.__pgnCalls === 1")
    page.locator("#pgn-file").set_input_files(
        {"name": "newer.pgn", "mimeType": "application/x-chess-pgn", "buffer": newer.encode()}
    )
    for _ in range(40):
        if page.evaluate("window.__pgnCalls === 2"):
            break
        page.wait_for_timeout(50)
    assert page.evaluate("window.__pgnCalls === 2")
    page.evaluate("window.__pgnResolvers[1]()")
    for _ in range(40):
        if page.locator("#game-meta h3").text_content() == "Player C — Player D":
            break
        page.wait_for_timeout(50)
    assert page.locator("#game-meta h3").text_content() == "Player C — Player D"
    page.evaluate("window.__pgnResolvers[0]()")
    page.wait_for_timeout(100)
    assert page.locator("#game-meta h3").text_content() == "Player C — Player D"


def test_custom_fen_selection_survives_a_late_pgn_import(page):
    page.add_init_script(
        """(() => {
          window.__pgnResolvers = [];
          const fetch = window.fetch.bind(window);
          window.fetch = async (input, init = {}) => {
            const response = await fetch(input, init);
            if (String(input).includes('/api/v1/pgn'))
              await new Promise(resolve => window.__pgnResolvers.push(resolve));
            return response;
          };
        })();"""
    )
    page.goto(BASE_URL)
    pgn = '[Event "Late PGN"]\n[White "Player A"]\n[Black "Player B"]\n\n1. e4 e5 *\n'
    page.locator("#pgn-file").set_input_files(
        {"name": "late.pgn", "mimeType": "application/x-chess-pgn", "buffer": pgn.encode()}
    )
    for _ in range(40):
        if page.evaluate("window.__pgnResolvers.length === 1"):
            break
        page.wait_for_timeout(50)
    assert page.evaluate("window.__pgnResolvers.length === 1")
    page.locator("#fen-open").click()
    page.locator("#fen-input").fill("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1")
    page.get_by_role("button", name="Explore position").click()
    page.locator("#fen-dialog").wait_for(state="hidden")
    page.evaluate("window.__pgnResolvers[0]()")
    page.wait_for_timeout(100)
    assert page.locator("#game-meta h3").text_content() == "Custom position"


def test_browser_switches_between_dual_and_pure_stockfish_views(page):
    from playwright.sync_api import expect

    errors = []
    requested = []
    engine_requested = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def fixture(route):
        data = json.loads(route.request.post_data)
        requested.append(data)
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
                "host": "Windows AMD64",
            }
        ),
    )

    def engine_fixture(route):
        engine_requested.append(json.loads(route.request.post_data))
        route.fulfill(
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
        )

    page.route("**/api/v1/engine/analyze", engine_fixture)
    page.goto(BASE_URL)
    page.locator("#dual-human-moves .move-prediction").nth(4).wait_for()
    assert not page.locator("#auto-stockfish").is_checked()
    assert engine_requested == []
    assert page.locator("#stockfish-lines-count").input_value() == "5"
    assert page.locator("#stockfish-depth").input_value() == "20"
    assert page.locator("#stockfish-lines-count option").count() == 5
    assert page.locator("#stockfish-depth option").all_text_contents() == [
        "10", "15", "20", "25", "30", "35", "40"
    ]
    assert page.locator("#stockfish-hash").input_value() == "8"
    assert page.locator("#stockfish-threads").input_value() == "14"
    assert page.locator("#dual-results .dual-column").count() == 2
    page.locator("#pgn-file").set_input_files("samples/opera-game.pgn")
    page.locator("#maia-warmup-status").filter(
        has_text="Maia ready · 34 positions"
    ).wait_for()
    assert engine_requested == []
    page.locator("#whole-game-analyze").wait_for(state="visible")
    expect(page.locator("#whole-game-analyze")).to_be_enabled()
    page.get_by_role("button", name="Analyze Whole Game").click()
    page.locator("#whole-game-status").filter(
        has_text="Complete · 34 positions analyzed"
    ).wait_for()
    page.locator("#whole-game-status").filter(has_text="Maia cached 34").wait_for()
    page.locator("#stockfish-results .stockfish-line").nth(1).wait_for()
    whole_game_maia = [
        request for request in requested
        if len(request.get("matchups", [])) == 1 and "initial_fen" in request
    ]
    assert {len(request["moves"]) for request in whole_game_maia} == set(range(34))
    assert all(item["multipv"] == 5 for item in engine_requested)
    assert all(item["depth"] == 20 for item in engine_requested)
    assert all(item["hash_mb"] == 8192 for item in engine_requested)
    assert all(item["threads"] == 14 for item in engine_requested)
    assert page.locator("#maia-gauge-marker").text_content().endswith("%")
    assert page.locator("#sf-gauge-marker").text_content() == "+0.35"
    page.locator(".rating-chart-line").nth(4).wait_for(state="attached")
    assert page.get_by_text("Maia probability", exact=True).is_visible()
    assert page.get_by_text("Lichess blitz rating", exact=True).is_visible()
    assert page.locator(".rating-chart-end-label").count() == 5
    assert page.locator('.rating-chart-line[data-uci="e2e4"]').count() == 1
    assert "Stockfish prefers" in page.locator("#comparison-summary").text_content()
    assert "moves-disagree" in page.locator("#comparison-summary").get_attribute("class")
    assert "TOP MOVES DIFFER" in page.locator(
        "#comparison-summary .comparison-label"
    ).text_content()
    page.locator(".rating-chart-dot").first.focus()
    assert "400 vs. 400 Elo" in page.locator(".rating-chart-tooltip").text_content()
    assert "5.00%" in page.locator(".rating-chart-tooltip").text_content()
    page.locator(".chart-legend-button").first.click()
    assert page.locator(".rating-chart-line").count() == 4
    page.locator(".chart-legend-button").first.click()
    assert page.locator(".rating-chart-line").count() == 5
    page.locator("#dual-human-moves .move-prediction").first.focus()
    assert page.locator("#move-inspector").is_visible()
    assert "Maia rank" in page.locator("#move-inspector").text_content()
    page.locator(".stockfish-line").nth(1).focus()
    assert "0.14 pawns" in page.locator("#move-inspector").text_content()
    page.locator("#workspace-analysis").focus()
    assert page.locator("#move-inspector").is_hidden()
    page.locator("#comparison-more").click()
    assert page.locator("#dual-human-moves .move-prediction").count() == 20
    page.locator("#comparison-more").click()
    assert page.locator("#dual-human-moves .move-prediction").count() == 5
    page.locator("#analysis-collapse").click()
    assert page.locator("#analysis-card").is_hidden()
    assert page.locator(".rating-chart-panel").is_visible()
    page.locator("#analysis-collapse").click()
    assert page.locator("#analysis-card").is_visible()
    page.locator("#analysis-rating").select_option("2400")
    page.locator("#dual-human-moves .move-prediction").nth(4).wait_for()
    assert page.locator("#elo").input_value() == "2400"
    assert page.locator("#human-model-rating").text_content() == "Maia 2400: Human Moves"
    assert page.locator(".stockfish-line .engine-pv").first.is_hidden()
    page.locator("#settings-tab-options").click()
    page.locator(".dual-matchup-menu > summary").click()
    page.locator("#dual-equal").uncheck()
    page.locator("#dual-opponent-elo").fill("1200")
    page.locator("#dual-opponent-elo").press("Tab")
    page.locator("#rating-chart-context").filter(has_text="opponent 1200 Elo").wait_for()
    assert requested[-1]["matchups"] == [
        {"player_elo": rating, "opponent_elo": 1200} for rating in range(400, 3001, 200)
    ]
    page.locator("#show-variations").check()
    assert page.locator(".stockfish-line .engine-pv").first.is_visible()
    page.locator("#view-stockfish").click()
    assert "pure-stockfish" in page.locator("#dual-results").get_attribute("class")
    assert page.locator(".human-column").is_hidden()
    assert page.locator(".rating-chart-panel").is_visible()
    assert page.locator(".stockfish-line .engine-pv").first.is_visible()
    page.locator("#settings-tab-engine").click()
    page.locator("#auto-stockfish").check()
    page.locator("#next").click()
    page.locator("#stockfish-results .stockfish-line").first.wait_for()
    assert any(
        len(request.get("moves", [])) == 1
        # SF Only now populates the full rating graph, including this pairing,
        # instead of sending a redundant single-rating Maia request.
        and {"player_elo": 2400, "opponent_elo": 1200} in request.get("matchups", [])
        for request in requested
    )
    page.locator("#view-dual").click()
    assert "pure-stockfish" not in page.locator("#dual-results").get_attribute("class")
    assert page.locator(".human-column").is_visible()
    page.locator("#dual-human-moves .comparison-move").first.wait_for()
    page.locator("#settings-tab-engine").click()
    assert page.locator("#settings-panel-engine").is_visible()
    assert page.locator("#settings-panel-options").is_hidden()
    page.locator("#settings-tab-export").click()
    assert page.locator("#settings-panel-export").is_visible()
    page.locator("#settings-tab-options").click()
    page.locator("#fen-open").click()
    page.locator("#fen-input").fill(chess.STARTING_FEN)
    page.get_by_role("button", name="Explore position").click()
    page.locator("#fen-dialog").wait_for(state="hidden")
    assert page.locator("#whole-game-analyze").is_disabled()
    page.locator("#settings-tab-engine").click()
    page.locator("#stockfish-panel > summary").click()
    assert page.locator("#stockfish-channel").is_visible()
    assert (
        page.locator("#stockfish-host").text_content()
        == "Engine runs on this computer: Windows AMD64"
    )
    page.locator("#stockfish-channel").select_option("development")
    assert "tests.stockfishchess.org" in page.locator("#stockfish-download").get_attribute("href")
    assert not errors


def test_whole_game_reuses_the_current_identical_stockfish_search(page):
    from playwright.sync_api import expect

    page.add_init_script(
        """window.__stockfishActive = 0;
        window.__stockfishMaxActive = 0;
        window.__releaseFirstStockfish = null;
        const firstSearchGate = new Promise(resolve => {
          window.__releaseFirstStockfish = resolve;
        });
        const originalFetch = window.fetch.bind(window);
        let firstSearch = true;
        window.fetch = function (input, init) {
          if (!String(input).includes('/api/v1/engine/analyze'))
            return originalFetch(input, init);
          window.__stockfishActive += 1;
          window.__stockfishMaxActive = Math.max(
            window.__stockfishMaxActive, window.__stockfishActive
          );
          const gate = firstSearch ? firstSearchGate : Promise.resolve();
          firstSearch = false;
          return gate.then(() => originalFetch(input, init)).finally(() => {
            window.__stockfishActive -= 1;
          });
        };"""
    )
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={"available": True, "name": "Stockfish 19 queue fixture", "channel": "official19"}
        ),
    )

    def analyze(route):
        data = json.loads(route.request.post_data)
        board = chess.Board(data["fen"])
        moves = list(board.legal_moves)
        route.fulfill(
            json={
                "predictions": [
                    {
                        "player_elo": pair["player_elo"],
                        "opponent_elo": pair["opponent_elo"],
                        "moves": [
                            {
                                "uci": move.uci(),
                                "san": board.san(move),
                                "probability": 1 / len(moves),
                                "rank": rank,
                            }
                            for rank, move in enumerate(moves, 1)
                        ],
                    }
                    for pair in data.get("matchups", [{"player_elo": 1800, "opponent_elo": 1800}])
                ]
            }
        )

    page.route("**/api/v1/analyze", analyze)
    page.route(
        "**/api/v1/engine/analyze",
        lambda route: route.fulfill(
            json={
                "engine": "Stockfish 19 queue fixture",
                "channel": "official19",
                "depth": 20,
                "lines": [],
            }
        ),
    )
    page.goto(BASE_URL)
    page.locator("#settings-tab-engine").click()
    page.locator("#auto-stockfish").check()
    page.locator("#sample").click()
    expect(page.locator("#whole-game-analyze")).to_be_enabled()
    page.locator("#next").click()
    for _ in range(100):
        if page.evaluate("window.__stockfishActive") == 1:
            break
        page.wait_for_timeout(50)
    assert page.evaluate("window.__stockfishActive") == 1
    page.locator("#whole-game-analyze").click()
    expect(page.locator("#whole-game-status")).to_contain_text("Complete · 34 positions analyzed")
    page.evaluate("window.__releaseFirstStockfish()")
    page.locator("#whole-game-status").filter(
        has_text="Complete · 34 positions analyzed"
    ).wait_for()
    assert page.evaluate("window.__stockfishMaxActive") <= 2


def test_browser_engine_settings_persist_and_restore_defaults(page):
    page.goto(BASE_URL)
    page.locator("#settings-tab-engine").click()
    page.locator("#stockfish-lines-count").select_option("3")
    page.locator("#stockfish-depth").select_option("30")
    page.locator("#stockfish-hash").fill("6")
    page.locator("#stockfish-hash").press("Tab")
    page.locator("#stockfish-threads").fill("10")
    page.locator("#stockfish-threads").press("Tab")
    page.locator("#auto-stockfish").check()
    page.reload()
    page.locator("#settings-tab-engine").click()
    assert page.locator("#stockfish-lines-count").input_value() == "3"
    assert page.locator("#stockfish-depth").input_value() == "30"
    assert page.locator("#stockfish-hash").input_value() == "6"
    assert page.locator("#stockfish-threads").input_value() == "10"
    assert page.locator("#auto-stockfish").is_checked()
    page.locator("#engine-reset-defaults").click()
    assert page.locator("#stockfish-lines-count").input_value() == "5"
    assert page.locator("#stockfish-depth").input_value() == "20"
    assert page.locator("#stockfish-hash").input_value() == "8"
    assert page.locator("#stockfish-threads").input_value() == "14"
    assert not page.locator("#auto-stockfish").is_checked()


def test_browser_shows_stockfish_install_error_in_engine_setup(page):
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={
                "available": False,
                "name": None,
                "channel": "official19",
                "host": "Windows AMD64",
            }
        ),
    )
    page.route(
        "**/api/v1/engine/install",
        lambda route: route.fulfill(
            status=422,
            json={
                "error": {
                    "code": "stockfish_platform",
                    "message": "This is a Linux engine. Choose the build for Windows.",
                }
            },
        ),
    )
    page.goto(BASE_URL)
    page.locator("#settings-tab-engine").click()
    page.locator("#stockfish-panel > summary").click()
    page.locator("#stockfish-file").evaluate(
        "input => { const transfer = new DataTransfer(); "
        "transfer.items.add(new File(['engine'], 'stockfish.exe')); "
        "input.files = transfer.files; "
        "input.dispatchEvent(new Event('change', { bubbles: true })); }"
    )
    page.locator("#stockfish-error").filter(has_text="stockfish_platform:").wait_for()
    assert page.locator("#stockfish-error").is_visible()
    assert "Choose the build for Windows" in page.locator("#stockfish-error").text_content()
    assert page.locator("#stockfish-panel").evaluate("el => el.open")


def test_browser_failed_stockfish_replacement_keeps_existing_engine(page):
    from playwright.sync_api import expect

    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={
                "available": True,
                "name": "Stockfish 19 existing engine",
                "channel": "official19",
            }
        ),
    )
    page.route(
        "**/api/v1/engine/analyze",
        lambda route: route.fulfill(
            json={"engine": "Stockfish 19 existing engine", "depth": 16, "lines": []}
        ),
    )
    page.route(
        "**/api/v1/engine/install",
        lambda route: route.fulfill(
            status=422,
            json={
                "error": {
                    "code": "stockfish_platform",
                    "message": "The replacement engine is for another platform.",
                }
            },
        ),
    )
    page.goto(BASE_URL)
    page.locator("#settings-tab-engine").click()
    expect(page.locator("#stockfish-analyze")).to_be_enabled()
    page.locator("#stockfish-panel > summary").click()
    page.locator("#stockfish-file").evaluate(
        "input => { const transfer = new DataTransfer(); "
        "transfer.items.add(new File(['engine'], 'stockfish.exe')); "
        "input.files = transfer.files; "
        "input.dispatchEvent(new Event('change', { bubbles: true })); }"
    )
    page.locator("#stockfish-error").filter(has_text="stockfish_platform:").wait_for()
    expect(page.locator("#stockfish-analyze")).to_be_enabled()
    assert "Current engine remains ready" in page.locator("#stockfish-status").text_content()


def test_browser_identifies_stale_stockfish_backend(page):
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(status=404, json={"detail": "Not Found"}),
    )
    page.goto(BASE_URL)
    page.locator("#stockfish-error").filter(has_text="older ELO Vision backend").wait_for()
    assert "free port" in page.locator("#stockfish-error").text_content()
    assert page.locator("#stockfish-status").text_content() == "Older ELO Vision server detected"


def test_stockfish_results_return_from_cache_when_navigating_back(page):
    from playwright.sync_api import expect

    page.add_init_script(
        """window.__elovisionDebouncedNavigation = [];
        const originalSetTimeout = window.setTimeout;
        window.setTimeout = function (callback, delay, ...args) {
          if (delay === 100) window.__elovisionDebouncedNavigation.push(delay);
          return originalSetTimeout.call(this, callback, delay, ...args);
        };"""
    )
    engine_requests = []
    maia_requests = []

    def analyze_maia(route):
        data = json.loads(route.request.post_data)
        maia_requests.append(data)
        board = chess.Board(data["fen"])
        matchups = data.get("matchups") or [
            {"player_elo": rating, "opponent_elo": rating} for rating in data.get("ratings", [1800])
        ]
        route.fulfill(
            json={
                "predictions": [
                    {
                        "player_elo": pair["player_elo"],
                        "opponent_elo": pair["opponent_elo"],
                        "moves": [
                            {
                                "uci": move.uci(),
                                "san": board.san(move),
                                "probability": 1 / board.legal_moves.count(),
                                "rank": rank,
                            }
                            for rank, move in enumerate(board.legal_moves, 1)
                        ],
                        "cached": False,
                        "elapsed_ms": 1,
                    }
                    for pair in matchups
                ]
            }
        )

    def analyze_stockfish(route):
        data = json.loads(route.request.post_data)
        engine_requests.append(data)
        board = chess.Board(data["fen"])
        move = next(iter(board.legal_moves))
        route.fulfill(
            json={
                "engine": "Stockfish 19 cache fixture",
                "channel": "official19",
                "depth": data["depth"],
                "lines": [
                    {
                        "rank": 1,
                        "uci": move.uci(),
                        "san": board.san(move),
                        "score_cp": 11 if board.turn else 22,
                        "mate": None,
                        "score": "+0.11" if board.turn else "+0.22",
                        "pv": [board.san(move)],
                        "depth": data["depth"],
                    }
                ],
            }
        )

    page.route("**/api/v1/analyze", analyze_maia)
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={"available": True, "name": "Stockfish 19 cache fixture", "channel": "official19"}
        ),
    )
    page.route("**/api/v1/engine/analyze", analyze_stockfish)
    page.goto(BASE_URL)
    page.locator("#sample").click()
    expect(page.locator("#next")).to_be_enabled()
    page.locator("#maia-warmup-status").filter(
        has_text="Maia ready · 34 positions"
    ).wait_for()
    page.locator("#dual-human-moves .comparison-move").first.wait_for()
    page.locator("#settings-tab-engine").click()
    page.locator("#stockfish-analyze").click()
    page.locator("#stockfish-results .stockfish-line").filter(has_text="+0.11").wait_for()
    def maia_position_requests():
        return [
            request for request in maia_requests
            if "initial_fen" in request and len(request.get("matchups", [])) == 1
        ]

    maia_requests_after_warmup = len(maia_position_requests())
    page.locator("#next").click()
    assert page.evaluate("window.__elovisionDebouncedNavigation") == []
    page.locator("#dual-human-moves .comparison-move").first.wait_for()
    expect(page.locator("#probability-total")).to_contain_text("Cached")
    assert len(engine_requests) == 1
    page.locator("#stockfish-analyze").click()
    page.locator("#stockfish-results .stockfish-line").filter(has_text="+0.22").wait_for()
    requests_after_searching_both_positions = len(engine_requests)
    assert len(maia_position_requests()) == maia_requests_after_warmup
    page.locator("#prev").click()
    assert page.evaluate("window.__elovisionDebouncedNavigation") == []
    expect(page.locator("#dual-human-moves .comparison-move").first).to_be_visible()
    expect(page.locator("#probability-total")).to_contain_text("Cached")
    assert "Waiting for Maia analysis" not in page.locator("#dual-human-moves").text_content()
    page.locator("#stockfish-results .stockfish-line").filter(has_text="+0.11").wait_for()
    page.wait_for_timeout(200)
    assert len(engine_requests) == requests_after_searching_both_positions
    assert len(maia_position_requests()) == maia_requests_after_warmup
    assert page.locator("#stockfish-results .stockfish-line").count() == 1
    page.locator("#stockfish-analyze").click()
    page.wait_for_timeout(100)
    assert len(engine_requests) == requests_after_searching_both_positions
    page.locator("#stockfish-lines-count").select_option("3")
    page.wait_for_timeout(200)
    assert len(engine_requests) == requests_after_searching_both_positions + 1


def test_selecting_another_pgn_stops_old_whole_game_analysis(page):
    page.add_init_script(
        """window.__holdEngine = false;
        window.__heldEngineCount = 0;
        let releaseEngine;
        const engineGate = new Promise(resolve => { releaseEngine = resolve; });
        window.__releaseHeldEngine = () => releaseEngine();
        const originalFetch = window.fetch.bind(window);
        window.fetch = function (input, init = {}) {
          if (window.__holdEngine && String(input).includes('/api/v1/engine/analyze')) {
            window.__heldEngineCount += 1;
            return engineGate.then(() => originalFetch(input, init));
          }
          return originalFetch(input, init);
        };"""
    )
    page.route("**/api/v1/health", lambda route: route.fulfill(json={"loaded": True}))
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={"available": True, "name": "Stockfish 19 PGN fixture", "channel": "official19"}
        ),
    )

    def analyze_maia(route):
        data = json.loads(route.request.post_data)
        board = chess.Board(data["fen"])
        pairs = data.get("matchups") or [
            {"player_elo": rating, "opponent_elo": rating}
            for rating in data.get("ratings", [1800])
        ]
        route.fulfill(
            json={
                "predictions": [
                    {
                        **pair,
                        "moves": [
                            {
                                "uci": move.uci(),
                                "san": board.san(move),
                                "probability": 0.05,
                                "rank": rank,
                            }
                            for rank, move in enumerate(board.legal_moves, 1)
                        ],
                    }
                    for pair in pairs
                ]
            }
        )

    engine_requests = []

    def analyze_stockfish(route):
        data = json.loads(route.request.post_data)
        engine_requests.append(data)
        board = chess.Board(data["fen"])
        move = next(iter(board.legal_moves))
        route.fulfill(
            json={
                "engine": "Stockfish 19 PGN fixture",
                "channel": "official19",
                "depth": data["depth"],
                "lines": [
                    {
                        "rank": 1,
                        "uci": move.uci(),
                        "san": board.san(move),
                        "pv": [board.san(move)],
                        "score": "+0.10",
                        "depth": data["depth"],
                    }
                ],
            }
        )

    page.route("**/api/v1/analyze", analyze_maia)
    page.route("**/api/v1/engine/analyze", analyze_stockfish)
    page.goto(BASE_URL)
    pgn = (
        '[Event "First"]\n[White "A"]\n[Black "B"]\n\n1. e4 e5 *\n\n'
        '[Event "Second"]\n[White "C"]\n[Black "D"]\n\n1. d4 d5 *\n'
    )
    page.locator("#pgn-file").set_input_files(
        {"name": "two-games.pgn", "mimeType": "text/plain", "buffer": pgn.encode()}
    )
    page.locator("#game-select option").nth(1).wait_for(state="attached")
    page.wait_for_timeout(200)
    page.evaluate("window.__holdEngine = true")
    page.locator("#whole-game-analyze").click()
    page.wait_for_function("window.__heldEngineCount > 0")
    page.locator("#game-select").select_option("1")
    page.evaluate("window.__releaseHeldEngine()")
    page.wait_for_function("!document.querySelector('#whole-game-analyze').disabled")
    page.wait_for_timeout(200)
    first_game_after_start = chess.Board()
    first_game_after_start.push_san("e4")
    assert all(request["fen"] != first_game_after_start.fen() for request in engine_requests)
    assert page.locator("#game-result").text_content().endswith("2 plies")


def test_maia_cache_is_reused_after_switching_between_pgn_games(page):
    maia_requests = []
    page.route("**/api/v1/health", lambda route: route.fulfill(json={"loaded": True}))
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(json={"available": False, "message": "Not installed"}),
    )

    def analyze_maia(route):
        data = json.loads(route.request.post_data)
        maia_requests.append(data)
        board = chess.Board(data["fen"])
        pairs = data.get("matchups") or [
            {"player_elo": rating, "opponent_elo": rating}
            for rating in data.get("ratings", [1800])
        ]
        route.fulfill(
            json={
                "predictions": [
                    {
                        **pair,
                        "moves": [
                            {
                                "uci": move.uci(),
                                "san": board.san(move),
                                "probability": 0.05,
                                "rank": rank,
                            }
                            for rank, move in enumerate(board.legal_moves, 1)
                        ],
                    }
                    for pair in pairs
                ]
            }
        )

    page.route("**/api/v1/analyze", analyze_maia)
    page.goto(BASE_URL)
    pgn = (
        '[Event "First"]\n[White "A"]\n[Black "B"]\n\n1. e4 e5 *\n\n'
        '[Event "Second"]\n[White "C"]\n[Black "D"]\n\n1. d4 d5 *\n'
    )
    page.locator("#pgn-file").set_input_files(
        {"name": "two-games.pgn", "mimeType": "text/plain", "buffer": pgn.encode()}
    )
    page.locator("#maia-warmup-status").filter(has_text="Maia ready · 3 positions").wait_for()

    def game_position_requests():
        return [request for request in maia_requests if "initial_fen" in request]

    first_game_count = len(game_position_requests())
    page.locator("#game-select").select_option("1")
    page.locator("#maia-warmup-status").filter(has_text="Maia ready · 3 positions").wait_for()
    second_game_count = len(game_position_requests())
    assert second_game_count > first_game_count
    page.locator("#game-select").select_option("0")
    page.locator("#maia-warmup-status").filter(has_text="Maia ready · 3 positions").wait_for()
    assert len(game_position_requests()) == second_game_count


def test_stockfish_cache_survives_switching_between_pgn_games(page):
    engine_requests = []
    page.route("**/api/v1/health", lambda route: route.fulfill(json={"loaded": True}))
    page.route(
        "**/api/v1/engine/status",
        lambda route: route.fulfill(
            json={"available": True, "name": "Stockfish 19 cache fixture", "channel": "official19"}
        ),
    )
    page.route(
        "**/api/v1/analyze",
        lambda route: route.fulfill(json={"predictions": []}),
    )

    def analyze_stockfish(route):
        data = json.loads(route.request.post_data)
        engine_requests.append(data)
        board = chess.Board(data["fen"])
        move = next(iter(board.legal_moves))
        route.fulfill(
            json={
                "engine": "Stockfish 19 cache fixture",
                "channel": "official19",
                "depth": data["depth"],
                "lines": [
                    {
                        "rank": 1,
                        "uci": move.uci(),
                        "san": board.san(move),
                        "pv": [board.san(move)],
                        "score": "+0.10",
                        "depth": data["depth"],
                    }
                ],
            }
        )

    page.route("**/api/v1/engine/analyze", analyze_stockfish)
    page.goto(BASE_URL)
    page.locator("#settings-tab-engine").click()
    pgn = (
        '[Event "First"]\n[White "A"]\n[Black "B"]\n\n1. e4 e5 *\n\n'
        '[Event "Second"]\n[White "C"]\n[Black "D"]\n\n1. d4 d5 *\n'
    )
    page.locator("#pgn-file").set_input_files(
        {"name": "two-games.pgn", "mimeType": "text/plain", "buffer": pgn.encode()}
    )
    page.locator("#game-select option").nth(1).wait_for(state="attached")
    page.wait_for_timeout(300)
    assert engine_requests == []
    page.locator("#auto-stockfish").check()
    page.get_by_role("button", name="e4", exact=True).click()
    page.locator("#stockfish-results .stockfish-line").first.wait_for()
    first_count = len(engine_requests)
    page.locator("#game-select").select_option("1")
    page.get_by_role("button", name="d4", exact=True).click()
    page.locator("#stockfish-results .stockfish-line").first.wait_for()
    page.wait_for_timeout(200)
    second_count = len(engine_requests)
    assert second_count == first_count + 1
    page.locator("#game-select").select_option("0")
    page.get_by_role("button", name="e4", exact=True).click()
    page.locator("#stockfish-results .stockfish-line").first.wait_for()
    page.wait_for_timeout(200)
    assert len(engine_requests) == second_count


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
    page.locator("#settings-tab-engine").click()
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


def test_auto_stockfish_is_opt_in_and_maia_still_warms_the_selected_game(page):
    maia_requests = []
    engine_requests = []

    def analyze_maia(route):
        data = json.loads(route.request.post_data)
        maia_requests.append(data)
        board = chess.Board(data["fen"])
        legal = list(board.legal_moves)
        moves = [
            {
                "uci": move.uci(),
                "san": board.san(move),
                "probability": 1 / len(legal),
                "rank": rank,
            }
            for rank, move in enumerate(legal, 1)
        ]
        route.fulfill(
            json={
                "predictions": [
                    {
                        "player_elo": 1800,
                        "opponent_elo": 1800,
                        "moves": moves,
                        "cached": False,
                    }
                ]
            }
        )

    page.route("**/api/v1/analyze", analyze_maia)
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

    def analyze_engine(route):
        data = json.loads(route.request.post_data)
        engine_requests.append(data)
        board = chess.Board(data["fen"])
        move = next(iter(board.legal_moves))
        route.fulfill(
            json={
                "engine": "Stockfish 19 browser fixture",
                "channel": "official19",
                "depth": data["depth"],
                "lines": [
                    {
                        "rank": 1,
                        "uci": move.uci(),
                        "san": board.san(move),
                        "score": "+0.10",
                        "pv": [board.san(move)],
                        "depth": data["depth"],
                    }
                ],
            }
        )

    page.route("**/api/v1/engine/analyze", analyze_engine)
    page.goto(BASE_URL)
    page.locator("#dual-human-moves .move-prediction").first.wait_for()
    assert not page.locator("#auto-stockfish").is_checked()
    pgn = '[Event "Auto test"]\n[White "A"]\n[Black "B"]\n\n1. e4 e5 *\n'
    page.locator("#pgn-file").set_input_files(
        {"name": "auto-test.pgn", "mimeType": "text/plain", "buffer": pgn.encode()}
    )
    page.locator("#maia-warmup-status").filter(has_text="Maia ready · 3 positions").wait_for()
    assert any("initial_fen" in request for request in maia_requests)
    assert engine_requests == []

    page.get_by_role("button", name="e4", exact=True).click()
    page.wait_for_timeout(100)
    assert engine_requests == []
    assert any(len(request.get("moves", [])) == 1 for request in maia_requests)

    page.locator("#settings-tab-engine").click()
    page.locator("#auto-stockfish").check()
    page.get_by_role("button", name="e5", exact=True).click()
    for _ in range(40):
        if len(engine_requests) >= 1:
            break
        page.wait_for_timeout(50)
    assert len(engine_requests) == 1
    assert len(engine_requests[0]["moves"]) == 2

    page.get_by_role("button", name="e4", exact=True).click()
    for _ in range(40):
        if len(engine_requests) >= 2:
            break
        page.wait_for_timeout(50)
    assert len(engine_requests) == 2
    page.get_by_role("button", name="e5", exact=True).click()
    page.wait_for_timeout(100)
    assert len(engine_requests) == 2


def layout_preferences(page, workspace="analysis"):
    return page.evaluate(
        "name => JSON.parse(localStorage.getItem('elovision-workspace-layout-v1')).pages[name]",
        workspace,
    )


def drag_layout_control(page, control, dx, dy):
    control.scroll_into_view_if_needed()
    bounds = control.bounding_box()
    x, y = bounds["x"] + bounds["width"] / 2, bounds["y"] + bounds["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + dx, y + dy, steps=12)
    page.mouse.up()


def test_layout_drag_resize_persist_and_keep_navigation_on_the_board(page):
    page.set_viewport_size({"width": 1600, "height": 1200})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE_URL)
    page.locator("#pgn-file").set_input_files("samples/opera-game.pgn")
    page.get_by_role("button", name="e4", exact=True).wait_for()
    page.locator("#layout-preset").select_option("focus")
    page.locator("#layout-edit").click()
    unit = page.locator(".workspace").bounding_box()["width"] / 24
    below_board = layout_preferences(page)["panels"]["board"]["h"] + 2
    drag_layout_control(
        page, page.get_by_role("button", name="Move Game notebook", exact=True),
        unit * 7, 16 * below_board,
    )
    moved = layout_preferences(page)["panels"]
    assert moved["game"]["x"] == 7 and moved["game"]["y"] >= 52
    assert moved["game"]["y"] >= moved["board"]["y"] + moved["board"]["h"]
    before = moved["board"]
    drag_layout_control(
        page, page.get_by_role("button", name="Resize Chessboard se", exact=True),
        -unit * 2, -16 * 6,
    )
    after = layout_preferences(page)["panels"]["board"]
    assert after["w"] == before["w"] - 2
    assert after["h"] == before["h"] - 6
    page.locator("#layout-edit").click()
    board = page.locator("#board").bounding_box()
    assert abs(board["height"] - board["width"]) < 1
    assert page.locator(".square").count() == 64
    page.locator("#last").click()
    # Navigating the board must scroll only the notebook's move list, not the page.
    assert page.evaluate("scrollY") < 100
    assert "Checkmate" in page.locator("#turn").text_content()
    saved = layout_preferences(page)
    page.reload()
    expect(page.locator(".dock-frame:visible")).to_have_count(5)
    assert layout_preferences(page) == saved
    assert not errors


def test_layout_presets_reset_and_independent_workspace_preferences(page):
    page.goto(BASE_URL)
    page.locator("#layout-preset").select_option("notebook")
    assert page.locator(".game-panel").bounding_box()["y"] > (
        page.locator(".board-panel").bounding_box()["y"]
    )
    analysis = layout_preferences(page)
    page.locator("#workspace-explorer").click()
    expect(page.locator(".dock-frame")).to_have_count(0)
    page.locator("#layout-preset").select_option("focus")
    expect(page.locator(".dock-frame:visible")).to_have_count(3)
    assert page.locator("#maia-view").is_visible()
    page.locator("#tab-compare").click()
    assert page.locator("#compare-controls").is_visible()
    page.locator("#layout-reset").click()
    expect(page.locator(".dock-frame")).to_have_count(0)
    assert page.locator(".workspace > .game-panel").is_visible()
    page.locator("#workspace-analysis").click()
    expect(page.locator(".dock-frame:visible")).to_have_count(5)
    assert layout_preferences(page) == analysis
    page.locator("#settings-tab-options").click()
    assert page.locator("#elo").is_visible()
    page.locator("#layout-reset").click()
    assert page.locator(".analysis-panel #analysis-options").is_visible()
    assert page.locator("#dual-view .rating-chart-panel").is_visible()
    assert page.locator("#board").is_visible()


def test_layout_keyboard_controls_and_escape_cancel_drag(page):
    page.goto(BASE_URL)
    page.locator("#layout-edit").click()
    handle = page.get_by_role("button", name="Move Game notebook", exact=True)
    before = page.locator("[data-layout-panel=game]").bounding_box()
    handle.press("ArrowDown")
    first = layout_preferences(page)["panels"]["game"]
    assert page.locator("[data-layout-panel=game]").bounding_box()["y"] == before["y"] + 16
    handle.press("Shift+ArrowRight")
    assert layout_preferences(page)["panels"]["game"]["w"] == first["w"] + 1
    saved = layout_preferences(page)
    bounds = handle.bounding_box()
    page.mouse.move(bounds["x"] + 50, bounds["y"] + 12)
    page.mouse.down()
    page.mouse.move(bounds["x"] + 160, bounds["y"] + 140, steps=8)
    page.keyboard.press("Escape")
    page.mouse.up()
    assert layout_preferences(page) == saved
    assert not page.locator(".layout-moving").count()
    assert page.locator("#layout-edit").get_attribute("aria-pressed") == "true"


def test_layout_all_resize_edges_and_corners_keep_panels_separate(page):
    page.set_viewport_size({"width": 1600, "height": 1200})
    page.goto(BASE_URL)
    page.locator("#layout-preset").select_option("focus")
    page.locator("#layout-edit").click()
    unit = page.locator(".workspace").bounding_box()["width"] / 24
    for edge in ("n", "e", "s", "w", "ne", "se", "sw", "nw"):
        page.locator("#layout-preset").select_option("focus")
        before = layout_preferences(page)["panels"]["board"]
        dx = unit if "w" in edge else -unit if "e" in edge else 0
        dy = 32 if "n" in edge else -32 if "s" in edge else 0
        drag_layout_control(
            page, page.get_by_role("button", name=f"Resize Chessboard {edge}", exact=True),
            dx, dy,
        )
        rects = layout_preferences(page)["panels"]
        assert rects["board"]["w"] == before["w"] - int(bool(dx))
        assert rects["board"]["h"] == before["h"] - 2 * int(bool(dy))
        for first, a in rects.items():
            for second, b in rects.items():
                if first == second:
                    continue
                assert not (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
                            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def test_layout_narrow_screen_restores_live_panels_without_losing_preferences(page):
    page.goto(BASE_URL)
    page.locator("#layout-preset").select_option("focus")
    stored = layout_preferences(page)
    for tab in ("analysis", "explorer"):
        page.locator(f"#workspace-{tab}").click()
        page.locator("#layout-preset").select_option("focus")
        for width in (820, 390):
            page.set_viewport_size({"width": width, "height": 900})
            expect(page.locator(".dock-frame")).to_have_count(0)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert page.locator("#layout-edit").is_disabled()
            board = page.locator("#board").bounding_box()
            assert abs(board["height"] - board["width"]) < 1
        page.set_viewport_size({"width": 1440, "height": 1000})
        expect(page.locator(".custom-layout")).to_have_count(1)
    page.locator("#workspace-analysis").click()
    assert layout_preferences(page) == stored
    assert page.locator("#settings-tab-engine").is_visible()


@pytest.mark.parametrize("blocked", [False, True])
def test_layout_recovers_from_corrupt_or_unavailable_browser_storage(page, blocked):
    if blocked:
        page.add_init_script("""Object.defineProperty(window, 'localStorage', {
            get() { throw new DOMException('Storage blocked', 'SecurityError'); }
        });""")
    else:
        page.add_init_script("""localStorage.setItem('elovision-workspace-layout-v1',
            JSON.stringify({version:1,pages:{analysis:{panels:{game:{x:999,y:-4,w:1,h:1}}}}}));""")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(BASE_URL)
    page.locator(".square").nth(63).wait_for()
    assert not page.locator(".dock-frame").count()
    page.locator("#layout-preset").select_option("notebook")
    expect(page.locator(".dock-frame:visible")).to_have_count(5)
    page.locator("#layout-reset").click()
    expect(page.locator(".dock-frame")).to_have_count(0)
    assert not errors


def test_layout_keeps_live_rating_graph_in_sf_only_without_restarting_analysis(page):
    requests = []

    def fixture(route):
        data = json.loads(route.request.post_data)
        requests.append(data)
        board = chess.Board(data["fen"])
        moves = list(board.legal_moves)
        matchups = data.get("matchups") or [
            {"player_elo": rating, "opponent_elo": rating} for rating in data["ratings"]
        ]
        route.fulfill(json={"predictions": [
            {**pair, "moves": [
                {"uci": move.uci(), "san": board.san(move), "rank": i + 1,
                 "probability": 1 / len(moves)} for i, move in enumerate(moves)
            ], "probability_sum": 1, "model": {"id": "layout-browser-fixture"}}
            for pair in matchups
        ]})

    page.route("**/api/v1/analyze", fixture)
    page.goto(BASE_URL)
    page.locator("#rating-comparison-chart svg").wait_for()
    page.locator("#view-stockfish").click()
    svg = page.locator("#rating-comparison-chart svg")
    svg.wait_for()
    svg.evaluate("element => element.dataset.layoutProbe = 'original'")
    count = len(requests)
    page.locator("#layout-preset").select_option("focus")
    page.locator("#layout-edit").click()
    handle = page.get_by_role("button", name="Move Moves by Rating", exact=True)
    handle.press("Shift+ArrowDown")
    handle.press("ArrowDown")
    page.locator("#layout-edit").click()
    assert svg.get_attribute("data-layout-probe") == "original"
    legend = page.locator(".chart-legend-button").first
    legend.click()
    assert page.locator(".chart-legend-button").first.get_attribute("aria-pressed") == "false"
    assert len(requests) == count
    assert page.locator("#dual-results").get_attribute("class").endswith("pure-stockfish")
    assert svg.is_visible()


def test_board_focus_uses_desktop_space_and_keeps_statistics_optional(page):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(BASE_URL)
    page.locator("#layout-preset").select_option("focus")
    expect(page.locator("#board-extras")).not_to_have_attribute("open", "")
    assert page.locator("#board-insight").is_hidden()
    board = page.locator("#board").bounding_box()
    assert board["width"] >= 700
    assert abs(board["width"] - board["height"]) < 1
    assert board["y"] + board["height"] <= 1080
    assert page.locator(".topbar").bounding_box()["height"] == 50
    workspace = page.locator(".workspace").bounding_box()
    assert workspace["x"] <= 20 and workspace["width"] >= 1870
    page.locator("#board-extras > summary").click()
    assert page.locator("#board-insight").is_visible()
    page.locator("#board-extras > summary").click()
    page.locator("#layout-edit").click()
    page.get_by_role("button", name="Move Game notebook", exact=True).press("ArrowDown")
    assert layout_preferences(page)["boardFocus"] is True
    page.locator("#layout-edit").click()
    page.reload()
    expect(page.locator("body")).to_have_class("analysis-theme board-focus-layout")
    assert page.locator("#board-insight").is_hidden()
    for width, height in ((1366, 768), (1600, 900)):
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_function("""() => {
            const r = document.getElementById('board').getBoundingClientRect();
            return r.bottom <= innerHeight;
        }""")
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.locator("#layout-reset").click()
    assert page.locator("#board-insight").is_visible()
