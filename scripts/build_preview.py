"""Build a network-free interface preview from the production UI and real chess states.

No inference implementation or probability data is embedded. The local Python app
remains necessary for arbitrary PGN/FEN input and Maia analysis.
"""

import argparse
import base64
import json
from pathlib import Path

from elovision.chess_state import parse_pgn

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "elovision" / "static"


def data_uri(path: Path) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def build_preview(output: Path) -> Path:
    samples = json.loads((STATIC / "sample-games.json").read_text(encoding="utf-8"))
    payload = {
        "samples": [{"metadata": sample, "parsed": parse_pgn(sample["pgn"])} for sample in samples],
        "pieces": {path.stem: data_uri(path) for path in (STATIC / "pieces").glob("*.svg")},
    }
    payload_json = json.dumps(payload, ensure_ascii=True).replace("<", "\\u003c")
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    layout_script = (STATIC / "layout.js").read_text(encoding="utf-8")
    # Inline code waits for the DOM, replacing the normal module's deferred execution.
    inline_script = (
        "<script>\n"
        f"globalThis.ELOVISION_PREVIEW = {payload_json};\n"
        "document.addEventListener('DOMContentLoaded', () => {\n"
        "(async () => {\n" + script + "\n})().catch(error => {\n"
        "const alert = document.getElementById('alert');\n"
        "alert.hidden = false;\n"
        "alert.textContent = 'Preview could not initialize: ' + error.message;\n"
        "});\n});\n</script>"
    )
    replacements = {
        '<link rel="stylesheet" href="./style.css" />': f"<style>\n{css}\n</style>",
        '<script src="./app.js" type="module"></script>': inline_script,
        '<script src="./layout.js" type="module"></script>': (
            "<script>document.addEventListener('DOMContentLoaded', () => {\n"
            + layout_script
            + "\n});</script>"
        ),
        'href="./favicon.svg"': f'href="{data_uri(STATIC / "favicon.svg")}"',
        'href="./docs"': 'href="https://github.com/understandingothers789-pixel/'
        'EloVision/blob/main/docs/BACKEND.md"',
        "<main>": '<main><div class="alert" role="note">Standalone interface preview: '
        "the sample game, board navigation, and rating controls work here. "
        "Run start.bat in the installed app for PGN imports, real Maia analysis, and Stockfish. "
        "No probabilities are simulated.</div>",
    }
    for original, replacement in replacements.items():
        if html.count(original) != 1:
            raise ValueError(f"Preview template changed: expected one {original!r}")
        html = html.replace(original, replacement)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "artifacts" / "EloVision-preview.html"
    )
    print(build_preview(parser.parse_args().output))
