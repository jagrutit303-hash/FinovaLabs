"""Authentication and Role-Based Access Control (RBAC) for FinovaLabs API."""

from __future__ import annotations

import os
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

Role = Literal["viewer", "analyst", "admin"]

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_auth = HTTPBearer(auto_error=False)


class AuthUser(BaseModel):
    """Authenticated user context containing identity and assigned role."""

    user_id: str
    username: str
    role: Role


def _resolve_role_from_token(token: str) -> tuple[str, Role] | None:
    """Resolve user identity and role from token or API key."""
    # Configurable token mapping via environment variables
    admin_token = os.getenv("FINOVALABS_ADMIN_TOKEN", "fl-admin-secret-key")
    analyst_token = os.getenv("FINOVALABS_ANALYST_TOKEN", "fl-analyst-secret-key")
    viewer_token = os.getenv("FINOVALABS_VIEWER_TOKEN", "fl-viewer-secret-key")

    clean = token.strip()
    if clean == admin_token:
        return "admin.lead", "admin"
    if clean == analyst_token:
        return "analyst.primary", "analyst"
    if clean == viewer_token:
        return "auditor.external", "viewer"

    # Default fallback key check
    master_key = os.getenv("FINOVALABS_API_KEY")
    if master_key and clean == master_key:
        return "analyst.primary", "analyst"

    return None


async def get_current_user(
    api_key: str | None = Security(api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Security(bearer_auth),
) -> AuthUser:
    """Extract and validate user credentials from headers."""
    require_auth = os.getenv("FINOVALABS_REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")
    token = (bearer.credentials if bearer else None) or api_key

    if not token:
        if require_auth:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication credentials were not provided. Pass X-API-Key or Bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Development mode default context
        return AuthUser(user_id="dev-analyst", username="analyst.lead", role="analyst")

    resolved = _resolve_role_from_token(token)
    if not resolved:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token or API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id, role = resolved
    return AuthUser(user_id=user_id, username=user_id, role=role)


def require_role(allowed_roles: list[Role]):
    """Dependency enforcing that the authenticated user possesses one of the allowed roles."""

    def _role_checker(user: Annotated[AuthUser, Depends(get_current_user)]) -> AuthUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: action requires one of {allowed_roles}, but your role is '{user.role}'.",
            )
        return user

    return _role_checker

