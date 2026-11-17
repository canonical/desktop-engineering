"""The repo-board sync: one repo, its own linked board, zero configuration.

For a code repo whose planning issues live in the repo itself (maps, specs,
tickets — the Wayfinder work in `canonical/warty-whisperer`), the board is an
org Project **linked to that repo** and discoverable by its **predictive
title** (default `AI planning`). Nothing is configured: no boards JSON, no
variables, no dispatch relays. The only setting is one secret, the PAT that
Projects v2 requires (the `GITHUB_TOKEN` is repo-scoped and cannot resolve a
ProjectV2 at all — verified live even for a repo-linked board).

    python -m ai_planning.repo_board

Environment:
    AI_PLANNING_TOKEN           the fine-grained PAT (Issues RW on this repo
                                + org Projects RW). The only required setting.
    GITHUB_REPOSITORY           the caller repo as `owner/name` — set by
                                Actions; the repo whose issues seed the board.
    AI_PLANNING_PROJECT_NAME    optional. The board's title, matched exactly
                                against the repo's linked projects. Default:
                                `AI planning`.
    AI_PLANNING_SEED_LABELS     optional comma-separated labels narrowing which
                                open issues seed the board. Default: the
                                agent-work vocabulary (`ready-for-agent`,
                                `ready-for-human`, `wayfinder:*`).

The sweep itself is the shared one (`job.run_sync`): seeds the repo's open
labelled issues plus their sub-issue trees, scores every card off live facts,
self-closes tickets whose linked PR merged, cascades maps, and authors the
missing ticket links of this repo's PRs (every PR into a non-default branch —
a stack PR into a spec branch — never gets one from GitHub, which ignores
`Closes` there). Map archiving is left out on purpose: no `wayfinder:archived`
marker is needed, finished maps stay visible and are hidden by hand or by the
project's native auto-archive.
"""

from __future__ import annotations

import os
import sys

from ai_planning.client import GraphQLClient
from ai_planning.job import run_sync
from ai_planning.link_authoring_job import author_missing_links

DEFAULT_PROJECT_NAME = "AI planning"

# The agent-work vocabulary: what lands on the board by default. A bug or an
# unlabelled idea never does; a spec and its tickets travel together regardless
# of their own labels (the sub-issue tree is seeded transitively).
DEFAULT_SEED_LABELS = (
    "ready-for-agent",
    "ready-for-human",
    "wayfinder:map",
    "wayfinder:task",
    "wayfinder:research",
    "wayfinder:prototype",
    "wayfinder:grilling",
)

_LINKED_PROJECTS_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    projectsV2(first: 20) {
      nodes { id number title }
    }
  }
}
"""


def pick_project(
    nodes: list[dict], title: str
) -> tuple[str, int] | None:
    """The `(project id, number)` of the repo's linked project titled `title`.

    Exact title match, case-sensitive. None when the repo has no such linked
    project; a ValueError when it has more than one (the predictive name must
    stay unique within the repo).
    """

    matches = [(n["id"], n["number"]) for n in nodes if n.get("title") == title]
    if len(matches) > 1:
        numbers = ", ".join(f"#{number}" for _, number in matches)
        raise ValueError(
            f"several linked projects are titled {title!r} ({numbers}) —"
            " rename all but one"
        )
    return matches[0] if matches else None


def main() -> int:
    token = os.environ.get("AI_PLANNING_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo or repo.count("/") != 1:
        print("set AI_PLANNING_TOKEN (and run inside a repo)", file=sys.stderr)
        return 2
    owner, name = repo.split("/", 1)
    project_name = os.environ.get("AI_PLANNING_PROJECT_NAME") or DEFAULT_PROJECT_NAME
    seed_labels = tuple(
        label.strip()
        for label in os.environ.get("AI_PLANNING_SEED_LABELS", "").split(",")
        if label.strip()
    ) or DEFAULT_SEED_LABELS

    client = GraphQLClient.with_token(token)

    # Author this repo's missing ticket links first: GitHub ignores `Closes`
    # on any PR that does not target the default branch — every stack PR into
    # a spec branch — so the sweep would never see those PRs without this.
    # A scan failure (a token too narrow to read PRs) must not kill the
    # status sweep: log it and reconcile the board anyway.
    try:
        link_result = author_missing_links(client, [repo])
    except Exception as error:  # noqa: BLE001 - reported, then non-fatal
        print(f"error: link scan failed ({error}); sweeping anyway", file=sys.stderr)
    else:
        for pr_label, ref in link_result.authored:
            print(f"linked {pr_label} -> {ref.repo_full_name}#{ref.number}")
        print(
            f"link_authored={len(link_result.authored)} "
            f"link_unchanged={len(link_result.unchanged)} "
            f"link_ambiguous={len(link_result.ambiguous)} "
            f"link_no_candidates={len(link_result.no_candidates)}",
            file=sys.stderr,
        )

    data = client.execute(_LINKED_PROJECTS_QUERY, {"owner": owner, "name": name})
    nodes = ((data.get("repository") or {}).get("projectsV2") or {}).get("nodes") or []
    found = pick_project(nodes, project_name)
    if found is None:
        linked = ", ".join(f"#{n['number']} {n['title']!r}" for n in nodes) or "none"
        print(
            f"error: no linked project titled {project_name!r} on {repo}"
            f" (linked: {linked}) — run ai-planning/setup-dest-board.sh",
            file=sys.stderr,
        )
        return 2
    project_id, number = found

    result = run_sync(
        client,
        project_id,
        planning_repo=repo,
        seed_labels=seed_labels,
        archived_label=None,  # no map archiving on a repo board: no marker
    )
    print(
        f"[{repo}] project #{number}: seeded={len(result.seeded)} "
        f"written={len(result.written)} unchanged={len(result.unchanged)} "
        f"skipped_maps={len(result.skipped_maps)} "
        f"closed_issues={len(result.closed_issues)} "
        f"map_closed={len(result.map_closed)} map_reopened={len(result.map_reopened)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())