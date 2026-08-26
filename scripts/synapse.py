#!/usr/bin/env python3
"""
synapse - command line client for the SynapseNode agent.

Talks to the Collaborative Partner and the task queue, against either a local
server or the private Cloud Run service. For Cloud Run it attaches a gcloud
identity token per request, so the service never needs an allUsers binding.

    synapse chat "free evening, what should I do?"
    synapse add "Fix the leaking tap"
    synapse tasks
    synapse state --energy 7 --receptivity 0.9
    synapse nudge
    synapse chat "..." --local        # hit http://localhost:8080 instead
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

SERVICE = os.getenv("SYNAPSE_SERVICE", "synapse-node-backend")
REGION = os.getenv("SYNAPSE_REGION", "us-central1")
LOCAL_URL = os.getenv("SYNAPSE_LOCAL_URL", "http://localhost:8080")

DIM, BOLD, GREEN, YELLOW, RESET = "\033[2m", "\033[1m", "\033[32m", "\033[33m", "\033[0m"
if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
    DIM = BOLD = GREEN = YELLOW = RESET = ""

_cache = {"url": None, "token": None, "token_expires": 0.0}


def _gcloud(*args, timeout=120):
    try:
        r = subprocess.run(["gcloud", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        sys.exit("gcloud not found on PATH. Add /snap/bin, or use --local.")
    if r.returncode != 0:
        sys.exit(f"gcloud {' '.join(args)} failed:\n{r.stderr.strip()}")
    return r.stdout.strip()


def cloud_url():
    if not _cache["url"]:
        url = _gcloud("run", "services", "describe", SERVICE,
                      "--region", REGION, "--format", "value(status.url)")
        if not url:
            sys.exit(f"No Cloud Run service '{SERVICE}' in {REGION}. Deploy it, or use --local.")
        _cache["url"] = url
    return _cache["url"]


def identity_token():
    if _cache["token"] and time.time() < _cache["token_expires"]:
        return _cache["token"]
    _cache["token"] = _gcloud("auth", "print-identity-token", timeout=60)
    _cache["token_expires"] = time.time() + 45 * 60
    return _cache["token"]


def call(path, method="GET", payload=None, local=False, timeout=300):
    base = LOCAL_URL if local else cloud_url()
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data:
        req.add_header("Content-Type", "application/json")
    if not local:
        req.add_header("Authorization", f"Bearer {identity_token()}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:
            detail = body
        sys.exit(f"{YELLOW}HTTP {e.code}{RESET} from {path}: {detail}")
    except urllib.error.URLError as e:
        where = "localhost" if local else "Cloud Run"
        sys.exit(f"Could not reach {where}: {e.reason}")


def wrap(text, width=76, indent="  "):
    out = []
    for para in (text or "").split("\n"):
        if not para.strip():
            out.append("")
            continue
        line = indent
        for word in para.split():
            if len(line) + len(word) + 1 > width and line.strip():
                out.append(line.rstrip())
                line = indent
            line += word + " "
        out.append(line.rstrip())
    return "\n".join(out)


# ---- commands -----------------------------------------------------------

def cmd_chat(a):
    r = call("/api/partner/chat", "POST",
             {"message": a.message, "session_id": a.session}, a.local)
    where = "localhost" if a.local else "Cloud Run"
    print(f"\n{DIM}Partner · {r.get('model','?')} · via {where}{RESET}\n")
    print(wrap(r.get("reply")))
    print()


def cmd_add(a):
    call("/api/ingest", "POST", {"raw_text": "\n".join(a.task)}, a.local)
    n = len(a.task)
    print(f"{GREEN}added{RESET} {n} task{'s' if n != 1 else ''}")


def cmd_tasks(a):
    tasks = call("/api/tasks", local=a.local).get("tasks", [])
    open_ = [t for t in tasks if not t.get("completed")]
    if not open_:
        print(f"{DIM}no open tasks{RESET}")
        return
    print(f"\n{BOLD}{len(open_)} open{RESET}\n")
    for t in open_:
        print(f"  {t.get('id','?'):<9} {t.get('title','untitled')[:44]:<46}"
              f"{DIM}{t.get('effort',0):>4.1f}h{RESET}")
    print()


def cmd_state(a):
    r = call("/api/user-state", "POST",
             {"energy": a.energy, "receptivity": a.receptivity}, a.local)
    s = r.get("user_state", {})
    print(f"{GREEN}set{RESET} energy={s.get('energy')}h receptivity={s.get('receptivity')}")


def cmd_nudge(a):
    r = call("/api/nudges", local=a.local)
    nudges = r.get("nudges", [])
    if not nudges:
        print(f"{DIM}no nudge (throttled by the cognitive load boundary){RESET}")
        return
    n = nudges[-1]
    print(f"\n{DIM}source: {n.get('source')}{RESET}")
    print(wrap(n.get("message")))
    print()


def cmd_status(a):
    r = call("/api/status", local=a.local)
    print(f"\n{BOLD}{'localhost' if a.local else cloud_url()}{RESET}\n")
    for key, svc in (r.get("services") or {}).items():
        print(f"  {svc.get('status','?'):<8} {key}")
    print()


def main():
    p = argparse.ArgumentParser(prog="synapse", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--local", action="store_true",
                   help=f"target {LOCAL_URL} instead of Cloud Run")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("chat", help="talk to the Collaborative Partner")
    c.add_argument("message")
    c.add_argument("--session", default="cli")
    c.set_defaults(fn=cmd_chat)

    c = sub.add_parser("add", help="add one or more tasks")
    c.add_argument("task", nargs="+")
    c.set_defaults(fn=cmd_add)

    c = sub.add_parser("tasks", help="list open tasks")
    c.set_defaults(fn=cmd_tasks)

    c = sub.add_parser("state", help="set energy and receptivity")
    c.add_argument("--energy", type=float, required=True)
    c.add_argument("--receptivity", type=float, required=True)
    c.set_defaults(fn=cmd_state)

    c = sub.add_parser("nudge", help="fetch a behavioural nudge")
    c.set_defaults(fn=cmd_nudge)

    c = sub.add_parser("status", help="show backing Google Cloud services")
    c.set_defaults(fn=cmd_status)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
