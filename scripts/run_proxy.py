#!/usr/bin/env python3
"""
Local authenticated proxy to a private Cloud Run service.

Stands in for `gcloud run services proxy`, which cannot install its
`cloud-run-proxy` component when the Google Cloud CLI was installed by snap or
another external package manager.

Browse http://localhost:8080 and every request is forwarded to the Cloud Run
service with a fresh identity token attached, so the service can stay private
(no allUsers binding) while the UI still works in a browser for a demo.

    python scripts/run_proxy.py
    python scripts/run_proxy.py --service synapse-node-backend --port 8080
"""
import argparse
import http.server
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

_token = {"value": None, "expires": 0.0}


def identity_token() -> str:
    """Returns a cached gcloud identity token, refreshing before it expires."""
    if _token["value"] and time.time() < _token["expires"]:
        return _token["value"]
    try:
        out = subprocess.run(
            ["gcloud", "auth", "print-identity-token"],
            capture_output=True, text=True, timeout=60, check=True,
        )
    except FileNotFoundError:
        sys.exit("gcloud not found on PATH. Add /snap/bin, or install the Cloud CLI.")
    except subprocess.CalledProcessError as e:
        sys.exit(f"Could not get an identity token:\n{e.stderr.strip()}")
    _token["value"] = out.stdout.strip()
    _token["expires"] = time.time() + 45 * 60  # tokens last an hour
    return _token["value"]


def service_url(service: str, region: str) -> str:
    out = subprocess.run(
        ["gcloud", "run", "services", "describe", service,
         "--region", region, "--format", "value(status.url)"],
        capture_output=True, text=True, timeout=120,
    )
    url = out.stdout.strip()
    if not url:
        sys.exit(f"Could not resolve a URL for '{service}' in {region}:\n{out.stderr.strip()}")
    return url


def make_handler(target: str):
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            sys.stderr.write("  %s\n" % (fmt % args))

        def _forward(self, method: str):
            body = None
            length = self.headers.get("Content-Length")
            if length:
                body = self.rfile.read(int(length))

            req = urllib.request.Request(target + self.path, data=body, method=method)
            for k, v in self.headers.items():
                if k.lower() not in HOP_BY_HOP:
                    req.add_header(k, v)
            req.add_header("Authorization", f"Bearer {identity_token()}")
            if body is not None:
                req.add_header("Content-Length", str(len(body)))

            try:
                with urllib.request.urlopen(req, timeout=300) as resp:
                    payload, status, headers = resp.read(), resp.status, resp.headers
            except urllib.error.HTTPError as e:
                payload, status, headers = e.read(), e.code, e.headers
            except Exception as e:
                msg = f"proxy error: {e}".encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
                return

            self.send_response(status)
            for k, v in headers.items():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):    self._forward("GET")
        def do_POST(self):   self._forward("POST")
        def do_PUT(self):    self._forward("PUT")
        def do_DELETE(self): self._forward("DELETE")

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--service", default="synapse-node-backend")
    ap.add_argument("--region", default="us-central1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()

    target = service_url(args.service, args.region)
    identity_token()  # fail fast if auth is not set up

    print(f"Proxying http://localhost:{args.port}  ->  {target}")
    print("The service stays private; this adds your identity token per request.")
    print("Ctrl+C to stop.\n")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(target))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
