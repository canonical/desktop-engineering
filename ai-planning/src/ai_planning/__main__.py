"""CLI entry point for the sync job: `python -m ai_planning`.

This is pure glue for the cron (ticket 04): read the token and Project id from
the environment, build the live client, run one sync pass, print a summary.
It holds no board logic — every decision is in `sync_status`.

Environment:
    AI_PLANNING_TOKEN   fine-grained PAT (Issues:read/write, PRs:read, Projects:write)
    AI_PLANNING_PROJECT_ID      the Project v2 node id (PVT_...)
    AI_PLANNING_REPO    the planning repo as `owner/name` (pass 0 seeds its issues
                        onto the board, and their sub-issue children transitively)
    AI_PLANNING_LINK_SCAN_REPOS    optional comma-separated `owner/name` list of
                        destination repos the link-authoring reconcile arm scans
                        for PRs missing their deliberate ticket link (ticket 33).
                        Deliberately its own variable, distinct from the retired
                        detection guard `AI_PLANNING_DESTINATION_REPOS`, even
                        though it may hold the same repos in practice. Unset
                        skips the reconcile arm entirely.
"""

from __future__ import annotations

import os
import sys

from ai_planning.client import GraphQLClient
from ai_planning.job import run_sync
from ai_planning.link_authoring_job import author_missing_links


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

    client = GraphQLClient.with_token(token)

    link_scan_repos = os.environ.get("AI_PLANNING_LINK_SCAN_REPOS")
    if link_scan_repos:
        destination_repos = [
            repo.strip() for repo in link_scan_repos.split(",") if repo.strip()
        ]
        link_result = author_missing_links(client, destination_repos)
        for pr_label, ref in link_result.authored:
            print(f"linked {pr_label} -> {ref.repo_full_name}#{ref.number}")
        if link_result.ambiguous:
            print(
                f"ambiguous link target, authored nothing: {link_result.ambiguous}",
                file=sys.stderr,
            )
        print(
            f"link_authored={len(link_result.authored)} "
            f"link_unchanged={len(link_result.unchanged)} "
            f"link_ambiguous={len(link_result.ambiguous)} "
            f"link_no_candidates={len(link_result.no_candidates)}",
            file=sys.stderr,
        )

    result = run_sync(
        client,
        project_id,
        planning_repo=planning_repo,
    )

    for item_id, status in result.written:
        print(f"{item_id} -> {status.value}")
    print(
        f"seeded={len(result.seeded)} "
        f"written={len(result.written)} "
        f"unchanged={len(result.unchanged)} "
        f"skipped_maps={len(result.skipped_maps)} "
        f"skipped_contentless={len(result.skipped_contentless)} "
        f"skipped_closed={len(result.skipped_closed)} "
        f"closed_issues={len(result.closed_issues)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
