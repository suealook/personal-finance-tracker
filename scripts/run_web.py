import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from web.app import create_app  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    # Flask's interactive debugger must never be reachable over the network.
    # Checking WEB_BIND_HOST directly (not just RUNNING_UNDER_HOME_ASSISTANT)
    # means setting WEB_BIND_HOST=0.0.0.0 for local LAN testing — a
    # completely reasonable thing to want to do without going through Home
    # Assistant — can't accidentally also turn on debug mode and expose an
    # arbitrary-code-execution console to the whole network.
    debug = not settings.RUNNING_UNDER_HOME_ASSISTANT and settings.WEB_BIND_HOST in ("127.0.0.1", "localhost")

    # Plain HTTP, always loopback-only under Home Assistant (the Dockerfile
    # sets WEB_BIND_HOST=127.0.0.1 and WEB_PORT=5001 there) — Caddy is the
    # only thing exposed to the LAN, terminating HTTPS and reverse-proxying
    # here. Flask's own dev-server TLS support (ssl_context=) turned out to
    # be unreliable under real connection patterns; Caddy is a proper,
    # battle-tested TLS terminator instead (see CHANGELOG).
    app.run(host=settings.WEB_BIND_HOST, port=settings.WEB_PORT, debug=debug, use_reloader=False, threaded=True)
