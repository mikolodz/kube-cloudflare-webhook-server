import os, time, requests
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from jose import jwt

TEAM_DOMAIN = os.environ["CF_TEAM_DOMAIN"]  # e.g., https://your-team.cloudflareaccess.com
EXPECTED_ISS = TEAM_DOMAIN.rstrip("/")
EXPECTED_AUD = os.environ["CF_APP_AUD"]     # Cloudflare Access app AUD
JWKS_URL = f"{EXPECTED_ISS}/cdn-cgi/access/certs"
JWKS_CACHE_TTL = 300

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

def verify(token: str):
  jwks = get_jwks()
  headers = jwt.get_unverified_header(token)
  kid = headers.get("kid")
  key = next((k for k in jwks["keys"] if k.get("kid") == kid), None)
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
    username = claims.get("email") or claims.get("sub") or "unknown"
    groups = claims.get("groups") or []
    return JSONResponse({
      "apiVersion": "authentication.k8s.io/v1",
      "kind": "TokenReview",
      "status": {"authenticated": True, "user": {"username": username, "groups": groups}}
    })
  except Exception:
    return JSONResponse({
      "apiVersion": "authentication.k8s.io/v1",
      "kind": "TokenReview",
      "status": {"authenticated": False}
    })