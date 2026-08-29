# OPB WEB CLOSURE WIP47 — SSO URL Semantic Evidence

This pass inspects the concrete implementation of authorization URL generation, callback handling, the SSO route, and the canonical public URL resolver. No source mutation was performed.

## `get_authorization_url()`

```text
184:     def get_authorization_url(self, state: str | None = None) -> str | None:
185:         """Generate the OAuth2 authorization URL for the configured provider.
186: 
187:         Args:
188:             state: Optional OAuth2 state parameter (auto-generated if None).
189: 
190:         Returns:
191:             The full authorization URL, or None if authlib is not installed
192:             or configuration is incomplete.
193: 
194:         """
195:         if not self.is_available:
196:             _log.warning("[SSO] authlib not installed -- cannot generate auth URL")
197:             return None
198:         if not self._config.client_id or not self._config.redirect_uri:
199:             _log.warning("[SSO] SSO not configured: missing client_id or redirect_uri")
200:             return None
201: 
202:         state = state or secrets.token_urlsafe(32)
203:         with self._lock:
204:             self._state_store[state] = time.time() + self._state_ttl
205: 
206:         try:
207:             from authlib.integrations.requests_client import OAuth2Session
208: 
209:             session = OAuth2Session(
210:                 client_id=self._config.client_id,
211:                 client_secret=self._config.client_secret,
212:                 redirect_uri=self._config.redirect_uri,
213:                 scope=self._config.scope,
214:             )
215:             uri, _ = session.create_authorization_url(
216:                 self._config.authorize_url,
217:                 state=state,
218:             )
219:             return uri  # type: ignore[no-any-return]
220:         except ImportError:
221:             _log.warning("[SSO] authlib submodules not available")
222:             return None
223:         except Exception as exc:
224:             _log.error("[SSO] Failed to create authorization URL: %s", exc)
225:             return None
226: 
```

## `handle_callback()`

```text
227:     async def handle_callback(self, code: str, state: str) -> SSOUser | None:
228:         """Handle the OAuth2 callback, exchanging the code for tokens and user info.
229: 
230:         Args:
231:             code: The authorization code from the provider.
232:             state: The OAuth2 state parameter (must match get_authorization_url).
233: 
234:         Returns:
235:             SSOUser on success, None on failure.
236: 
237:         """
238:         # Verify state
239:         with self._lock:
240:             expiry = self._state_store.pop(state, None)
241:             if expiry is None:
242:                 _log.warning("[SSO] Invalid or expired state parameter")
243:                 return None
244:             if time.time() > expiry:
245:                 _log.warning("[SSO] State parameter expired")
246:                 return None
247: 
248:         if not self.is_available:
249:             _log.warning("[SSO] authlib not installed -- cannot handle callback")
250:             return None
251: 
252:         try:
253:             from authlib.integrations.httpx_client import OAuth2Client
254: 
255:             async with OAuth2Client(
256:                 client_id=self._config.client_id,
257:                 client_secret=self._config.client_secret,
258:                 redirect_uri=self._config.redirect_uri,
259:                 scope=self._config.scope,
260:             ) as client:
261:                 # Exchange code for token
262:                 token = await client.fetch_token(
263:                     self._config.token_url,
264:                     code=code,
265:                 )
266:                 if not token:
267:                     _log.warning("[SSO] Token exchange failed")
268:                     return None
269: 
270:                 # Fetch user info
271:                 access_token = token.get("access_token", "")
272:                 if not access_token:
273:                     _log.warning("[SSO] No access token in response")
274:                     return None
275: 
276:                 headers = {"Authorization": f"Bearer {access_token}"}
277:                 resp = await client.get(self._config.userinfo_url, headers=headers)
278:                 if resp.status_code != 200:
279:                     _log.warning(
280:                         "[SSO] Userinfo fetch failed: %d %s",
281:                         resp.status_code, resp.text[:200],
282:                     )
283:                     return None
284: 
285:                 userinfo = resp.json()
286:                 return self._parse_userinfo(userinfo)
287: 
288:         except ImportError as exc:
289:             _log.warning("[SSO] authlib/httpx not available: %s", exc)
290:             return None
291:         except Exception as exc:
292:             _log.error("[SSO] Callback handling failed: %s", exc)
293:             return None
294: 
```

## `sso_login()`

