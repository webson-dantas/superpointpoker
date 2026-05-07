"""Launcher for SuperPoint Poker. Run with --http or --https (default: --https)."""
import sys
import os
import subprocess
import threading
import re
import time
import shutil

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_DIR = os.path.join(APP_DIR, ".streamlit")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.toml")

BASE_CONFIG = """\
[server]
port = 8000
address = "::"
headless = true
"""

SSL_CONFIG = """\
sslCertFile = "cert.pem"
sslKeyFile = "key.pem"
"""


def write_config(use_https):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(BASE_CONFIG)
        if use_https:
            f.write(SSL_CONFIG)


def start_cloudflared(port):
    """Start cloudflared tunnel and return the public URL."""
    cloudflared_path = shutil.which("cloudflared")
    if not cloudflared_path:
        # Try common install locations on Windows
        common_paths = [
            os.path.expandvars(r"%ProgramFiles(x86)%\cloudflared\cloudflared.exe"),
            os.path.expandvars(r"%ProgramFiles%\cloudflared\cloudflared.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\cloudflared\cloudflared.exe"),
            os.path.expanduser(r"~\.cloudflared\cloudflared.exe"),
        ]
        # Also search WinGet packages folder
        winget_dir = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages")
        if os.path.isdir(winget_dir):
            for root, dirs, files in os.walk(winget_dir):
                if "cloudflared.exe" in files:
                    common_paths.append(os.path.join(root, "cloudflared.exe"))
                    break
        for p in common_paths:
            if os.path.isfile(p):
                cloudflared_path = p
                break

    if not cloudflared_path:
        print("[!] cloudflared not found in PATH. Skipping tunnel.")
        print("[!] Install it: winget install Cloudflare.cloudflared")
        return None

    proc = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", f"http://localhost:{port}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    # Parse output to find the public URL
    url = None
    deadline = time.time() + 30  # wait up to 30s for tunnel
    for line in iter(proc.stdout.readline, ""):
        match = re.search(r"(https://[a-zA-Z0-9\-]+\.trycloudflare\.com)", line)
        if match:
            url = match.group(1)
            break
        if time.time() > deadline:
            break

    # Keep reading output in background (discard)
    def drain():
        try:
            for _ in iter(proc.stdout.readline, ""):
                pass
        except:
            pass

    threading.Thread(target=drain, daemon=True).start()
    return url


def main():
    use_https = "--http" not in sys.argv
    write_config(use_https)

    port = 8000

    # Start Streamlit in background (suppress its output)
    streamlit_proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py"],
        cwd=APP_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Wait a moment for Streamlit to start
    time.sleep(3)

    # Start cloudflared tunnel
    print("Starting cloudflared tunnel...")
    public_url = start_cloudflared(port)

    print()
    print("=" * 60)
    print("  🃏 SuperPoint Poker is LIVE!")
    print("=" * 60)
    print()
    if public_url:
        print(f"  Share this link with your team:")
        print(f"  👉  {public_url}")
    else:
        protocol = "https" if use_https else "http"
        print(f"  Local:    {protocol}://localhost:{port}")
        print(f"  (No tunnel available — share your IP manually)")
    print()
    print("=" * 60)
    print("  Press Ctrl+C to stop the server")
    print("=" * 60)
    print()

    try:
        streamlit_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down...")
        streamlit_proc.terminate()


if __name__ == "__main__":
    main()
