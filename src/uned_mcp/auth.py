from __future__ import annotations

import base64
import binascii
import contextlib
import os
import re
import time
import warnings
from pathlib import Path
from urllib.parse import unquote

from uned_mcp import client, config

LAUNCH_PATH = "/admin/tool/mobile/launch.php?service=moodle_mobile_app&passport=1&urlscheme=moodleappfs"
# The site may override the scheme (UNED uses ltgopenlmsapp://), so accept any custom scheme.
_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[a-z][a-z0-9+.-]*://token=([^\"'\s<>&]+)")


def decode_token(raw: str) -> str | None:
    """Extract the web service token from the value after '<scheme>://token='.

    Moodle sends base64("siteid:::token[:::privatetoken]"). A plain token is also accepted.
    """
    raw = unquote(raw).strip()
    try:
        decoded = base64.b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        decoded = ""
    parts = decoded.split(":::")
    if len(parts) >= 2 and re.fullmatch(r"[A-Za-z0-9]+", parts[1]):
        return parts[1]
    return raw if re.fullmatch(r"[A-Za-z0-9]{20,}", raw) else None


def corporate_ca_spki_args() -> list[str]:
    """Chromium ignores the system CA store; trust only the TLS-inspection proxy CAs.

    Uses --ignore-certificate-errors-spki-list (normal verification stays on for everything else):
    - UNED_MCP_PROXY_CA_ORG set (comma-separated): certificates of the CA bundle whose subject
      contains one of those organization names (bundle from UNED_MCP_CA_BUNDLE or REQUESTS_CA_BUNDLE).
    - otherwise: every certificate of UNED_MCP_CA_BUNDLE, which should contain only the proxy CA.
    """
    orgs = [o.strip().lower() for o in os.environ.get("UNED_MCP_PROXY_CA_ORG", "").split(",") if o.strip()]
    bundle = os.environ.get("UNED_MCP_CA_BUNDLE") or (os.environ.get("REQUESTS_CA_BUNDLE") if orgs else None)
    if not bundle or not Path(bundle).is_file():
        return []
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    hashes_b64 = []
    pem = Path(bundle).read_bytes()
    for block in re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", pem, re.S):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")  # some bundled CAs have non-RFC-5280 serial numbers
                cert = x509.load_pem_x509_certificate(block)
        except ValueError:
            continue
        subject = cert.subject.rfc4514_string().lower()
        if orgs and not any(o in subject for o in orgs):
            continue
        spki = cert.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        digest = hashes.Hash(hashes.SHA256())
        digest.update(spki)
        hashes_b64.append(base64.b64encode(digest.finalize()).decode())
    return [f"--ignore-certificate-errors-spki-list={','.join(hashes_b64)}"] if hashes_b64 else []


def find_token(text: str) -> str | None:
    m = _TOKEN_RE.search(text or "")
    return decode_token(m.group(1)) if m else None


def refresh_from_saved_session() -> str | None:
    """Try to obtain a new token headlessly from the saved SSO session. Returns the token or None."""
    if not config.SESSION_FILE.is_file():
        return None
    from playwright.sync_api import sync_playwright

    seen: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(args=corporate_ca_spki_args())
        try:
            page = browser.new_context(storage_state=str(config.SESSION_FILE)).new_page()
            page.on("requestfailed", lambda req: seen.append(req.url) if "://token=" in req.url else None)
            with contextlib.suppress(Exception):
                page.goto(f"{config.BASE_URL}{LAUNCH_PATH}", wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        finally:
            browser.close()
    return next((t for t in map(find_token, seen) if t), None)


def interactive_login() -> str:
    """Open Chromium, let the user complete the SSO and capture the mobile-app token."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return "Falta Playwright. Ejecuta: uv sync && uv run playwright install chromium"

    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    token = None
    with contextlib.suppress(Exception):
        token = refresh_from_saved_session()
    if token:
        return _store_token(token)
    seen: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=corporate_ca_spki_args())
        context = browser.new_context(locale="es-ES")
        page = context.new_page()
        page.on("request", lambda req: seen.append(req.url) if "://token=" in req.url else None)
        page.on("requestfailed", lambda req: seen.append(req.url) if "://token=" in req.url else None)
        try:
            page.goto(f"{config.BASE_URL}/login/index.php", wait_until="domcontentloaded")
            deadline = time.time() + 300
            while time.time() < deadline:
                try:
                    url = page.url
                except Exception:
                    return "Navegador cerrado antes de completar el login. Inténtalo de nuevo."
                if config.BASE_URL in url and "login/index.php" not in url and "login.uned.es" not in url:
                    break
                page.wait_for_timeout(1000)
            else:
                return "Timeout de 5 minutos sin detectar el login. Inténtalo de nuevo."

            context.storage_state(path=str(config.SESSION_FILE))
            config.SESSION_FILE.chmod(0o600)

            with contextlib.suppress(Exception):  # navigating to the app scheme fails on purpose
                page.goto(f"{config.BASE_URL}{LAUNCH_PATH}", wait_until="domcontentloaded")

            token = None
            for _ in range(30):
                token = next((t for t in map(find_token, seen) if t), None)
                if not token:
                    with contextlib.suppress(Exception):
                        token = find_token(page.content())
                if token:
                    break
                page.wait_for_timeout(500)
        finally:
            browser.close()

    if not token:
        return ("No se pudo capturar el token (posiblemente el servicio móvil está deshabilitado "
                "en agora.uned.es). Reporta este mensaje a tu asistente.")

    return _store_token(token)


def _store_token(token: str) -> str:
    client.save_auth({"token": token, "capturado": client.fmt_ts(time.time())})
    site = client.call("core_webservice_get_site_info")
    if client.is_error(site):
        client.clear_auth()
        return f"Token capturado pero no es válido ({site.get('error')}: {site.get('message')})."
    client.save_auth({"token": token, "capturado": client.fmt_ts(time.time()), "siteinfo": site})
    return f"Login OK ({site.get('fullname')}). Ya puedes preguntar por cursos, entregas, notas o anuncios."
