"""A minimal GitHub GraphQL client, stdlib-only and injectable.

The client is a thin transport: it POSTs a query + variables and returns the
`data` object, raising on transport or GraphQL errors. It carries no board logic.
The `transport` seam (a callable `payload -> response dict`) lets the job run
against a fake in tests with no network; the default transport hits the live
GitHub GraphQL endpoint with a bearer token.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Protocol

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

Transport = Callable[[dict[str, Any]], dict[str, Any]]


class GraphQLError(RuntimeError):
    """Raised when a GraphQL response carries an `errors` array."""


class SupportsExecute(Protocol):
    def execute(
        self, query: str, variables: dict[str, Any]
    ) -> dict[str, Any]: ...


def _urllib_transport(token: str, url: str) -> Transport:
    def send(payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/vnd.github+json",
                "User-Agent": "ai-planning",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:  # fixed host: api.github.com
            return json.loads(response.read().decode("utf-8"))

    return send


class GraphQLClient:
    """Sends GraphQL documents and returns the `data` payload."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    @classmethod
    def with_token(
        cls, token: str, *, url: str = GITHUB_GRAPHQL_URL
    ) -> "GraphQLClient":
        """Build a client that authenticates to GitHub with `token`."""

        return cls(_urllib_transport(token, url))

    def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        response = self._transport({"query": query, "variables": variables})
        errors = response.get("errors")
        if errors:
            raise GraphQLError(json.dumps(errors))
        return response.get("data") or {}
