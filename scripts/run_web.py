import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402
from web.app import create_app  # noqa: E402

if __name__ == "__main__":
    app = create_app()
    app.run(
        host=settings.WEB_BIND_HOST,
        port=settings.WEB_PORT,
        debug=settings.DEBUG,
        use_reloader=False,
        threaded=True,
    )
