import argparse
import json
import threading
import webbrowser

from .config import ModelConfig
from .errors import VisionError
from .model_files import install_model, verified_manifest


def main():
    parser = argparse.ArgumentParser(description="ELO Vision — local Maia 3 human chess analysis")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="Start the local browser application")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--open", action="store_true", help="Open your default browser")
    model = sub.add_parser("model", help="Install or verify the official weights")
    model.add_argument("action", choices=["install", "verify"])
    model.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.command == "model":
        try:
            config = ModelConfig()
            result = (
                install_model(config, force=args.force)
                if args.action == "install"
                else verified_manifest(config)
            )
            print(json.dumps(result, indent=2))
        except VisionError as exc:
            parser.exit(1, f"{exc.code}: {exc}\n")
        return
    import uvicorn

    from .app import create_app

    port = getattr(args, "port", 8765)
    if getattr(args, "open", False):

        def open_when_ready():
            import time
            import urllib.request

            for _ in range(40):
                try:
                    with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/v1/health", timeout=1
                    ):
                        webbrowser.open(f"http://127.0.0.1:{port}")
                        return
                except OSError:
                    time.sleep(0.25)

        threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
