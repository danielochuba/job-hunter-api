"""Verify the Supabase access token sent by the web app as `Authorization: Bearer <jwt>`.

New Supabase projects sign tokens with asymmetric keys (verified via the project's JWKS);
legacy projects use the shared HS256 secret (SUPABASE_JWT_SECRET)."""
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ...application import profile
from ...domain.errors import Forbidden, Unauthorized
from .deps import get_ctx

bearer = HTTPBearer(auto_error=False)


class TokenVerifier:
    def __init__(self, supabase_url, jwt_secret="", allowed_email=""):
        self.jwks_url = supabase_url.rstrip("/") + "/auth/v1/.well-known/jwks.json" if supabase_url else None
        self.jwt_secret = jwt_secret
        self.allowed_email = (allowed_email or "").lower()
        self._jwks = None
        self.known_users: set[str] = set()

    def _jwks_client(self):
        if self._jwks is None:
            if not self.jwks_url:
                raise Unauthorized("SUPABASE_URL is not configured")
            self._jwks = jwt.PyJWKClient(self.jwks_url, cache_keys=True, lifespan=3600)
        return self._jwks

    def decode(self, token):
        try:
            alg = jwt.get_unverified_header(token).get("alg")
            if alg == "HS256":
                if not self.jwt_secret:
                    raise Unauthorized("HS256 token but SUPABASE_JWT_SECRET is not set")
                return jwt.decode(token, self.jwt_secret, algorithms=["HS256"], audience="authenticated")
            key = self._jwks_client().get_signing_key_from_jwt(token).key
            return jwt.decode(token, key, algorithms=["RS256", "ES256", "EdDSA"], audience="authenticated")
        except jwt.PyJWTError as e:
            raise Unauthorized(f"Invalid token: {e}") from e

    def check_email(self, email):
        if self.allowed_email and (email or "").lower() != self.allowed_email:
            raise Forbidden("This account is not allowed to use JobHunter")


def current_user(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer),
                 ctx=Depends(get_ctx)):
    if not creds or creds.scheme.lower() != "bearer":
        raise Unauthorized("Missing bearer token")
    verifier: TokenVerifier = request.app.state.verifier
    claims = verifier.decode(creds.credentials)
    email = claims.get("email") or ""
    verifier.check_email(email)
    uid = claims["sub"]
    if uid not in verifier.known_users:
        profile.ensure_user(ctx, uid, email)
        verifier.known_users.add(uid)
    return {"id": uid, "email": email}
