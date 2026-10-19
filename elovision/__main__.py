import argparse
import json
import socket
import threading
import webbrowser

from .config import ModelConfig
from .errors import VisionError
from .model_files import install_model, verified_manifest


def bind_local_server_socket(preferred_port: int, attempts: int = 100):
    """Reserve the preferred loopback port, falling forward when an old server owns it."""
    if not 0 <= preferred_port <= 65535:
        raise ValueError("Port must be between 0 and 65535.")
    if preferred_port == 0:
        ports = [0]
    else:
        ports = [((preferred_port - 1 + offset) % 65535) + 1 for offset in range(attempts)]
    for port in ports:
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server_socket.bind(("127.0.0.1", port))
            server_socket.listen(2048)
            server_socket.setblocking(False)
            return server_socket, server_socket.getsockname()[1]
        except OSError:
            server_socket.close()
    raise OSError(
        f"No free local port in {preferred_port}–{min(preferred_port + attempts - 1, 65535)}. "
        "Close another ELO Vision instance or choose a different --port."
    )


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

    requested_port = getattr(args, "port", 8765)
    server_socket, port = bind_local_server_socket(requested_port)
    if port != requested_port:
        print(
            f"Port {requested_port} is already in use; starting this ELO Vision instance "
            f"at http://127.0.0.1:{port}."
        )
    else:
        print(f"Starting ELO Vision at http://127.0.0.1:{port}.")
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
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="info")
    try:
        uvicorn.Server(config).run(sockets=[server_socket])
    finally:
        server_socket.close()


if __name__ == "__main__":
    main()
