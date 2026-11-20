"""Local session tools. No model calls, design adoption, or package publication.

Examples (run from the project root):
  uv run python scripts/session_agent.py pending
  uv run python scripts/session_agent.py claim --project ID --run ID --revision 7
  uv run python scripts/session_agent.py context --project ID --run ID
  uv run python scripts/session_agent.py preview --project ID --run ID --revision 7 --file candidate.json
  uv run python scripts/session_agent.py finish --project ID --run ID --revision 7 --proposal ID

While designing, send heartbeat at least every two minutes. A preview increments
the three-attempt budget. Read repairable_issues and repair, or question/fail.
Only finish a checked candidate; the user adopts it in the browser.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlencode
from urllib.request import Request, urlopen
from uuid import UUID


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["pending", "list", "get", "claim", "context", "heartbeat", "preview", "finish", "question", "answer", "cancel", "fail"])
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--project")
    parser.add_argument("--run")
    parser.add_argument("--revision", type=int)
    parser.add_argument("--worker", default="codex-session")
    parser.add_argument("--file", type=Path)
    parser.add_argument("--proposal")
    parser.add_argument("--text")
    parser.add_argument("--pages", help="Comma-separated 1-based PDF page numbers, at most six")
    parser.add_argument("--output", type=Path, help="Write response JSON here instead of stdout")
    args = parser.parse_args()
    address = urlsplit(args.base)
    if address.scheme != "http" or address.hostname not in {"127.0.0.1", "localhost", "::1"} or address.username or address.password or address.path not in {"", "/"} or address.query or address.fragment:
        parser.error("--base must be a local HTTP workbench origin")

    def call(path, payload=None):
        request = Request(args.base.rstrip("/") + "/api/workbench" + path,
                          data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    try:
        if args.action == "pending":
            result = []
            for project in call("/projects"):
                listing = call("/projects/" + project["id"] + "/design-runs")
                if listing["active"]:
                    result.append({"project_name": project["name"], "run": listing["active"]})
        else:
            if not args.project:
                parser.error("--project is required")
            path = "/projects/" + str(UUID(args.project)) + "/design-runs"
            if args.action == "list":
                result = call(path)
            else:
                if not args.run:
                    parser.error("--run is required")
                path += "/" + str(UUID(args.run))
                if args.action == "get":
                    result = call(path)
                elif args.action == "context":
                    result = call(path + "/context" + ("?" + urlencode({"pages": args.pages}) if args.pages else ""))
                else:
                    if not args.revision or args.revision < 1:
                        parser.error("--revision must be the task's base revision")
                    payload = {"expected_revision": args.revision}
                    if args.action not in {"cancel", "answer"}:
                        payload["worker_id"] = args.worker
                    if args.action == "preview":
                        if not args.file:
                            parser.error("preview requires --file containing {summary, patch}")
                        candidate = json.loads(args.file.read_text(encoding="utf-8-sig"))
                        payload.update(summary=candidate["summary"], patch=candidate["patch"])
                    elif args.action == "finish":
                        if not args.proposal:
                            parser.error("finish requires --proposal")
                        payload["proposal_id"] = str(UUID(args.proposal))
                    elif args.action in {"question", "answer", "fail"}:
                        if not args.text:
                            parser.error(args.action + " requires --text")
                        payload[{"question": "question", "answer": "answer", "fail": "message"}[args.action]] = args.text
                    result = call(path + "/" + args.action, payload)
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.write_text(encoded + "\n", encoding="utf-8")
            print(str(args.output.resolve()))
        else:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            print(encoded)
    except HTTPError as exc:
        print(f"HTTP {exc.code}: " + exc.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except (URLError, ValueError, KeyError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
