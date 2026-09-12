"""Orchestration tests for the link-authoring reconcile + immediate arms,
driven by a fake GraphQL client (no network, no dependence on GitHub's live
schema)."""

from ai_planning.link_authoring import TicketRef
from ai_planning.link_authoring_job import (
    DispatchedPR,
    author_dispatched_pr_link,
    author_missing_links,
    dispatched_pr_from_payload,
)
from ai_planning.queries import (
    ADD_CLOSE_ISSUE_REFERENCES_MUTATION,
    ISSUE_BY_NUMBER_QUERY,
    PR_BY_NUMBER_QUERY,
    REPO_PRS_QUERY,
)


def _pr(number, *, body, closing_refs=()):
    return {
        "id": f"PR_{number}",
        "number": number,
        "body": body,
        "baseRefName": "main",
        "closingIssuesReferences": {
            "nodes": [
                {
                    "number": ref_number,
                    "repository": {"owner": {"login": owner}, "name": repo},
                }
                for owner, repo, ref_number in closing_refs
            ]
        },
    }


class FakeClient:
    """Serves one repo's PR page(s) and canned issue lookups; records writes."""

    def __init__(self, prs_by_repo, issues_by_ref, prs_by_number=None):
        self._prs_by_repo = prs_by_repo
        self._issues_by_ref = issues_by_ref
        self._prs_by_number = prs_by_number or {}
        self.authored = []

    def execute(self, query, variables):
        if query == REPO_PRS_QUERY:
            key = (variables["owner"], variables["name"])
            return {
                "repository": {
                    "pullRequests": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": self._prs_by_repo.get(key, []),
                    }
                }
            }
        if query == ISSUE_BY_NUMBER_QUERY:
            key = (variables["owner"], variables["name"], variables["number"])
            issue = self._issues_by_ref.get(key)
            return {"repository": {"issue": issue}}
        if query == PR_BY_NUMBER_QUERY:
            key = (variables["owner"], variables["name"], variables["number"])
            pr = self._prs_by_number.get(key)
            return {"repository": {"pullRequest": pr}}
        if query == ADD_CLOSE_ISSUE_REFERENCES_MUTATION:
            self.authored.append((variables["issueId"], variables["pullRequestId"]))
            return {"addCloseIssueReferences": {"issue": {"id": variables["issueId"]}}}
        raise AssertionError(f"unexpected query: {query!r}")


def _issue(node_id, *, labels=()):
    return {"id": node_id, "labels": {"nodes": [{"name": name} for name in labels]}}


def test_authors_the_single_unambiguous_impl_ticket_link():
    prs = {("acme", "code"): [_pr(10, body="Fixes acme/planning#7")]}
    issues = {("acme", "planning", 7): _issue("I_7")}
    client = FakeClient(prs, issues)

    result = author_missing_links(client, ["acme/code"])

    assert client.authored == [("I_7", "PR_10")]
    assert result.authored == [("acme/code#10", TicketRef("acme", "planning", 7))]


def test_skips_a_pr_already_carrying_its_deliberate_link():
    prs = {
        ("acme", "code"): [
            _pr(11, body="Fixes acme/planning#7", closing_refs=[("acme", "planning", 7)])
        ]
    }
    issues = {("acme", "planning", 7): _issue("I_7")}
    client = FakeClient(prs, issues)

    result = author_missing_links(client, ["acme/code"])

    assert client.authored == []
    assert result.unchanged == ["acme/code#11"]


def test_ambiguous_multi_impl_candidates_authors_nothing():
    prs = {
        ("acme", "code"): [
            _pr(12, body="Fixes acme/planning#7, fixes acme/planning#8")
        ]
    }
    issues = {
        ("acme", "planning", 7): _issue("I_7"),
        ("acme", "planning", 8): _issue("I_8"),
    }
    client = FakeClient(prs, issues)

    result = author_missing_links(client, ["acme/code"])

    assert client.authored == []
    assert result.ambiguous == ["acme/code#12"]


