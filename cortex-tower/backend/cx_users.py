"""Identity (appster core-builder HARD RULE 0): KOGO SSO + manual login, and the tower roles guardrails use.

Identity is the *verified* caller the platform puts in the environment (``USER_EMAIL`` when
``KOGO_AUTH_VERIFIED == "1"``). It is NEVER read from request parameters — the old ``actor`` parameter of the
action functions is ignored by the guarded pipeline for exactly that reason.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta

import config
import guardrails
from models_cx import SessionModel, UserModel

SESSION_DAYS = 7


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${dk.hex()}"


def _check_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(_hash_password(password, salt), stored)


def _session_user(db, token):
    if not token:
        return None
    th = hashlib.sha256(token.encode()).hexdigest()
    row = db.query(SessionModel).filter(SessionModel.token_hash == th).first()
    if not row:
        return None
    if row.expires_at < datetime.utcnow():
        db.delete(row)
        db.commit()
        return None
    return db.query(UserModel).filter(UserModel.id == row.user_id).first()


def _resolve_or_bootstrap(db, email: str, name: str):
    user = db.query(UserModel).filter(UserModel.email == email).first()
    if user:
        return user
    if db.query(UserModel).count() == 0:         # an empty app + a verified caller = that caller owns it (fires once)
        user = UserModel(email=email, name=name, role="admin", is_admin=True, tower_roles=json.dumps(["Admin"]))
        db.add(user)
        db.commit()
        return user
    return None


def current_user(db, **kwargs):
    """The caller as a row of THIS app, or None (anonymous / not registered)."""
    if config.sso_present():
        ident = config.verified_identity()
        if ident:
            return _resolve_or_bootstrap(db, ident["email"], ident["name"])
        return None
    return _session_user(db, kwargs.get("_app_token"))


def roles_of(user) -> list[str]:
    try:
        roles = json.loads(user.tower_roles or "[]")
    except Exception:
        roles = []
    if user.is_admin and "Admin" not in roles:
        roles.append("Admin")
    return [r for r in roles if r in guardrails.ROLES]


def principal(user) -> dict:
    return {"email": user.email, "name": user.name, "roles": roles_of(user), "is_admin": bool(user.is_admin),
            "erp_user": user.erp_user or ""}


def require(db, **kwargs) -> dict:
    """The gate every guarded function starts with. Raises PermissionError with a sentence the UI can show."""
    u = current_user(db, **kwargs)
    if not u:
        raise PermissionError("Sign in to use this.")
    if not u.active:
        raise PermissionError("Your account is switched off. Ask an administrator.")
    return principal(u)


def kogo_me(db, **kwargs):
    if not config.sso_present() and not _session_user(db, kwargs.get("_app_token")):
        return {"authenticated": False, "registered": False, "reason": "no_session"}
    u = current_user(db, **kwargs)
    if not u:
        return {"authenticated": True, "registered": False, "reason": "not_registered", "email": config.verified_identity().get("email", "")}
    return {"authenticated": True, "registered": True, "email": u.email, "name": u.name, "role": u.role,
            "is_admin": bool(u.is_admin), "tower_roles": roles_of(u), "erp_user": u.erp_user or "",
            "via": "kogo" if config.sso_present() else "password",
            "can_login_directly": bool(u.password_hash)}


def kogo_register_users(db, users=None, **kwargs):
    count = 0
    for u in (users or []):
        try:
            email = (u.get("email") or "").strip().lower()
            if not email:
                continue
            row = db.query(UserModel).filter(UserModel.email == email).first()
            if row:
                row.name = u.get("name") or row.name
                if u.get("is_admin"):
                    row.is_admin, row.role = True, u.get("role") or "admin"
            else:
                db.add(UserModel(email=email, name=u.get("name") or email,
                                 role=u.get("role") or ("admin" if u.get("is_admin") else "member"),
                                 is_admin=bool(u.get("is_admin")),
                                 tower_roles=json.dumps(["Admin"] if u.get("is_admin") else [])))
            db.commit()
            count += 1
        except Exception:
            db.rollback()
    return {"ok": True, "count": count, "default_role": "member"}


def kogo_login(db, email=None, password=None, **kwargs):
    user = db.query(UserModel).filter(UserModel.email == (email or "").strip().lower()).first()
    if not user or not user.active or not _check_password(password or "", user.password_hash):
        return {"error": "Incorrect email or password"}
    token = secrets.token_urlsafe(32)
    db.add(SessionModel(token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
                        expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS)))
    db.commit()
    return {"ok": True, "token": token, "name": user.name, "role": user.role, "is_admin": bool(user.is_admin)}


def kogo_logout(db, **kwargs):
    token = kwargs.get("_app_token")
    if token:
        row = db.query(SessionModel).filter(SessionModel.token_hash == hashlib.sha256(token.encode()).hexdigest()).first()
        if row:
            db.delete(row)
            db.commit()
    return {"ok": True}


def kogo_set_password(db, new_password=None, **kwargs):
    u = current_user(db, **kwargs)
    if not u:
        return {"error": "Sign in first"}
    if len(new_password or "") < 10:
        return {"error": "Use at least 10 characters"}
    u.password_hash = _hash_password(new_password)
    db.commit()
    return {"ok": True}


def kogo_admin_set_password(db, email=None, new_password=None, **kwargs):
    me = require(db, **kwargs)
    if not me["is_admin"]:
        return {"error": "Only an administrator can set someone else's password"}
    if len(new_password or "") < 10:
        return {"error": "Use at least 10 characters"}
    u = db.query(UserModel).filter(UserModel.email == (email or "").strip().lower()).first()
    if not u:
        return {"error": "No such user"}
    u.password_hash = _hash_password(new_password)
    db.commit()
    return {"ok": True}


def list_tower_users(db, **kwargs):
    me = require(db, **kwargs)
    if not me["is_admin"]:
        return {"error": "Administrators only"}
    return {"users": [{"email": u.email, "name": u.name, "is_admin": bool(u.is_admin), "roles": roles_of(u),
                       "erp_user": u.erp_user or "", "active": bool(u.active)} for u in db.query(UserModel).order_by(UserModel.email)],
            "all_roles": guardrails.ROLES}


def set_tower_user(db, email=None, roles=None, erp_user=None, active=None, **kwargs):
    me = require(db, **kwargs)
    if not me["is_admin"]:
        return {"error": "Administrators only"}
    u = db.query(UserModel).filter(UserModel.email == (email or "").strip().lower()).first()
    if not u:
        return {"error": "No such user"}
    if roles is not None:
        bad = [r for r in roles if r not in guardrails.ROLES]
        if bad:
            return {"error": f"Unknown role(s): {', '.join(bad)}"}
        if u.email == me["email"] and "Admin" not in roles and u.is_admin:
            return {"error": "You cannot remove your own Admin role"}
        u.tower_roles = json.dumps(roles)
    if erp_user is not None:
        u.erp_user = erp_user
    if active is not None:
        if u.email == me["email"] and not active:
            return {"error": "You cannot switch yourself off"}
        u.active = bool(active)
    db.commit()
    return {"ok": True}