```text
1063:     async def sso_login(
1064:         request: Request,
1065:         provider: str = "google",
1066:     ) -> dict:
1067:         """Initiate SSO login with the specified provider.
1068: 
1069:         Query params:
1070:             provider: OAuth2 provider (google, microsoft, github).
1071: 
1072:         Returns:
1073:             Dict with ``authorization_url`` to redirect the user to.
1074: 
1075:         """
1076:         # Use singleton SSO authenticator (closure) or create from req state
1077:         sso = _sso_authenticator
1078:         if sso is None:
1079:             from core.auth.sso import SSOAuthenticator
1080:             app_config = getattr(request.app.state, "config", {}) or {}
1081:             sso_redirect_uri = build_action_url(
1082:                 "/api/auth/sso/callback",
1083:                 cfg=app_config,
1084:             )
1085:             app_config["sso_redirect_uri"] = sso_redirect_uri
1086:             sso = SSOAuthenticator.from_config(auth_handler, app_config)
1087: 
1088:         # Keep the OAuth callback on the canonical public origin configured for
1089:         # this deployment. Do not derive it from request.base_url because that
1090:         # can be the internal reverse-proxy/upstream host (or localhost), which
1091:         # would make the provider redirect the user to an unusable URL.
1092:         app_config = getattr(request.app.state, "config", {}) or {}
1093:         sso._config.redirect_uri = build_action_url(
1094:             "/api/auth/sso/callback",
1095:             cfg=app_config,
1096:         )
1097: 
1098:         url = sso.get_authorization_url()
1099:         if url is None:
1100:             ready, issues = sso.is_ready()
1101:             raise HTTPException(
1102:                 status_code=400,
1103:                 detail={
1104:                     "message": "SSO not available",
1105:                     "issues": issues,
1106:                     "hint": "Install authlib: pip install authlib httpx",
1107:                 },
1108:             )
1109:         return {"success": True, "authorization_url": url}
1110: 
1111:     @router.get("/sso/callback")
```

## `get_public_base_url()`

```text
123: def get_public_base_url(cfg: dict[str, Any] | None = None) -> str:
124:     """Resolve the canonical public base URL for notifications, emails, and external links.
125: 
126:     Resolution order:
127:       1. Environment variable: PUBLIC_BASE_URL, APP_BASE_URL, EXTERNAL_BASE_URL, OPBUYING_PUBLIC_BASE_URL
128:       2. Explicit Configuration dict passed by caller
129:       3. Global configuration dict (json/config.json)
130:       4. Environment auto-detection:
131:          - Production -> https://gaurav-cockpit.servegame.com
132:          - Development -> http://localhost:8000
133:     """
134:     # 1. Explicit Admin-managed override. This is intentionally above deployment
135:     # environment variables so an authorized Admin/Super Admin can change the
136:     # public origin from the UI and have it reflected consistently at runtime.
137:     if cfg:
138:         val = cfg.get("PUBLIC_BASE_URL_ADMIN_OVERRIDE")
139:         if isinstance(val, str) and val.strip():
140:             url = val.strip().rstrip("/")
141:             if not url.startswith(("http://", "https://")):
142:                 url = f"https://{url}"
143:             if is_production_environment(cfg) and _is_loopback_url(url):
144:                 return DEFAULT_PRODUCTION_URL
145:             return url
146: 
147:     global_cfg = _get_global_config()
148:     val = global_cfg.get("PUBLIC_BASE_URL_ADMIN_OVERRIDE")
149:     if isinstance(val, str) and val.strip():
150:         url = val.strip().rstrip("/")
151:         if not url.startswith(("http://", "https://")):
152:             url = f"https://{url}"
153:         if is_production_environment(cfg) and _is_loopback_url(url):
154:             return DEFAULT_PRODUCTION_URL
155:         return url
156: 
157:     # 2. Environment variables retain deployment-level precedence for the
158:     # legacy PUBLIC_BASE_URL contract when no Admin override is configured.
159:     for env_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL", "OPBUYING_PUBLIC_BASE_URL"):
160:         val = os.environ.get(env_key)
161:         if val and val.strip():
162:             url = val.strip().rstrip("/")
163:             if not url.startswith(("http://", "https://")):
164:                 url = f"https://{url}"
165:             if is_production_environment(cfg) and _is_loopback_url(url):
166:                 return DEFAULT_PRODUCTION_URL
167:             return url
168: 
169:     # 3. Persisted legacy configuration fallback.
170:     if cfg:
171:         for cfg_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL"):
172:             val = cfg.get(cfg_key)
173:             if val and isinstance(val, str) and val.strip():
174:                 url = val.strip().rstrip("/")
175:                 if not url.startswith(("http://", "https://")):
176:                     url = f"https://{url}"
177:                 if is_production_environment(cfg) and _is_loopback_url(url):
178:                     return DEFAULT_PRODUCTION_URL
179:                 return url
180: 
181:     for cfg_key in ("PUBLIC_BASE_URL", "APP_BASE_URL", "EXTERNAL_BASE_URL", "PUBLIC_URL"):
182:         val = global_cfg.get(cfg_key)
183:         if val and isinstance(val, str) and val.strip():
184:             url = val.strip().rstrip("/")
185:             if not url.startswith(("http://", "https://")):
186:                 url = f"https://{url}"
187:             if is_production_environment(cfg) and _is_loopback_url(url):
188:                 return DEFAULT_PRODUCTION_URL
189:             return url
190: 
191:     # 4. Environment heuristic
192:     if is_production_environment(cfg):
193:         return DEFAULT_PRODUCTION_URL
194: 
195:     return DEFAULT_DEV_URL
196: 
197: 
```

