import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from web.app import create_app  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    # Flask's interactive debugger must never be reachable over the network — only
    # enable it for local dev, where the app is bound to 127.0.0.1 anyway.
    debug = not settings.RUNNING_UNDER_HOME_ASSISTANT
    app.run(host=settings.WEB_BIND_HOST, port=settings.WEB_PORT, debug=debug, use_reloader=False)
