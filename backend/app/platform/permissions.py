"""Who may do what: the operator roles, the permissions they carry, and the one decision every check goes through.

Roles and their permissions live here, reviewed and released with the code, so who can move money can be read from
this file. A person may hold several roles; a customer holds none. Holding a role buys no paid features, and paying
buys no role: what a customer bought is decided separately, from their membership.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from app.core import prompt_data


_WORDING_FILE = "platform_permissions"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/platform_permissions.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

ROLE_ASSIGN = "role:assign"
USER_READ = "user:read"
USER_MANAGE = "user:manage"
MODEL_CONFIG_MANAGE = "model_config:manage"
SKILL_MANAGE = "skill:manage"
MARKET_MANAGE = "market:manage"
CAPABILITY_MANAGE = "capability:manage"
PROJECT_READ_ANY = "project:read_any"
PROJECT_WRITE_ANY = "project:write_any"
PRICING_MANAGE = "pricing:manage"
ORDER_READ_ANY = "order:read_any"
REFUND_REQUEST = "refund:request"
REFUND_APPROVE = "refund:approve"
WALLET_ADJUST_REQUEST = "wallet:adjust_request"
WALLET_ADJUST_APPROVE = "wallet:adjust_approve"
RECON_READ = "recon:read"
RECON_RESOLVE = "recon:resolve"
PAYMENT_CONFIGURE = "payment:configure"
AUDIT_READ = "audit:read"

ALL_PERMISSIONS = frozenset({
    ROLE_ASSIGN, USER_READ, USER_MANAGE, MODEL_CONFIG_MANAGE, SKILL_MANAGE, MARKET_MANAGE, CAPABILITY_MANAGE,
    PROJECT_READ_ANY, PROJECT_WRITE_ANY, PRICING_MANAGE, ORDER_READ_ANY, REFUND_REQUEST, REFUND_APPROVE,
    WALLET_ADJUST_REQUEST, WALLET_ADJUST_APPROVE, RECON_READ, RECON_RESOLVE, PAYMENT_CONFIGURE, AUDIT_READ,
})

SUPER_ADMIN = "super_admin"

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    SUPER_ADMIN: ALL_PERMISSIONS,
    "ops": frozenset({
        MODEL_CONFIG_MANAGE, SKILL_MANAGE, MARKET_MANAGE, CAPABILITY_MANAGE, PROJECT_READ_ANY, PROJECT_WRITE_ANY,
    }),
    "finance": frozenset({
        USER_READ, PRICING_MANAGE, ORDER_READ_ANY, REFUND_REQUEST, REFUND_APPROVE, WALLET_ADJUST_REQUEST,
        WALLET_ADJUST_APPROVE, RECON_READ, RECON_RESOLVE, AUDIT_READ,
    }),
    "support": frozenset({
        USER_READ, USER_MANAGE, PROJECT_READ_ANY, ORDER_READ_ANY, REFUND_REQUEST, WALLET_ADJUST_REQUEST,
    }),
    "auditor": frozenset({USER_READ, PROJECT_READ_ANY, ORDER_READ_ANY, RECON_READ, AUDIT_READ}),
}

ROLE_LABELS = {
    SUPER_ADMIN: _words_of("module.role_labels"),
    "ops": _words_of("module.role_labels.ops"),
    "finance": _words_of("module.role_labels.finance"),
    "support": _words_of("module.role_labels.support"),
    "auditor": _words_of("module.role_labels.auditor"),
}


def permissions_for(roles: Iterable[str]) -> frozenset[str]:
    granted: set[str] = set()
    for role in roles:
        granted |= ROLE_PERMISSIONS.get(role, frozenset())
    return frozenset(granted)


def legacy_role(roles: Iterable[str]) -> str:
    """What the old ``role`` field says, for whatever still reads it and for rolling back."""
    return "admin" if SUPER_ADMIN in roles else "user"


def permissions_of(actor: Mapping[str, Any]) -> frozenset[str]:
    """An actor from a login carries its permissions. A dict built by hand with only ``role`` is read the old way."""
    if "permissions" in actor:
        return frozenset(actor.get("permissions") or ())
    return ALL_PERMISSIONS if actor.get("role") == "admin" else frozenset()


def has_permission(actor: Mapping[str, Any], permission: str) -> bool:
    return permission in permissions_of(actor)


@dataclass(frozen=True)
class Decision:
    allowed: bool
    status: int = 200
    reason: str = ""
    detail: str = ""
    #: Allowed because of a role, on something that belongs to someone else: this gets audited.
    cross_account: bool = False


def _deny(status: int, reason: str, detail: str) -> Decision:
    return Decision(False, status, reason, detail)


def authorize(
    actor: Mapping[str, Any], *, permission: str | None = None, owner_id: str | None = None, write: bool = False,
) -> Decision:
    """The one decision: account, then the operation's permission, then whose resource it is.

    ``owner_id`` is given when the request is about something owned; pass "" when it has no owner on record, which
    only an operator may touch. Not owning something answers 404, so the answer never shows that it exists.
    """
    if actor.get("status", "active") != "active":
        return _deny(401, "account_suspended", _text_of("authorize.text"))
    has_changed_password = not actor.get("must_change_password")
    if permission is not None:
        if not has_permission(actor, permission):
            return _deny(403, "permission_denied", _text_of("authorize.text.2"))
        if not has_changed_password:
            return _deny(403, "must_change_password", _text_of("authorize.text.3"))
    if owner_id is None:
        return Decision(True)
    user_id = str(actor.get("user_id") or "")
    if user_id and owner_id == user_id:
        return Decision(True)
    needed = PROJECT_WRITE_ANY if write else PROJECT_READ_ANY
    if has_permission(actor, needed) and has_changed_password:
        return Decision(True, cross_account=True)
    return _deny(404, "not_found", _text_of("authorize.text.4"))
