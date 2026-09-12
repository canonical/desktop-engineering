"""The shared, pure authoring rule (ticket 33 / decision #29).

Detection (`facts_mapping`) scores a card off a *deliberate* native link
(`closedByPullRequestsReferences`/`closingIssuesReferences(userLinkedOnly:
true)`), so it stays inert until something authors that link. This module
picks the single correct ticket a PR should be linked to, so both the
immediate arm (ticket 35, not built here) and the reconcile arm
(`link_authoring_job`) apply the identical rule and a PR always lands on
exactly one ticket.

**Signal = the PR body**, parsed here with no GraphQL: a `Ticket: <url>` field
is the happy-path convention and, when present, is the sole candidate — it
guarantees exactly one ticket on the fast path. Failing that, closing
keywords (`closes #12`, `fixes owner/repo#34`, ...) are parsed for every
referenced ticket, the degrade path a pre-adoption or keyword-only PR needs.

**Tie-break by kind** then picks among whatever candidates were found: a
same-repo `wayfinder:spec`-labelled issue always outranks any other
referenced ticket (a spec-branch PR links the spec, never its impl tickets).
Absent a spec candidate, exactly one remaining candidate is unambiguous;
more than one is a defect this module refuses to guess at — it returns
`None` so the caller can author nothing and surface it.

Callers resolve each parsed `TicketRef` to a `TicketCandidate` (its node id,
and whether it is a same-repo spec) themselves; this module holds no I/O.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# A `Ticket: <url>` field, GitHub issue URLs only (`.../owner/repo/issues/N`).
_TICKET_FIELD_RE = re.compile(r"^\s*Ticket:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_ISSUE_URL_RE = re.compile(r"github\.com/([\w.-]+)/([\w.-]+)/issues/(\d+)")

# GitHub's own closing-keyword vocabulary, followed by an optional
# `owner/repo` (cross-repo/full form) and the mandatory `#N`.
_CLOSING_KEYWORDS = r"close[sd]?|fix(?:e[sd])?|resolve[sd]?"
_CLOSING_REF_RE = re.compile(
    rf"\b(?:{_CLOSING_KEYWORDS})\b\s*:?\s*(?:([\w.-]+/[\w.-]+)#|#)(\d+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TicketRef:
    """One ticket a PR body references: `owner/repo#number`."""

    owner: str
    repo: str
    number: int

    @property
    def repo_full_name(self) -> str:
        return f"{self.owner}/{self.repo}"


@dataclass(frozen=True)
class TicketCandidate:
    """A parsed `TicketRef`, resolved by the caller to its issue node id.

    `is_same_repo_spec` is true when the referenced issue lives in the same
    repo as the PR being scanned *and* carries the `wayfinder:spec` label —
    the one fact the tie-break needs; nothing else about the issue matters
    here.
    """

    ref: TicketRef
    node_id: str
    is_same_repo_spec: bool


def parse_ticket_field(body: str | None) -> TicketRef | None:
    """The `Ticket: <url>` field's target, or `None` if absent/unparseable."""

    match = _TICKET_FIELD_RE.search(body or "")
    if match is None:
        return None
    url_match = _ISSUE_URL_RE.search(match.group(1))
    if url_match is None:
        return None
    owner, repo, number = url_match.groups()
    return TicketRef(owner=owner, repo=repo, number=int(number))


def parse_closing_refs(
    body: str | None, *, default_owner: str, default_repo: str
) -> list[TicketRef]:
    """Every closing-keyword ticket reference in `body`, in first-seen order.

    A bare `#N` resolves against `default_owner`/`default_repo` (the repo the
    PR itself lives in); an explicit `owner/repo#N` is used as written.
    Duplicates collapse to their first occurrence.
    """

    refs: list[TicketRef] = []
    seen: set[TicketRef] = set()
    for match in _CLOSING_REF_RE.finditer(body or ""):
        owner_repo, number = match.groups()
        if owner_repo:
            owner, repo = owner_repo.split("/", 1)
        else:
            owner, repo = default_owner, default_repo
        ref = TicketRef(owner=owner, repo=repo, number=int(number))
        if ref not in seen:
            seen.add(ref)
            refs.append(ref)
    return refs


def parse_candidate_refs(
    body: str | None, *, default_owner: str, default_repo: str
) -> list[TicketRef]:
    """The PR body's candidate `TicketRef`s: the `Ticket:` field if present,
    else every closing-keyword reference (see module docstring)."""

    ticket_field = parse_ticket_field(body)
    if ticket_field is not None:
        return [ticket_field]
    return parse_closing_refs(body, default_owner=default_owner, default_repo=default_repo)


def pick_link_target(
    candidates: Sequence[TicketCandidate],
) -> TicketCandidate | None:
    """The one ticket this PR should link to, or `None` when it's ambiguous.

    A same-repo `wayfinder:spec` candidate always wins (a spec-branch PR
    links the spec, never its impl tickets) — but more than one such
    candidate on the same PR is itself a defect, not a tie to break, so that
    also returns `None`. Absent a spec candidate, exactly one candidate is
    unambiguous; zero or more than one both return `None`: nothing to link,
    or a defect to surface rather than guess at.
    """

    specs = [candidate for candidate in candidates if candidate.is_same_repo_spec]
    if specs:
        return specs[0] if len(specs) == 1 else None
    return candidates[0] if len(candidates) == 1 else None
