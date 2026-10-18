from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys

from uned_mcp import client


def check() -> int:
    site = client.call("core_webservice_get_site_info")
    if client.is_error(site):
        print(f"Token NO válido → {site.get('error')}: {site.get('message')}")
        return 1
    print(f"Token OK — {site.get('fullname')} ({site.get('sitename')})")
    return 0


def _ensure_token() -> None:
    """Silently renew an expired token from the saved SSO session (headless)."""
    if not client.is_error(client.call("core_webservice_get_site_info")):
        return
    from uned_mcp import auth

    token = auth.refresh_from_saved_session()
    if token:
        print(auth._store_token(token), file=sys.stderr)


def _notify(title: str, body: str) -> None:
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", title, body[:500]], check=False)  # noqa: S603,S607


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(prog="uned-mcp", description="Servidor MCP y utilidades del campus UNED.")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="Arranca el servidor MCP por stdio (por defecto).")
    sub.add_parser("check", help="Comprueba el token.")
    sub.add_parser("login", help="Login SSO en el navegador.")
    p_sync = sub.add_parser("sync", help="Sincroniza materiales, guías, plazos y fichas en ~/UNED.")
    p_sync.add_argument("asignatura", nargs="?", default=None)
    p_sync.add_argument("--forzar", action="store_true")
    p_res = sub.add_parser("resumen", help="Sincroniza y muestra novedades (para cron).")
    p_res.add_argument("--notify", action="store_true", help="Notificación de escritorio si hay cambios.")
    p_plan = sub.add_parser("plan", help="Genera ~/UNED/plan-semanal.md.")
    p_plan.add_argument("--horas", type=float, default=10)
    p_plan.add_argument("--semanas", type=int, default=4)
    args = parser.parse_args()

    if args.cmd == "check":
        sys.exit(check())
    if args.cmd == "login":
        from uned_mcp import auth

        print(auth.interactive_login())
        return
    if args.cmd in ("sync", "resumen"):
        from uned_mcp import study

        _ensure_token()
        try:
            out = study.sync(getattr(args, "asignatura", None), getattr(args, "forzar", False),
                             progress=lambda m: print(m, file=sys.stderr))
        except (RuntimeError, ValueError) as exc:
            print(exc)
            if getattr(args, "notify", False):
                _notify("UNED", str(exc))
            sys.exit(1)
        print(out)
        if getattr(args, "notify", False):
            head = out.split("\n", 1)[0]
            if any(f"{k}: 0" not in head for k in ("materiales nuevos", "plazos nuevos/cambiados", "anuncios nuevos")):
                _notify("Novedades UNED", head)
        return
    if args.cmd == "plan":
        from uned_mcp import planner

        path, text = planner.write_plan(args.horas, args.semanas)
        print(text)
        print(f"\nGuardado en {path}", file=sys.stderr)
        return
    from uned_mcp.server import create_server

    create_server().run()


if __name__ == "__main__":
    main()