## URL-like literals discovered in `sso.py`

- `
        existing = self._auth_handler.get_user(username)

        if existing:
            return existing

        # Try by email
        if sso_user.email:
            existing_by_email = self._auth_handler.get_user(sso_user.email)
            if existing_by_email:
                return existing_by_email

        # Create new user with a random password (SSO users authenticate via OAuth)
        import secrets as sec
        random_pass = sec.token_hex(24)
        display = sso_user.display_name or sso_user.email.split(`
- `
    authorize_url: str = `
- `
    redirect_uri: str = `
- `
    token_url: str = `
- `)
                if not access_token:
                    _log.warning(`
- `)
            return None

        state = state or secrets.token_urlsafe(32)
        with self._lock:
            self._state_store[state] = time.time() + self._state_ttl

        try:
            from authlib.integrations.requests_client import OAuth2Session

            session = OAuth2Session(
                client_id=self._config.client_id,
                client_secret=self._config.client_secret,
                redirect_uri=self._config.redirect_uri,
                scope=self._config.scope,
            )
            uri, _ = session.create_authorization_url(
                self._config.authorize_url,
                state=state,
            )
            return uri  # type: ignore[no-any-return]
        except ImportError:
            _log.warning(`
- `)
            return None
        if not self._config.client_id or not self._config.redirect_uri:
            _log.warning(`
- `)
        if not self._config.authorize_url:
            issues.append(`
- `)
        if not self._config.redirect_uri:
            issues.append(`
- `)
        if not self._config.token_url:
            issues.append(`
- `)
    async def sso_callback(code: str, state: str):
        user = await sso.handle_callback(code, state)
        token = auth_handler.create_session(user)
        return {`
- `)
    async def sso_login():
        redirect_url = sso.get_authorization_url()
        return RedirectResponse(url=redirect_url)

    @router.get(`
- `)),
            token_url=cfg.get(`
- `),
            authorize_url=cfg.get(`
- `),
            redirect_uri=cfg.get(`
- `,
        redirect_uri=`
- `, exc)
            return None

    async def handle_callback(self, code: str, state: str) -> SSOUser | None:
        `
- `: token.token}
`
- `Bearer {access_token}`
- `Configuration for an SSO/OAuth2 provider.

    Attributes:
        provider: Provider name (google, microsoft, github, or custom).
        client_id: OAuth2 client ID.
        client_secret: OAuth2 client secret.
        redirect_uri: Callback URL after authentication.
        authorize_url: Custom authorize URL (for custom providers).
        token_url: Custom token URL (for custom providers).
        userinfo_url: Custom userinfo URL (for custom providers).
        scope: OAuth2 scope string.
        enabled: Whether SSO is enabled.

    `
- `Create an SSOAuthenticator from a config dict.

        Expected config keys:
            - sso_enabled (bool)
            - sso_provider (str): google, microsoft, github, or custom
            - sso_client_id (str)
            - sso_client_secret (str)
            - sso_redirect_uri (str)
            - sso_scope (str, optional)
            - sso_authorize_url (str, optional, for custom providers)
            - sso_token_url (str, optional, for custom providers)
            - sso_userinfo_url (str, optional, for custom providers)
        `
- `Get an existing user or create a new one from SSO data.

        Integrates with the existing AuthHandler to look up users by
        email or create them on first SSO login.

        Args:
            sso_user: The SSO user returned by handle_callback().

        Returns:
            AuthUser from the AuthHandler, or None if integration fails.

        `
- `Handle the OAuth2 callback, exchanging the code for tokens and user info.

        Args:
            code: The authorization code from the provider.
            state: The OAuth2 state parameter (must match get_authorization_url).

        Returns:
            SSOUser on success, None on failure.

        `
- `[SSO] Callback handling failed: %s`
- `[SSO] Token exchange failed`
- `[SSO] authlib not installed -- cannot handle callback`
- `access_token`
- `authorize_url`
- `https://accounts.google.com/o/oauth2/v2/auth`
- `https://api.github.com/user`
- `https://github.com/login/oauth/access_token`
- `https://github.com/login/oauth/authorize`
- `https://graph.microsoft.com/v1.0/me`
- `https://login.microsoftonline.com/common/oauth2/v2.0/authorize`
- `https://login.microsoftonline.com/common/oauth2/v2.0/token`
- `https://oauth2.googleapis.com/token`
- `https://www.googleapis.com/oauth2/v3/userinfo`
- `token_url`

## Configuration symbols discovered

- `PUBLIC_BASE_URL_ADMIN_OVERRIDE`
