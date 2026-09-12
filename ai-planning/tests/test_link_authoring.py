"""Unit tests for the shared, pure link-authoring rule."""

from ai_planning.link_authoring import (
    TicketCandidate,
    TicketRef,
    parse_candidate_refs,
    parse_closing_refs,
    parse_ticket_field,
    pick_link_target,
)


def _candidate(owner, repo, number, *, node_id="I_x", is_same_repo_spec=False):
    return TicketCandidate(
        ref=TicketRef(owner=owner, repo=repo, number=number),
        node_id=node_id,
        is_same_repo_spec=is_same_repo_spec,
    )


# -- parse_ticket_field -------------------------------------------------


def test_ticket_field_parses_a_github_issue_url():
    body = "Some description.\n\nTicket: https://github.com/acme/planning/issues/42\n"
    assert parse_ticket_field(body) == TicketRef("acme", "planning", 42)


def test_ticket_field_absent_returns_none():
    assert parse_ticket_field("Just closes #3, no field.") is None


def test_ticket_field_unparseable_url_returns_none():
    assert parse_ticket_field("Ticket: not-a-url") is None


# -- parse_closing_refs --------------------------------------------------


def test_closing_ref_bare_number_defaults_to_pr_repo():
    refs = parse_closing_refs(
        "Closes #12", default_owner="acme", default_repo="code"
    )
    assert refs == [TicketRef("acme", "code", 12)]


def test_closing_ref_cross_repo_form():
    refs = parse_closing_refs(
        "Fixes acme/planning#7", default_owner="acme", default_repo="code"
    )
    assert refs == [TicketRef("acme", "planning", 7)]


def test_closing_ref_recognises_every_keyword_variant():
    body = "close #1, closes #2, closed #3, fix #4, fixes #5, fixed #6, " \
        "resolve #7, resolves #8, resolved #9"
    refs = parse_closing_refs(body, default_owner="acme", default_repo="code")
    assert [ref.number for ref in refs] == [1, 2, 3, 4, 5, 6, 7, 8, 9]


def test_closing_ref_ignores_mere_mentions():
    refs = parse_closing_refs(
        "See #5 for context, unrelated to this PR.",
        default_owner="acme",
        default_repo="code",
    )
    assert refs == []


def test_closing_ref_deduplicates_preserving_first_seen_order():
    refs = parse_closing_refs(
        "Closes #1. Also fixes #1 and closes #2.",
        default_owner="acme",
        default_repo="code",
    )
    assert refs == [TicketRef("acme", "code", 1), TicketRef("acme", "code", 2)]


# -- parse_candidate_refs -------------------------------------------------


def test_candidate_refs_prefers_ticket_field_over_closing_keywords():
    body = (
        "Closes #99\n\nTicket: https://github.com/acme/planning/issues/1\n"
    )
    refs = parse_candidate_refs(body, default_owner="acme", default_repo="code")
    assert refs == [TicketRef("acme", "planning", 1)]


def test_candidate_refs_falls_back_to_closing_keywords():
    refs = parse_candidate_refs(
        "Fixes #4", default_owner="acme", default_repo="code"
    )
    assert refs == [TicketRef("acme", "code", 4)]


# -- pick_link_target -----------------------------------------------------


def test_pick_target_no_candidates_is_none():
    assert pick_link_target([]) is None


def test_pick_target_single_impl_candidate_wins():
    candidate = _candidate("acme", "planning", 5)
    assert pick_link_target([candidate]) is candidate


def test_pick_target_multiple_impl_candidates_is_ambiguous():
    candidates = [_candidate("acme", "planning", 5), _candidate("acme", "planning", 6)]
    assert pick_link_target(candidates) is None


def test_pick_target_spec_outranks_impl_ticket():
    spec = _candidate("acme", "code", 1, is_same_repo_spec=True)
    impl = _candidate("acme", "planning", 5)
    assert pick_link_target([impl, spec]) is spec


def test_pick_target_multiple_spec_candidates_is_ambiguous():
    specs = [
        _candidate("acme", "code", 1, is_same_repo_spec=True),
        _candidate("acme", "code", 2, is_same_repo_spec=True),
    ]
    assert pick_link_target(specs) is None
