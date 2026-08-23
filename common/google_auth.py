"""Thin wrapper around Google's own OAuth client libraries for "Sign in with
Google" — the app never sees or stores a password or MFA secret; Google's
account security (including its own MFA) does that work.
"""

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from google_auth_oauthlib.flow import Flow

from config import settings

# openid + email is enough to identify who signed in; no Drive/Sheets scopes
# here — this app's own service account (see sheets_client.py) is what talks
# to Sheets, entirely separate from whoever is logging into the dashboard.
SCOPES = ["openid", "https://www.googleapis.com/auth/userinfo.email"]


def _client_config(redirect_uri: str) -> dict:
    return {
        "web": {
            "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
            "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri],
        }
    }


def build_flow(redirect_uri: str, state: str | None = None, code_verifier: str | None = None) -> Flow:
    # code_verifier must be the SAME value on both the authorization request
    # (start route) and the token exchange (callback route) — PKCE, RFC 7636.
    # Flow auto-generates one per-instance by default, which doesn't survive
    # across two separate requests/processes, so the caller must generate it
    # once and pass it explicitly both times (stored in the session between).
    return Flow.from_client_config(
        _client_config(redirect_uri),
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
    )


def exchange_code(flow: Flow, authorization_response_url: str) -> dict:
    """Exchanges the callback's `code` for tokens, verifies the ID token's
    signature/audience/expiry against Google's own public keys, and returns
    its claims (notably `email` and `email_verified`)."""
    flow.fetch_token(authorization_response=authorization_response_url)
    return google_id_token.verify_oauth2_token(
        flow.credentials.id_token, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID
    )