def test_spec_beats_impl_ticket_on_the_same_pr():
    prs = {
        ("acme", "code"): [
            _pr(13, body="Fixes #1, fixes acme/planning#7")
        ]
    }
    issues = {
        ("acme", "code", 1): _issue("I_spec", labels=["wayfinder:spec"]),
        ("acme", "planning", 7): _issue("I_7"),
    }
    client = FakeClient(prs, issues)

    result = author_missing_links(client, ["acme/code"])

    assert client.authored == [("I_spec", "PR_13")]


def test_no_candidate_refs_in_body_authors_nothing():
    prs = {("acme", "code"): [_pr(14, body="No ticket reference here.")]}
    client = FakeClient(prs, issues_by_ref={})

    result = author_missing_links(client, ["acme/code"])

    assert client.authored == []
    assert result.no_candidates == ["acme/code#14"]


def test_unresolvable_candidate_issue_is_dropped_not_raised():
    prs = {("acme", "code"): [_pr(15, body="Fixes acme/planning#999")]}
    client = FakeClient(prs, issues_by_ref={("acme", "planning", 999): None})

    result = author_missing_links(client, ["acme/code"])

    assert client.authored == []
    assert result.ambiguous == ["acme/code#15"]


# -- dispatched_pr_from_payload --------------------------------------------


def test_dispatched_pr_from_payload_parses_the_client_payload():
    payload = {
        "repository": {"owner": "acme", "name": "code"},
        "number": 20,
        "body": "Fixes acme/planning#7",
        "baseRefName": "main",
        "state": "open",
        "isDraft": False,
        "merged": False,
    }

    pr = dispatched_pr_from_payload(payload)

    assert pr == DispatchedPR(owner="acme", name="code", number=20, body="Fixes acme/planning#7")


# -- author_dispatched_pr_link (the immediate arm, ticket 35) ---------------


def test_immediate_arm_authors_the_single_unambiguous_link():
    issues = {("acme", "planning", 7): _issue("I_7")}
    prs_by_number = {("acme", "code", 20): _pr(20, body="Fixes acme/planning#7")}
    client = FakeClient({}, issues, prs_by_number)
    pr = DispatchedPR(owner="acme", name="code", number=20, body="Fixes acme/planning#7")

    ref = author_dispatched_pr_link(client, pr)

    assert ref == TicketRef("acme", "planning", 7)
    assert client.authored == [("I_7", "PR_20")]


def test_immediate_arm_skips_a_pr_already_carrying_its_link():
    issues = {("acme", "planning", 7): _issue("I_7")}
    prs_by_number = {
        ("acme", "code", 21): _pr(
            21, body="Fixes acme/planning#7", closing_refs=[("acme", "planning", 7)]
        )
    }
    client = FakeClient({}, issues, prs_by_number)
    pr = DispatchedPR(owner="acme", name="code", number=21, body="Fixes acme/planning#7")

    ref = author_dispatched_pr_link(client, pr)

    assert ref is None
    assert client.authored == []


def test_immediate_arm_ambiguous_candidates_authors_nothing():
    issues = {
        ("acme", "planning", 7): _issue("I_7"),
        ("acme", "planning", 8): _issue("I_8"),
    }
    client = FakeClient({}, issues, prs_by_number={})
    pr = DispatchedPR(
        owner="acme",
        name="code",
        number=22,
        body="Fixes acme/planning#7, fixes acme/planning#8",
    )

    ref = author_dispatched_pr_link(client, pr)

    assert ref is None
    assert client.authored == []


def test_immediate_arm_no_candidate_refs_authors_nothing():
    client = FakeClient({}, issues_by_ref={}, prs_by_number={})
    pr = DispatchedPR(owner="acme", name="code", number=23, body="No ticket reference here.")

    ref = author_dispatched_pr_link(client, pr)

    assert ref is None
    assert client.authored == []
