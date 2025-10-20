import os, time, requests, logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jose import jwt

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("cf-access-authn")

TEAM = os.environ["CF_TEAM_DOMAIN"].strip()
EXPECTED_ISS = TEAM.rstrip("/") if TEAM.startswith("http") else f"https://{TEAM}".rstrip("/")
EXPECTED_AUD = os.environ["CF_APP_AUD"]
JWKS_URL = f"{EXPECTED_ISS}/cdn-cgi/access/certs"
JWKS_CACHE_TTL = 300

USERNAME_CLAIMS = [c.strip() for c in os.getenv("USERNAME_CLAIMS", "email,common_name,sub").split(",") if c.strip()]

app = FastAPI()
_jwks_cache = {"keys": None, "ts": 0}

def get_jwks():
    now = time.time()
    if not _jwks_cache["keys"] or now - _jwks_cache["ts"] > JWKS_CACHE_TTL:
        resp = requests.get(JWKS_URL, timeout=5)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["ts"] = now
    return _jwks_cache["keys"]

def choose_username(claims: dict) -> str:
    for key in USERNAME_CLAIMS:
        val = claims.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "unknown"

def verify(token: str) -> dict:
    jwks = get_jwks()
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    key = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if not key:
        raise ValueError("Unknown kid")
    claims = jwt.decode(token, key, algorithms=["RS256"], audience=EXPECTED_AUD, issuer=EXPECTED_ISS)
    return claims

@app.post("/")
async def token_review(req: Request):
    body = await req.json()
    token = (body.get("spec") or {}).get("token") or ""
    try:
        claims = verify(token)
        username = choose_username(claims)
        groups = claims.get("groups") or []
        log.debug("claims=%s username=%s", claims, username)
        return JSONResponse({
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenReview",
            "status": {"authenticated": True, "user": {"username": username, "groups": groups}},
        })
    except Exception as e:
        log.debug("auth_failed error=%s", e)
        return JSONResponse({
            "apiVersion": "authentication.k8s.io/v1",
            "kind": "TokenReview",
            "status": {"authenticated": False},
        })