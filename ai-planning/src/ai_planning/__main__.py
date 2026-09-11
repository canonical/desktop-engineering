"""CLI entry point for the sync job: `python -m ai_planning`.

This is pure glue for the cron (ticket 04): read the token and Project id from
the environment, build the live client, run one sync pass, print a summary.
It holds no board logic — every decision is in `sync_status`.

Environment:
    AI_PLANNING_TOKEN   fine-grained PAT (Issues:read/write, PRs:read, Projects:write)
    AI_PLANNING_PROJECT_ID      the Project v2 node id (PVT_...)
    AI_PLANNING_REPO    the planning repo as `owner/name` (pass 0 seeds its issues
                        onto the board, and their sub-issue children transitively)
    AI_PLANNING_DESTINATION_REPOS   optional, comma/space-separated `owner/name`
                        allow-list of code repos whose merged PRs may complete a
                        cross-repo implementation ticket via the timeline fallback
                        (ticket 06). Unset -> the fallback stays inert.
"""

from __future__ import annotations

import os
import sys

from ai_planning.client import GraphQLClient
from ai_planning.job import run_sync


def _parse_destination_repos(raw: str | None) -> set[str]:
    """Split the allow-list env value on commas/whitespace into `owner/name`s."""

    if not raw:
        return set()
    return {token for token in raw.replace(",", " ").split() if token}


def main(argv: list[str] | None = None) -> int:
    token = os.environ.get("AI_PLANNING_TOKEN")
    project_id = os.environ.get("AI_PLANNING_PROJECT_ID")
    planning_repo = os.environ.get("AI_PLANNING_REPO")
    if not token or not project_id or not planning_repo:
        print(
            "set AI_PLANNING_TOKEN, AI_PLANNING_PROJECT_ID and AI_PLANNING_REPO",
            file=sys.stderr,
        )
        return 2

    destination_repos = _parse_destination_repos(
        os.environ.get("AI_PLANNING_DESTINATION_REPOS")
    )

    client = GraphQLClient.with_token(token)
    result = run_sync(
        client,
        project_id,
        planning_repo=planning_repo,
        destination_repos=destination_repos,
    )

    for item_id, status in result.written:
        print(f"{item_id} -> {status.value}")
    print(
        f"seeded={len(result.seeded)} "
        f"written={len(result.written)} "
        f"unchanged={len(result.unchanged)} "
        f"skipped_maps={len(result.skipped_maps)} "
        f"skipped_contentless={len(result.skipped_contentless)} "
        f"closed_issues={len(result.closed_issues)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
