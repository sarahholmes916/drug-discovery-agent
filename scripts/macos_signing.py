"""CI-only temporary signing keychain. Never print secrets or their commands."""
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys

root = Path(os.environ["RUNNER_TEMP"])
keychain = root / "companion-signing.keychain-db"
certificate = root / "companion-signing.p12"
key = root / "companion-notary.p8"


def run(*args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode:
        # Avoid CalledProcessError's repr of secret-bearing argv.
        raise RuntimeError(f"Signing credential operation failed: {args[0]} {args[1]}")
    return result.stdout


if sys.argv[1] == "cleanup":
    if keychain.exists():
        run("security", "delete-keychain", str(keychain))
    certificate.unlink(missing_ok=True)
    key.unlink(missing_ok=True)
else:
    names = ["MACOS_CERTIFICATE_P12_BASE64", "MACOS_CERTIFICATE_PASSWORD", "MACOS_SIGNING_IDENTITY",
             "APPLE_API_KEY_BASE64", "APPLE_API_KEY_ID", "APPLE_API_ISSUER"]
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing signing secrets: " + ", ".join(missing))
    certificate.write_bytes(base64.b64decode(os.environ[names[0]], validate=True))
    key.write_bytes(base64.b64decode(os.environ["APPLE_API_KEY_BASE64"], validate=True))
    certificate.chmod(0o600)
    key.chmod(0o600)
    password = secrets.token_urlsafe(32)
    run("security", "create-keychain", "-p", password, str(keychain))
    run("security", "set-keychain-settings", "-lut", "21600", str(keychain))
    run("security", "unlock-keychain", "-p", password, str(keychain))
    run("security", "import", str(certificate), "-k", str(keychain), "-P", os.environ[names[1]], "-T", "/usr/bin/codesign")
    run("security", "set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k", password, str(keychain))
    run("security", "list-keychains", "-d", "user", "-s", str(keychain))
    with open(os.environ["GITHUB_ENV"], "a", encoding="utf-8") as handle:
        for name in ("MACOS_SIGNING_IDENTITY", "APPLE_API_KEY_ID", "APPLE_API_ISSUER"):
            value = os.environ[name]
            if "\n" in value or "\r" in value:
                raise ValueError("Invalid signing configuration")
            handle.write(f"{name}={value}\n")
        handle.write(f"APPLE_API_KEY_PATH={key}\n")
    certificate.unlink()
