from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from uned_mcp import auth

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("install_vscode", ROOT / "scripts" / "install_vscode.py")
install_vscode = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install_vscode)


def test_install_preserves_other_servers(tmp_path, monkeypatch):
    monkeypatch.setenv("UNED_MCP_CA_BUNDLE", "/tmp/ca.pem")
    (tmp_path / "mcp.json").write_text(json.dumps({"servers": {"other": {"command": "x"}}, "inputs": []}))
    install_vscode.install_mcp_config(tmp_path, install_vscode.build_local_server_config())
    data = json.loads((tmp_path / "mcp.json").read_text())
    assert data["servers"]["other"] == {"command": "x"}
    uned = data["servers"]["uned"]
    assert uned["args"][-2:] == ["run", "uned-mcp"] and uned["env"]["UNED_MCP_CA_BUNDLE"] == "/tmp/ca.pem"


def test_customizations_copied(tmp_path):
    install_vscode.install_copilot_customizations([tmp_path / "prompts"], [tmp_path / "skills"])
    assert (tmp_path / "prompts" / "uned-tutor.agent.md").exists()
    assert (tmp_path / "prompts" / "uned-hoy.prompt.md").exists()
    assert (tmp_path / "skills" / "estudio-uned" / "SKILL.md").exists()


def _self_signed_pem(org: str) -> bytes:
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, org), x509.NameAttribute(NameOID.COMMON_NAME, org)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=1)).sign(key, hashes.SHA256()))
    return cert.public_bytes(serialization.Encoding.PEM)


def test_proxy_ca_requires_explicit_opt_in(monkeypatch, tmp_path):
    bundle = tmp_path / "ca.pem"
    bundle.write_bytes(_self_signed_pem("Proxy Corp") + _self_signed_pem("Public Root"))
    monkeypatch.delenv("UNED_MCP_CA_BUNDLE", raising=False)
    monkeypatch.delenv("UNED_MCP_PROXY_CA_ORG", raising=False)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    assert auth.corporate_ca_spki_args() == []

    monkeypatch.setenv("UNED_MCP_PROXY_CA_ORG", "proxy corp")
    args = auth.corporate_ca_spki_args()
    assert len(args) == 1 and args[0].count(",") == 0

    monkeypatch.delenv("UNED_MCP_PROXY_CA_ORG")
    monkeypatch.setenv("UNED_MCP_CA_BUNDLE", str(bundle))
    assert auth.corporate_ca_spki_args()[0].count(",") == 1
