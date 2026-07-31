"""Small single-tenant bearer authentication boundary for the API."""

from __future__ import annotations

from dataclasses import dataclass
import hmac

from fastapi import HTTPException, Request


@dataclass(frozen=True)
class Principal:
    """Authenticated API caller in the explicitly single-owner deployment model."""

    subject: str
    owner_id: str
    authenticated: bool


class BearerAuthenticator:
    """Authenticate one configured owner token without accepting caller identity."""

    def __init__(self, *, token: str | None, owner_id: str) -> None:
        configured = token.strip() if token is not None else ""
        self._token = configured or None
        self.owner_id = owner_id.strip()
        if not self.owner_id:
            raise ValueError("owner_id must not be empty")

    @property
    def enabled(self) -> bool:
        return self._token is not None

    def authenticate(self, request: Request) -> Principal:
        """Return the configured owner or reject missing/invalid credentials."""

        if self._token is None:
            return Principal(
                subject="offline-demo",
                owner_id=self.owner_id,
                authenticated=False,
            )

        authorization = request.headers.get("authorization", "")
        scheme, separator, credential = authorization.partition(" ")
        if (
            not separator
            or scheme.lower() != "bearer"
            or not credential
            or not hmac.compare_digest(credential, self._token)
        ):
            raise HTTPException(
                status_code=401,
                detail="valid bearer authentication is required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return Principal(
            subject=f"owner:{self.owner_id}",
            owner_id=self.owner_id,
            authenticated=True,
        )


def principal_from_request(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if not isinstance(principal, Principal):
        raise HTTPException(status_code=401, detail="authentication context is missing")
    return principal
