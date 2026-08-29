# OPB WEB CLOSURE WIP54 — Seven Unmatched UI Routes Forensic Review

Unmatched UI routes: 7

These are classified from source references only. No route is declared broken without evidence from registration or runtime behavior.

## `/*`
### UI occurrences
- `static/vendor/tailwind.min.js:13` — ``)){let a=this.raw(e,null,"indent");if(a.length)for(let o=0;o<s;o++)i+=a}return i}block(e,t){let i=this.raw(e,"between","beforeOpen");this.builder(t+i+"{",e,"start");let n;e.nodes&&e.nodes.length?(this.body(e),n=this.raw(e,"after")):n=this.raw(e,"after","emptyBody"),n&&this.builder(n),this.builder("}",e,"end")}body(e){let t=e.nodes.length-1;for(;t>0&&e.nodes[t].type==="comment";)t-=1;let i=this.ra`
- `static/vendor/tailwind.min.js:25` — `https://www.w3ctech.com/topic/2226`));let o=t(...a);return o.postcssPlugin=e,o.postcssVersion=new Ta().version,o}let s;return Object.defineProperty(n,"postcss",{get(){return s||(s=n()),s}}),n.process=function(a,o,l){return J([n(l)]).process(a,o)},n};J.stringify=F1;J.parse=N1;J.fromJSON=D1;J.list=L1;J.comment=r=>new vp(r);J.atRule=r=>new wp(r);J.decl=r=>new xp(r);J.rule=r=>new Ap(r);J.root=r=>new S`
- `static/vendor/tailwind.min.js:25` — `https://www.w3ctech.com/topic/2226`));let o=t(...a);return o.postcssPlugin=e,o.postcssVersion=new Ta().version,o}let s;return Object.defineProperty(n,"postcss",{get(){return s||(s=n()),s}}),n.process=function(a,o,l){return J([n(l)]).process(a,o)},n};J.stringify=F1;J.parse=N1;J.fromJSON=D1;J.list=L1;J.comment=r=>new vp(r);J.atRule=r=>new wp(r);J.decl=r=>new xp(r);J.rule=r=>new Ap(r);J.root=r=>new S`
- `static/vendor/tailwind.min.js:34` — ``))});c.push([p,d,h])}}for(let[l,[c,f]]of o){let d=[];for(let[h,b,v]of c){let y=[h,...Fg([h],e.tailwindConfig.separator)];for(let[w,k]of v){let S=xs(l),E=xs(k);if(E=E.groups.filter(R=>R.some(F=>y.includes(F))).flat(),E=E.concat(Fg(E,e.tailwindConfig.separator)),S.some(R=>E.includes(R)))throw k.error(`You cannot \`@apply\` the \`${h}\` utility here because it creates a circular dependency.`);let B=`
- `static/vendor/tailwind.min.js:40` — ``)}insert(e,t,i){let n=this.set(this.clone(e),t);if(!(!n||e.parent.some(a=>a.prop===n.prop&&a.value===n.value)))return this.needCascade(e)&&(n.raws.before=this.calcBefore(i,e,t)),e.parent.insertBefore(e,n)}isAlready(e,t){let i=this.all.group(e).up(n=>n.prop===t);return i||(i=this.all.group(e).down(n=>n.prop===t)),i}add(e,t,i,n){let s=this.prefixed(e.prop,t);if(!(this.isAlready(e,s)||this.otherPref`
### Repository references
- `core/fii_dii_tracker.py:37` — `"Accept": "application/json, text/plain, */*",`
- `index_app/index_trader.py:1095` — `_nse_session.headers.update({"User-Agent": "Mozilla/5.0", "Accept": "application/json, text/plain, */*"})`
- `static/theme_engine.js:1` — `/**`
- `static/theme_engine.js:249` — `/* ── Core Container & Card Tokens ────────────────────────────── */`
- `static/theme_engine.js:257` — `/* ── Form Inputs & Controls ─────────────────────────────────── */`
- `static/theme_engine.js:268` — `/* ── Typography & Headings ──────────────────────────────────── */`
- `static/theme_engine.js:289` — `/* ── Universal Semantic Badges ──────────────────────────────── */`
- `static/theme_engine.js:313` — `/* ── Navigation Components ───────────────────────────────────── */`
- `static/theme_engine.js:374` — `/* ── PWA & Details Banners ───────────────────────────────────── */`
- `static/theme_engine.js:391` — `/* ── Tabs & Quick Navigation ─────────────────────────────────── */`
- `static/theme_engine.js:420` — `/* ── Strategy Flyout & Badges ────────────────────────────────── */`
- `static/theme_engine.js:441` — `/* ── Tables & Data Grids ─────────────────────────────────────── */`
- `static/theme_engine.js:459` — `/* ── Emergency Kill Switch Button ───────────────────────────── */`
- `static/theme_engine.js:493` — `/* ── Theme Selectors & Status Dock ───────────────────────────── */`
- `static/theme_engine.js:523` — `/* ── Universal Multi-Theme Toast & Popup System ──────────────────────── */`
- `static/theme_engine.js:645` — `/* ── Universal Multi-Theme Modal System ──────────────────────────────── */`
- `static/theme_engine.js:772` — `/* ── Universal Toast & Modal Engine Implementation ──────────────────── */`
- `static/tailwind.min.js:1` — `/* RealEstate India — Tailwind CSS Utility Classes (Production Bundle)`
- `static/tailwind.min.js:18` — `/* Layout */`
- `static/tailwind.min.js:40` — `/* Grid columns */`
- `static/tailwind.min.js:46` — `/* Text */`
- `static/tailwind.min.js:66` — `/* Spacing */`
- `static/tailwind.min.js:101` — `/* Colors */`
- `static/tailwind.min.js:126` — `/* Borders */`
- `static/tailwind.min.js:142` — `/* Sizing */`
- `static/tailwind.min.js:157` — `/* Effects */`
- `static/tailwind.min.js:172` — `/* Cursor */`
- `static/tailwind.min.js:175` — `/* Overflow */`
- `static/tailwind.min.js:179` — `/* Position */`
- `static/tailwind.min.js:193` — `/* Visual */`
- `static/tailwind.min.js:196` — `/* Animations */`
- `static/tailwind.min.js:202` — `/* Responsive */`
- `static/tailwind.min.js:224` — `/* Dark theme overrides for enterprise dashboard */`
- `static/tailwind.min.js:229` — `/* Toast messages */`
- `static/tailwind.min.js:236` — `/* Skeleton loading */`
- `scripts/fix_stale_doc_refs.py:138` — `md_files = sorted(glob.glob("**/*.md", recursive=True))`
- `scripts/check_stale_doc_refs.py:13` — `python scripts/check_stale_doc_refs.py docs/*.md`
- `scripts/generate_integration_manifest.py:192` — `"> Stub **app/** - must not replace this product’s real modules.\n\n"`
- `scripts/batch_convert_exceptions.py:128` — `for f in sorted(root.rglob("core/**/*.py")):`
- `scripts/generate_config_schemas.py:5` — `python scripts/generate_config_schemas.py              # write schemas/*.schema.json`
- `scripts/hygiene_check.py:73` — `"stale_reports": ["reports/*.html", "reports/*.xml", "reports/*.json"],`
- `scripts/hygiene_check.py:363` — `if fnmatch.fnmatch(rel, raw_name) or fnmatch.fnmatch(rel, f"{base}/*"):`
- `scripts/sync_artifacts.py:49` — `"ci_cd": [".github/**/*.yml", "bitbucket-pipelines.yml", ".gitlab-ci.yml"],`
- `scripts/sync_artifacts.py:270` — `alt_test_paths = list(ROOT.glob(f"tests/**/{test_name}"))`
- `scripts/gen_ppt.py:374` — `"Admin API: /api/config/*, /api/auth/users/*",`
- `scripts/db_backup.py:41` — `_DEFAULT_DB_PATTERNS = ["db/*.db", "db/*.db-wal", "db/*.db-shm"]`
- `scripts/constitution_scorecard.py:102` — `"core/ports/*.py", weight=1.0),`
- `scripts/constitution_scorecard.py:104` — `"core/services/use_cases/*.py", weight=1.0),`
- `scripts/constitution_scorecard.py:126` — `"core/enterprise_dashboard/routes/*.py", weight=1.0),`
- `scripts/boost_constitution_evidence.py:75` — `("PLS-06", "Provisioning dashboard routes — /api/platform/provisioning/*", "code_review", 0.4, "core/enterprise_dashboard/routes/provisioning.py"),`
- `scripts/compile_validate.py:18` — `all_files = glob.glob("**/*.py", recursive=True)`
- `scripts/clean_artifacts.py:55` — `"reports/*.db",`
- `scripts/clean_artifacts.py:56` — `"reports/*.sqlite",`
- `tests/test_ci_compose_yaml.py:26` — `"""Every deployment YAML: workflows/*, .github root configs, docker-compose*.`
- `tests/test_ci_compose_yaml.py:28` — `Covers .github/workflows/*.yml + *.yaml, .github/*.yml (e.g.`
- `tests/test_constitution_scorecard.py:144` — `module_path="core/ports/*.py",`
- `templates/enterprise/dashboard.html:139` — `/* Mobile Responsive Dashboard Clean */`
- `templates/enterprise/dashboard.html:146` — `display: none !important; /* Hide redundant banner on mobile */`
- `templates/enterprise/dashboard.html:166` — `/* ── Mobile vs Desktop Cockpit Header Styling ── */`
- `templates/enterprise/admin_config.html:23` — `/* ── Header Title & Controls ────────────────────────────────────────── */`
- `templates/enterprise/admin_config.html:59` — `/* ── Modern Buttons ─────────────────────────────────────────────────── */`
- `templates/enterprise/admin_config.html:111` — `/* ── Segmented Tab Bar ──────────────────────────────────────────────── */`
- `templates/enterprise/admin_config.html:148` — `/* ── Main Container & Card Grid ─────────────────────────────────────── */`
- `templates/enterprise/admin_config.html:163` — `/* ── Cockpit Parameter Tile Architecture ────────────────────────────── */`
- `templates/enterprise/admin_config.html:247` — `/* ── Toast Container & Modal ────────────────────────────────────────── */`
- `templates/enterprise/user_signals.html:34` — `/* Modal styling */`
- `templates/enterprise/security.html:124` — `<tr><td><strong>CSRF Exempt Paths</strong></td><td style="font-size:0.7rem;">/api/auth/*, /api/system/health/docker, /signals/inject, /api/system/self-test</td></tr>`
- `templates/enterprise/strategy_sandbox.html:27` — `/* ── 16 Strategies Architectural Cards ─────────────────────────────── */`
- `templates/enterprise/presentation.html:180` — `} catch(e) { /* fallback */ }`
- `templates/enterprise/profile.html:26` — `/* ── Hero Profile Banner ── */`
- `templates/enterprise/profile.html:103` — `/* ── Profile Cards ── */`
- `templates/enterprise/profile.html:132` — `/* ── Form Inputs & Password Toggles ── */`
- `templates/enterprise/profile.html:205` — `/* ── Buttons ── */`
- `templates/enterprise/profile.html:247` — `/* ── Entitlements List ── */`
- `templates/enterprise/profile.html:310` — `/* ── Quick Link ── */`
- `templates/enterprise/profile.html:331` — `/* Toast Notifications */`
- `templates/enterprise/_nav.html:11` — `/* ══════════════════════════════════════════════════════════════════════════`
- `templates/enterprise/_nav.html:116` — `/* Keep the desktop dropdown connected to its trigger: the previous 6px`
- `templates/enterprise/_nav.html:154` — `/* ══════════════════════════════════════════════════════════════════════════`
- `templates/enterprise/_nav.html:198` — `/* ── Slide-Over Mobile Navigation Drawer ── */`
- `templates/enterprise/_nav.html:232` — `/* Drawer Active States */`
- `static/vendor/tailwind.min.js:13` — ``)){let a=this.raw(e,null,"indent");if(a.length)for(let o=0;o<s;o++)i+=a}return i}block(e,t){let i=this.raw(e,"between","beforeOpen");this.builder(t+i+"{",e,"start");let n;e.nodes&&e.nodes.length?(this.body(e),n=this.raw(e,"after")):n=this.raw(e,"after","emptyBody"),n&&this.builder(n),this.builder("}",e,"end")}body(e){let t=e.nodes.length-1;for(;t>0&&e.nodes[t].type==="comment";)t-=1;let i=this.raw(e,"semicolon");for(let n=0;n<e.nodes.length;n++){let s=e.nodes[n],a=this.raw(s,"before");a&&this.b`
- `static/vendor/tailwind.min.js:25` — `https://www.w3ctech.com/topic/2226`));let o=t(...a);return o.postcssPlugin=e,o.postcssVersion=new Ta().version,o}let s;return Object.defineProperty(n,"postcss",{get(){return s||(s=n()),s}}),n.process=function(a,o,l){return J([n(l)]).process(a,o)},n};J.stringify=F1;J.parse=N1;J.fromJSON=D1;J.list=L1;J.comment=r=>new vp(r);J.atRule=r=>new wp(r);J.decl=r=>new xp(r);J.rule=r=>new Ap(r);J.root=r=>new Sp(r);J.document=r=>new kp(r);J.CssSyntaxError=I1;J.Declaration=xp;J.Container=P1;J.Processor=Ta;J.Do`
- `static/vendor/tailwind.min.js:27` — ``),v=y.length-1,v>0?(k=a+v,S=w-y[v].length):(k=a,S=s),T=D.comment,a=k,p=k,d=w-S):c===D.slash?(w=o,T=c,p=a,d=o-s,l=w+1):(w=OA(t,o),T=D.word,p=a,d=w-s),l=w+1;break}e.push([T,a,o-s,p,d,o,l]),S&&(s=S,S=null),o=l}return e}});var kd=x((ki,xd)=>{u();"use strict";ki.__esModule=!0;ki.default=void 0;var IA=je(Da()),fo=je($a()),DA=je(Na()),md=je(Fa()),qA=je(za()),$A=je(Ha()),co=je(Ga()),LA=je(Ya()),gd=Vn(to()),MA=je(io()),po=je(so()),NA=je(oo()),BA=je(fd()),O=Vn(hd()),q=Vn(lo()),FA=Vn(Se()),ue=ii(),Vt,ho;f`
- `static/vendor/tailwind.min.js:32` — ``,CHAR_NO_BREAK_SPACE:"\xA0",CHAR_PERCENT:"%",CHAR_PLUS:"+",CHAR_QUESTION_MARK:"?",CHAR_RIGHT_ANGLE_BRACKET:">",CHAR_RIGHT_CURLY_BRACE:"}",CHAR_RIGHT_SQUARE_BRACKET:"]",CHAR_SEMICOLON:";",CHAR_SINGLE_QUOTE:"'",CHAR_SPACE:" ",CHAR_TAB:"	",CHAR_UNDERSCORE:"_",CHAR_VERTICAL_LINE:"|",CHAR_ZERO_WIDTH_NOBREAK_SPACE:"\uFEFF"}});var Nm=x((s6,Mm)=>{u();"use strict";var mE=hs(),{MAX_LENGTH:qm,CHAR_BACKSLASH:dl,CHAR_BACKTICK:gE,CHAR_COMMA:yE,CHAR_DOT:bE,CHAR_LEFT_PARENTHESES:wE,CHAR_RIGHT_PARENTHESES:vE,CH`
- `static/vendor/tailwind.min.js:34` — ``))});c.push([p,d,h])}}for(let[l,[c,f]]of o){let d=[];for(let[h,b,v]of c){let y=[h,...Fg([h],e.tailwindConfig.separator)];for(let[w,k]of v){let S=xs(l),E=xs(k);if(E=E.groups.filter(R=>R.some(F=>y.includes(F))).flat(),E=E.concat(Fg(E,e.tailwindConfig.separator)),S.some(R=>E.includes(R)))throw k.error(`You cannot \`@apply\` the \`${h}\` utility here because it creates a circular dependency.`);let B=ee.root({nodes:[k.clone()]});B.walk(R=>{R.source=f}),(k.type!=="atrule"||k.type==="atrule"&&k.name!=`
- `static/vendor/tailwind.min.js:40` — ``)}insert(e,t,i){let n=this.set(this.clone(e),t);if(!(!n||e.parent.some(a=>a.prop===n.prop&&a.value===n.value)))return this.needCascade(e)&&(n.raws.before=this.calcBefore(i,e,t)),e.parent.insertBefore(e,n)}isAlready(e,t){let i=this.all.group(e).up(n=>n.prop===t);return i||(i=this.all.group(e).down(n=>n.prop===t)),i}add(e,t,i,n){let s=this.prefixed(e.prop,t);if(!(this.isAlready(e,s)||this.otherPrefixes(e.value,t)))return this.insert(e,t,i,n)}process(e,t){if(!this.needCascade(e)){super.process(e,t`
- `static/vendor/tailwind.min.js:65` — `/*!`
- `static/vendor/tailwind.min.js:71` — `/*!`
- `static/vendor/tailwind.min.js:77` — `/*!`
- `static/vendor/tailwind.min.js:83` — `/*! https://mths.be/cssesc v3.0.0 by @mathias */`
- `static/vendor/chart.umd.min.js:1` — `/**`
- `static/vendor/chart.umd.min.js:7` — `/*!`
- `static/vendor/chart.umd.min.js:14` — `/*!`
- `archive/unrelated_modules/templates/realestate/property_detail.html:30` — `/* Lightbox */`
- `infrastructure/adapters/market_data/nse/adapter.py:87` — `'Accept': 'application/json, text/plain, */*',`
- `index_app/domains/market/holidays.py:80` — `"Accept": "application/json, text/plain, */*",`
- `core/static/theme_engine.js:1` — `/**`
- `core/static/leaflet-map.js:1` — `/**`
- `core/static/leaflet-map.js:37` — `/**`

## `/**`
### UI occurrences
- `static/vendor/tailwind.min.js:32` — ``,CHAR_NO_BREAK_SPACE:"\xA0",CHAR_PERCENT:"%",CHAR_PLUS:"+",CHAR_QUESTION_MARK:"?",CHAR_RIGHT_ANGLE_BRACKET:">",CHAR_RIGHT_CURLY_BRACE:"}",CHAR_RIGHT_SQUARE_BRACKET:"]",CHAR_SEMICOLON:";",CHAR_SINGLE_QUOTE:"'",CHAR_SPACE:" ",CHAR_TAB:"	",CHAR_UNDERSCORE:"_",CHAR_VERTICAL_LINE:"|",CHAR_ZERO_WIDTH_NOBREAK_SPACE:"\uFEFF"}});var Nm=x((s6,Mm)=>{u();"use strict";var mE=hs(),{MAX_LENGTH:qm,CHAR_BACKSLASH`
- `static/vendor/tailwind.min.js:32` — ``,CHAR_NO_BREAK_SPACE:"\xA0",CHAR_PERCENT:"%",CHAR_PLUS:"+",CHAR_QUESTION_MARK:"?",CHAR_RIGHT_ANGLE_BRACKET:">",CHAR_RIGHT_CURLY_BRACE:"}",CHAR_RIGHT_SQUARE_BRACKET:"]",CHAR_SEMICOLON:";",CHAR_SINGLE_QUOTE:"'",CHAR_SPACE:" ",CHAR_TAB:"	",CHAR_UNDERSCORE:"_",CHAR_VERTICAL_LINE:"|",CHAR_ZERO_WIDTH_NOBREAK_SPACE:"\uFEFF"}});var Nm=x((s6,Mm)=>{u();"use strict";var mE=hs(),{MAX_LENGTH:qm,CHAR_BACKSLASH`
### Repository references
- `static/theme_engine.js:1` — `/**`
- `scripts/generate_integration_manifest.py:192` — `"> Stub **app/** - must not replace this product’s real modules.\n\n"`
- `scripts/batch_convert_exceptions.py:128` — `for f in sorted(root.rglob("core/**/*.py")):`
- `scripts/sync_artifacts.py:49` — `"ci_cd": [".github/**/*.yml", "bitbucket-pipelines.yml", ".gitlab-ci.yml"],`
- `scripts/sync_artifacts.py:270` — `alt_test_paths = list(ROOT.glob(f"tests/**/{test_name}"))`
- `static/vendor/tailwind.min.js:32` — ``,CHAR_NO_BREAK_SPACE:"\xA0",CHAR_PERCENT:"%",CHAR_PLUS:"+",CHAR_QUESTION_MARK:"?",CHAR_RIGHT_ANGLE_BRACKET:">",CHAR_RIGHT_CURLY_BRACE:"}",CHAR_RIGHT_SQUARE_BRACKET:"]",CHAR_SEMICOLON:";",CHAR_SINGLE_QUOTE:"'",CHAR_SPACE:" ",CHAR_TAB:"	",CHAR_UNDERSCORE:"_",CHAR_VERTICAL_LINE:"|",CHAR_ZERO_WIDTH_NOBREAK_SPACE:"\uFEFF"}});var Nm=x((s6,Mm)=>{u();"use strict";var mE=hs(),{MAX_LENGTH:qm,CHAR_BACKSLASH:dl,CHAR_BACKTICK:gE,CHAR_COMMA:yE,CHAR_DOT:bE,CHAR_LEFT_PARENTHESES:wE,CHAR_RIGHT_PARENTHESES:vE,CH`
- `static/vendor/chart.umd.min.js:1` — `/**`
- `core/static/theme_engine.js:1` — `/**`
- `core/static/leaflet-map.js:1` — `/**`
- `core/static/leaflet-map.js:37` — `/**`
- `core/static/leaflet-map.js:92` — `/**`
- `core/static/leaflet-map.js:132` — `/** Remove all property markers from the map. */`
- `core/static/leaflet-map.js:140` — `/**`
- `core/static/leaflet-map.js:158` — `/**`
- `core/static/leaflet-map.js:186` — `/**`
- `core/static/leaflet-map.js:238` — `/**`
- `core/static/leaflet-map.js:262` — `/** Return CSS styles for the map container. */`
- `core/static/sw.js:1` — `/**`

## `/*__simple__*/`
### UI occurrences
- `static/vendor/tailwind.min.js:27` — ``),v=y.length-1,v>0?(k=a+v,S=w-y[v].length):(k=a,S=s),T=D.comment,a=k,p=k,d=w-S):c===D.slash?(w=o,T=c,p=a,d=o-s,l=w+1):(w=OA(t,o),T=D.word,p=a,d=w-s),l=w+1;break}e.push([T,a,o-s,p,d,o,l]),S&&(s=S,S=null),o=l}return e}});var kd=x((ki,xd)=>{u();"use strict";ki.__esModule=!0;ki.default=void 0;var IA=je(Da()),fo=je($a()),DA=je(Na()),md=je(Fa()),qA=je(za()),$A=je(Ha()),co=je(Ga()),LA=je(Ya()),gd=Vn(to(`
- `static/vendor/tailwind.min.js:27` — ``),v=y.length-1,v>0?(k=a+v,S=w-y[v].length):(k=a,S=s),T=D.comment,a=k,p=k,d=w-S):c===D.slash?(w=o,T=c,p=a,d=o-s,l=w+1):(w=OA(t,o),T=D.word,p=a,d=w-s),l=w+1;break}e.push([T,a,o-s,p,d,o,l]),S&&(s=S,S=null),o=l}return e}});var kd=x((ki,xd)=>{u();"use strict";ki.__esModule=!0;ki.default=void 0;var IA=je(Da()),fo=je($a()),DA=je(Na()),md=je(Fa()),qA=je(za()),$A=je(Ha()),co=je(Ga()),LA=je(Ya()),gd=Vn(to(`
### Repository references
- `static/vendor/tailwind.min.js:27` — ``),v=y.length-1,v>0?(k=a+v,S=w-y[v].length):(k=a,S=s),T=D.comment,a=k,p=k,d=w-S):c===D.slash?(w=o,T=c,p=a,d=o-s,l=w+1):(w=OA(t,o),T=D.word,p=a,d=w-s),l=w+1;break}e.push([T,a,o-s,p,d,o,l]),S&&(s=S,S=null),o=l}return e}});var kd=x((ki,xd)=>{u();"use strict";ki.__esModule=!0;ki.default=void 0;var IA=je(Da()),fo=je($a()),DA=je(Na()),md=je(Fa()),qA=je(za()),$A=je(Ha()),co=je(Ga()),LA=je(Ya()),gd=Vn(to()),MA=je(io()),po=je(so()),NA=je(oo()),BA=je(fd()),O=Vn(hd()),q=Vn(lo()),FA=Vn(Se()),ue=ii(),Vt,ho;f`

## `/10`
### UI occurrences
- `templates/enterprise/intelligence.html:568` — `document.getElementById('hCodeQuality').textContent = h.code_quality_score != null ? h.code_quality_score.toFixed(1)+'/10' : '-';`
- `templates/enterprise/intelligence.html:569` — `document.getElementById('hTestQuality').textContent = h.test_quality_score != null ? h.test_quality_score.toFixed(1)+'/10' : '-';`
- `templates/enterprise/intelligence.html:570` — `document.getElementById('hSecurity').textContent = h.security_score != null ? h.security_score.toFixed(1)+'/10' : '-';`
- `templates/enterprise/intelligence.html:571` — `document.getElementById('hIncidents').textContent = h.incident_impact_score != null ? h.incident_impact_score.toFixed(1)+'/10' : '-';`
- `templates/enterprise/intelligence.html:578` — `document.getElementById('avgHealthScore').textContent = t.avg_health_score != null ? t.avg_health_score.toFixed(1)+'/10' : '-';`
### Repository references
- `core/iv_surface.py:155` — `f"  Skew: {self.skew_slope:+.1f} bp/10%% moneyness\n"`
- `core/presentation_generator.py:267` — `score = str(data.get("score", "9.6/10"))`
- `core/presentation_generator.py:848` — `["Architecture Score", "9.81/10"],`
- `core/market_scanner_daemon.py:83` — `_log.info(">> DISPATCHED: %s %s | Score: %d/100 (%s) | LTP: Rs %.2f",`
- `core/gex_analyzer.py:16` — `For options buying with IV approximation (σ ≈ VIX/100):`
- `core/liquidity_analytics.py:135` — `f"  Composite Score: {self.composite_score:.1f}/100\n"`
- `core/liquidity_analytics.py:137` — `f"  Spread Score:    {self.spread_score:.1f}/100\n"`
- `core/liquidity_analytics.py:138` — `f"  Volume Score:    {self.volume_score:.1f}/100\n"`
- `core/liquidity_analytics.py:139` — `f"  OI Score:        {self.oi_score:.1f}/100\n"`
- `core/param_optimizer.py:103` — `# (simulated by keeping top (1 - v/100) fraction ranked by pnl magnitude)`
- `core/performance_optimizer.py:173` — `f"  Score: {self.overall_score:.1f}/10.0",`
- `core/performance_optimizer.py:293` — `report.bottlenecks.append(f"{m.module_path} ({m.score:.1f}/10) — {m.finding_count} issues")`
- `core/accessibility_gate.py:202` — `f"  Score: {self.overall_score:.1f}/10.0  |  Risk: {self.risk_level}",`
- `core/accessibility_gate.py:459` — `print(f"Last Score: {stats['last_score']}/10")`
- `core/release_intelligence.py:143` — `f"  Readiness Score: {self.release_readiness_score:.1f}/100",`
- `core/release_intelligence.py:150` — `f"    Risk Score:           {self.risk_score:.1f}/100",`
- `core/release_intelligence.py:151` — `f"    Migration Safety:     {self.migration_safety_score:.1f}/100",`
- `core/release_intelligence.py:152` — `f"    Dependency Readiness: {self.dependency_readiness_score:.1f}/100",`
- `core/release_intelligence.py:153` — `f"    Infrastructure:       {self.infrastructure_readiness_score:.1f}/100",`
- `core/quality_gates.py:163` — `f"  Engineering Score: {self.engineering_score:.1f}/10.0",`
- `core/vulnerability_scanner.py:115` — `f"  Risk Score: {self.risk_score:.1f}/100  Pass: {self.pass_threshold}",`
- `core/audit_mode.py:98` — `f"  Score: {self.score:.1f}/10",`
- `core/all_nse_scanner.py:243` — `"""Dynamic category-level conviction score threshold (Strict 100/100 conviction)."""`
- `core/all_nse_scanner.py:309` — `# STRICT 100 CONVICTION FILTER: Only 100/100 score signals are allowed`
- `core/all_nse_scanner.py:358` — `_log.info(">> DETECTED %s SIGNAL for %s (Score: %d/100, Tier: %s, Price: Rs %.2f)",`
- `core/all_nse_scanner.py:487` — `• 16-Strategy Composite Score: {signal.score}/100 (Tier: {signal.tier})`
- `core/all_nse_scanner.py:502` — `_log.info("[GATE] Suppressed signal for %s (%s, Score: %d) - below strict 100/100 conviction score threshold",`
- `core/all_nse_scanner.py:699` — `print(f"* {s.symbol:<12} ({name_clean}): {s.direction:<4} | Score: {s.score:<3}/100 ({s.tier}) | LTP: Rs {s.price:,.2f} | RSI: {s.rsi:.1f}")`
- `core/executive_advisor.py:431` — `value=f"{briefing.system_health.overall_score:.1f}/10",`
- `core/executive_advisor.py:478` — `value=f"{briefing.system_health.security_score:.1f}/10",`
- `core/executive_advisor.py:575` — `f"System health: {health:.1f}/10 | "`
- `core/hallucination_detector.py:131` — `- Absolute claims (always/never/100% — rarely true)`
- `core/runtime_security.py:154` — `f"  Score: {self.score:.1f}/10.0  |  Risk: {self.overall_risk}",`
- `core/runtime_security.py:592` — `print(f"Last Score: {stats['last_score']}/10")`
- `core/continuous_intelligence.py:115` — `lines.append(f"  v4.0 Health: {self.v4_overall_score}/10 ({self.v4_total_categories} cats, {self.v4_open_regressions} regr)")`
- `core/presentation_engine.py:47` — `f"Score: {int(score)}/100\n"`
- `core/presentation_engine.py:62` — `f"Score: {int(score)}/100 | IV: {iv} | VIX: {vix} | Net RR: {round(net_rr, 2)}\n"`
- `core/architecture_analyzer.py:193` — `f"  Score: {self.score:.1f}/10.0",`
- `core/security_auditor.py:194` — `f"  Score: {self.score:.1f}/10.0",`
- `core/telegram_commander.py:97` — `f"Score: [{score_bar}] {score}/100",`
- `core/autonomous_optimizer.py:180` — `f"  Score: {self.overall_optimization_score:.1f}/10.0",`
- `core/recommendation_engine.py:498` — `rationale=f"Overall constitution score is {overall:.1f}/10 — improve governance posture",`
- `core/bi_dashboard.py:260` — `lines.append(f"  ┌─ Health Score: {self.current_health.overall_score:.1f}/10.0")`
- `core/bi_dashboard.py:749` — `f"Health: {trend.current_health_score:.1f}/10 | "`
- `core/bi_dashboard.py:799` — `f"Security score {health.security_score}/10 is below target — run a security review and patch vulnerabilities."`
- `core/bi_dashboard.py:803` — `f"Security score {health.security_score}/10 meets the bar — maintain the current security posture."`
- `core/constitution_alert_bridge.py:179` — `alert_parts = [f"Constitution Health: {result.overall_score:.2f}/10 ({result.health_status})"]`
- `scripts/generate_master_pptx.py:443` — `f"Constitution Engine: {constitution['categories']}-category scoring with {constitution['evidence']:,} evidence entries — {constitution['overall']:.2f}/10",`
- `scripts/generate_master_pptx.py:451` — `sb.section_slide("System Certification", "Formal Production Readiness: 10.00/10.00 (100% Certified)")`
- `scripts/generate_master_pptx.py:545` — `"OPB Index Options Buying Bot v2.57.1\nProduction Certified: 8.62/10.00",`
- `scripts/generate_constitution_report.py:307` — `f"Score: {report['overall_score']:.2f}/10 — Trending: {report['trending']['direction'].upper()}",`
- `scripts/gen_ppt.py:120` — `"🏆 Institutional Certification Score: 10.0/10.0", size=16, bold=True, color=PROFIT, alignment=PP_ALIGN.CENTER)`
- `scripts/gen_ppt.py:244` — `"OVERALL: 10.0/10.0 🏆",`
- `scripts/gen_ppt.py:668` — `"🏆 Institutional Certification: 10.0/10.0 · All 31 Categories · 100%", size=16, color=PROFIT, alignment=PP_ALIGN.CENTER)`
- `scripts/generate_all_master_consolidated_documents.py:119` — `• Strategy Composite Score: 92/100 (Tier: STRONG)`
- `scripts/score_system.py:18` — `perfect 10.0/10.0 achievable when every category has verified evidence)`
- `scripts/generate_pdf_report.py:68` — `"CERTIFICATION: APPROVED (10.0/10)",`
- `scripts/generate_pdf_report.py:117` — `["Certification Score", "10.0/10", "Institutional Board"],`
- `scripts/generate_pdf_report.py:183` — `["Architecture", "10.0/10", "Code Quality", "10.0/10"],`
- `scripts/generate_pdf_report.py:184` — `["Reliability", "10.0/10", "Security", "10.0/10"],`
- `scripts/generate_pdf_report.py:185` — `["Performance", "10.0/10", "Maintainability", "10.0/10"],`
- `scripts/generate_pdf_report.py:186` — `["Scalability", "10.0/10", "Testing", "10.0/10"],`
- `scripts/generate_pdf_report.py:187` — `["Risk Controls", "10.0/10", "Observability", "10.0/10"],`
- `scripts/generate_pdf_report.py:188` — `["Documentation", "10.0/10", "Future Readiness", "10.0/10"],`
- `scripts/generate_pdf_report.py:204` — `"OVERALL SCORE: 10.0/10  |  "`
- `scripts/run_pr_audit.py:168` — `f"**Overall Score: {self.score:.1f}/100**  ",`
- `scripts/run_pr_audit.py:218` — `f"  Overall Score: {self.score:.1f}/100",`
- `scripts/generate_consolidated_report.py:260` — `f"The system achieves an overall constitution score of <b>{overall_score}/10</b> "`
- `scripts/generate_consolidated_report.py:262` — `f"and a PR audit score of <b>{pr_score}/100</b>.",`
- `scripts/generate_consolidated_report.py:269` — `_make_stat_card(s, "Constitution Score", f"{overall_score}/10", _score_color(overall_score)),`
- `scripts/generate_consolidated_report.py:272` — `_make_stat_card(s, "PR Audit Score", f"{pr_score}/100", _score_color(pr_score / 10)),`
- `scripts/generate_consolidated_report.py:310` — `f"<b>[!] {len(below_red)} categories below {THRESHOLD_RED}/10</b> require attention: "`
- `scripts/generate_consolidated_report.py:402` — `story.append(Paragraph("Gap Analysis - Categories Below 7.5/10", s["h1"]))`
- `scripts/generate_consolidated_report.py:438` — `f"<b>All {n_categories} categories are above {THRESHOLD_RED}/10!</b>",`
- `scripts/generate_consolidated_report.py:450` — `f"(currently {c['evidence_count']}) to cross {THRESHOLD_RED}/10"`
- `scripts/generate_consolidated_report.py:466` — `f"Overall PR Audit Score: <b>{pr_score}/100</b> - "`
- `scripts/generate_consolidated_report.py:517` — `["Session Start", "7.66/10", "1,345", "Baseline"],`
- `scripts/generate_consolidated_report.py:518` — `["After 47-category fix", "7.92/10", "1,424", "+79 evidence, 45 categories crossed 7.0"],`
- `scripts/generate_consolidated_report.py:519` — `["After boost collector", "8.25/10", "1,528", "+104 evidence, 35 targeted categories boosted"],`
- `scripts/generate_consolidated_report.py:520` — `["Constitution v4.0 engine audit", "8.71/10", "1,703", "+175 evidence, 111 categories live-scored"],`
- `scripts/generate_consolidated_report.py:521` — `["Top-10 gap closure", "8.83/10", "1,757", "+54 evidence, 10 categories at 100%"],`
- `scripts/generate_consolidated_report.py:530` — `f"{prev['score']}/10",`
- `scripts/generate_consolidated_report.py:536` — `f"{overall_score}/10",`
- `scripts/generate_consolidated_report.py:561` — `f"<b>Overall Score:</b> {prev['score'] if prev else 7.66:.2f}/10 → {overall_score}/10 "`
- `scripts/generate_consolidated_report.py:588` — `f"<b>Constitution Score:</b> {overall_score}/10 (up from 7.66)",`
- `scripts/generate_consolidated_report.py:589` — `f"<b>PR Audit Score:</b> {pr_score}/100",`
- `scripts/generate_consolidated_report.py:599` — `f"Version v2.57.1 · Constitution Score: {overall_score}/10 · PR Audit: {pr_score}/100",`
- `scripts/run_consolidated_full_system_verification.py:63` — `_log.info("✅ [2/20 PASSED] Evaluated TCS: Score %d/100, Tier: %s, Price: ₹%.2f", sig.score, sig.tier, sig.price)`
- `scripts/constitution_scorecard.py:327` — `f" -> Weighted: {self.overall_weighted_score:.1f}/100"`
- `scripts/batch_portfolio_scan.py:140` — `log.info(f"Scan Complete -> Health Score: {score}/100 | PnL: ₹{pnl}")`
- `scripts/boost_constitution_evidence.py:201` — `print(f"\nUpdated overall score: {report.overall_score:.2f}/10")`
- `scripts/gen_gap_analysis.py:3` — `NOTE: All 19 phases are now COMPLETE with the system scoring 10/10 across`
- `scripts/gen_gap_analysis.py:17` — `report.append("Target: ALL categories >= 10/10 with objective evidence")`
- `scripts/gen_gap_analysis.py:20` — `report.append("Current Baseline: 10.0/10.0 across all 31 categories (905 evidence items, 0 regressions)")`
- `scripts/gen_gap_analysis.py:49` — `report.append("  [DONE] Architecture Certification: 10.0/10.0 (ARCH-01 through ARCH-04)")`
- `scripts/gen_gap_analysis.py:53` — `report.append("STATUS: ✅ COMPLETE (10.0/10.0)")`
- `scripts/gen_gap_analysis.py:58` — `report.append("  [DONE] All Risk categories at 10.0/10.0 (RSK-01 through RSK-04)")`
- `scripts/gen_gap_analysis.py:71` — `report.append("STATUS: ✅ COMPLETE (10.0/10.0)")`
- `scripts/gen_gap_analysis.py:77` — `report.append("  [DONE] All Execution categories at 10.0/10.0 (EXE-01 through EXE-04)")`
- `scripts/gen_gap_analysis.py:140` — `report.append("STATUS: ✅ COMPLETE (10.0/10.0)")`

## `/10</span>`
### UI occurrences
- `templates/enterprise/intelligence.html:554` — `document.getElementById('healthScore').innerHTML = r.current_health ? '<span style="color:'+(r.current_health.overall_score>=7?'#4ade80':r.current_health.overall_score>=5?'#fbbf24':'#f87171')+'">'+r.current_health.overall_score.toFixed(1)+'/10</span>' : '-';`
### Repository references
- `templates/enterprise/intelligence.html:554` — `document.getElementById('healthScore').innerHTML = r.current_health ? '<span style="color:'+(r.current_health.overall_score>=7?'#4ade80':r.current_health.overall_score>=5?'#fbbf24':'#f87171')+'">'+r.current_health.overall_score.toFixed(1)+'/10</span>' : '-';`
- `archive/unrelated_modules/templates/realestate/property_detail.html:423` — `<div class="detail-item"><span class="label">Schools</span><span class="value">${i.schools_rating}/10</span></div>`
- `archive/unrelated_modules/templates/realestate/property_detail.html:424` — `<div class="detail-item"><span class="label">Hospitals</span><span class="value">${i.hospitals_rating}/10</span></div>`
- `archive/unrelated_modules/templates/realestate/property_detail.html:425` — `<div class="detail-item"><span class="label">Connectivity</span><span class="value">${i.connectivity_rating}/10</span></div>`
- `archive/unrelated_modules/templates/realestate/property_detail.html:426` — `<div class="detail-item"><span class="label">Safety</span><span class="value">${i.safety_rating}/10</span></div>`

## `/g,`
### UI occurrences
- `templates/enterprise/intelligence.html:1020` — `'<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+(inc.description||'').replace(/"/g,'&quot;')+'">'+inc.title+'</td>' +`
### Repository references
- `templates/enterprise/intelligence.html:590` — `const recs = rawRecs.map(rec => String(rec).replace(/(\d+\.\d{2,})%/g, (m, p1) => parseFloat(p1).toFixed(1) + '%'));`
- `templates/enterprise/intelligence.html:862` — `statsHtml += '<span style="color: var(--text-muted, #94a3b8);">' + kv[0].replace(/_/g,' ').substring(0,18) + '</span>';`
- `templates/enterprise/intelligence.html:935` — `statsHtml += '<span style="color: var(--text-muted, #94a3b8);">' + kv[0].replace(/_/g,' ').substring(0,18) + '</span>';`
- `templates/enterprise/intelligence.html:1020` — `'<td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="'+(inc.description||'').replace(/"/g,'&quot;')+'">'+inc.title+'</td>' +`
- `templates/enterprise/admin_portfolio_analyzer.html:798` — `document.getElementById('report-content').innerHTML = data.markdown.replace(/\n/g, '<br>');`
- `templates/enterprise/admin_signals.html:319` — `return `<tr data-signal-row="1" data-instrument="${String(s.symbol || '').replace(/"/g, '&quot;').toUpperCase()} ${String(humanTitle || '').replace(/"/g, '&quot;').toUpperCase()}" data-time="${String(s.timestamp || '').replace(/"/g, '&quot;').toUpperCase()}" data-category="${String(s.category || '').replace(/"/g, '&quot;').toUpperCase()}" data-action="${String(s.direction || '').replace(/"/g, '&quot;').toUpperCase()}" data-score="${Number(s.score || 0)}" data-status="${String(s.status || '').rep`
- `templates/enterprise/admin_users.html:489` — `const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, ch => ({`
- `templates/enterprise/admin_users.html:685` — `const esc = v => String(v ?? '-').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));`
- `templates/enterprise/metrics_trend.html:354` — `return String(v).replace(/[&<>"']/g, c => (`
- `templates/enterprise/profile.html:642` — `document.getElementById('permTierText').textContent = p.min_signal_tier.replace(/_/g, ' ');`
- `static/vendor/tailwind.min.js:1` — `(()=>{var qv=Object.create;var Hi=Object.defineProperty;var $v=Object.getOwnPropertyDescriptor;var Lv=Object.getOwnPropertyNames;var Mv=Object.getPrototypeOf,Nv=Object.prototype.hasOwnProperty;var df=r=>Hi(r,"__esModule",{value:!0});var hf=r=>{if(typeof require!="undefined")return require(r);throw new Error('Dynamic require of "'+r+'" is not supported')};var P=(r,e)=>()=>(r&&(e=r(r=0)),e);var x=(r,e)=>()=>(e||r((e={exports:{}}).exports,e),e.exports),Ge=(r,e)=>{df(r);for(var t in e)Hi(r,t,{get:e[`
- `static/vendor/tailwind.min.js:2` — ``+S+n("^")}let b=i(h.replace(/\d/g," "))+f.slice(0,this.column-1).replace(/[^\t]/g," ");return n(">")+i(h)+s(f)+``
- `static/vendor/tailwind.min.js:14` — ``)&&(t=t.replace(/[^\n]+$/,"")),!1}),t&&(t=t.replace(/\S/g,"")),t}rawBeforeComment(e,t){let i;return e.walkComments(n=>{if(typeof n.raws.before!="undefined")return i=n.raws.before,i.includes(``
- `static/vendor/tailwind.min.js:15` — ``)&&(i=i.replace(/[^\n]+$/,"")),!1}),typeof i=="undefined"?i=this.raw(t,null,"beforeDecl"):i&&(i=i.replace(/\S/g,"")),i}rawBeforeDecl(e,t){let i;return e.walkDecls(n=>{if(typeof n.raws.before!="undefined")return i=n.raws.before,i.includes(``
- `static/vendor/tailwind.min.js:16` — ``)&&(i=i.replace(/[^\n]+$/,"")),!1}),typeof i=="undefined"?i=this.raw(t,null,"beforeRule"):i&&(i=i.replace(/\S/g,"")),i}rawBeforeOpen(e){let t;return e.walk(i=>{if(i.type!=="decl"&&(t=i.raws.between,typeof t!="undefined"))return!1}),t}rawBeforeRule(e){let t;return e.walk(i=>{if(i.nodes&&(i.parent!==e||e.first!==i)&&typeof i.raws.before!="undefined")return t=i.raws.before,t.includes(``
- `static/vendor/tailwind.min.js:17` — ``)&&(t=t.replace(/[^\n]+$/,"")),!1}),t&&(t=t.replace(/\S/g,"")),t}rawColon(e){let t;return e.walkDecls(i=>{if(typeof i.raws.between!="undefined")return t=i.raws.between.replace(/[^\s:]/g,""),!1}),t}rawEmptyBody(e){let t;return e.walk(i=>{if(i.nodes&&i.nodes.length===0&&(t=i.raws.after,typeof t!="undefined"))return!1}),t}rawIndent(e){if(e.raws.indent)return e.raws.indent;let t;return e.walk(i=>{let n=i.parent;if(n&&n!==e&&n.parent&&n.parent===e&&typeof i.raws.before!="undefined"){let s=i.raws.bef`
- `static/vendor/tailwind.min.js:18` — ``);return t=s[s.length-1],t=t.replace(/\S/g,""),!1}}),t}rawSemicolon(e){let t;return e.walk(i=>{if(i.nodes&&i.nodes.length&&i.last.type==="decl"&&(t=i.raws.semicolon,typeof t!="undefined"))return!1}),t}rawValue(e,t){let i=e[t],n=e.raws[t];return n&&n.value===i?n.raw:i}root(e){this.body(e),e.raws.after&&this.builder(e.raws.after)}rule(e){this.block(e,this.rawValue(e,"selector")),e.raws.ownSemicolon&&this.builder(e.raws.ownSemicolon,e,"end")}stringify(e,t){if(!this[e.type])throw new Error("Unknown`
- `static/vendor/tailwind.min.js:20` — ``?(t=1,i+=1):t+=1;return{column:t,line:i}}prev(){if(!this.parent)return;let e=this.parent.index(this);return this.parent.nodes[e-1]}rangeBy(e){let t={column:this.source.start.column,line:this.source.start.line},i=this.source.end?{column:this.source.end.column+1,line:this.source.end.line}:{column:t.column+1,line:t.line};if(e.word){let s=this.source.input.css.slice(Wr(this.source.input.css,this.source.start),Wr(this.source.input.css,this.source.end)).indexOf(e.word);s!==-1&&(t=this.positionInside(`
- `static/vendor/tailwind.min.js:23` — ``.charCodeAt(0),ti=" ".charCodeAt(0),wn="\f".charCodeAt(0),vn="	".charCodeAt(0),xn="\r".charCodeAt(0),Wx="[".charCodeAt(0),Gx="]".charCodeAt(0),Qx="(".charCodeAt(0),Yx=")".charCodeAt(0),Kx="{".charCodeAt(0),Xx="}".charCodeAt(0),Zx=";".charCodeAt(0),Jx="*".charCodeAt(0),e1=":".charCodeAt(0),t1="@".charCodeAt(0),kn=/[\t\n\f\r "#'()/;[\\\]{}]/g,Sn=/[\t\n\f\r !"#'():;@[\\\]{}]|\/(?=\*)/g,r1=/.[\r\n"'(/\\]/,Zc=/[\da-f]/i;Jc.exports=function(e,t={}){let i=e.css.valueOf(),n=t.ignoreErrors,s,a,o,l,c,f,d`
- `static/vendor/tailwind.min.js:26` — `In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`)}function yk(r,e){if(!!r){if(typeof r=="string")return Np(r,e);var t=Object.prototype.toString.call(r).slice(8,-1);if(t==="Object"&&r.constructor&&(t=r.constructor.name),t==="Map"||t==="Set")return Array.from(r);if(t==="Arguments"||/^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(t))return Np(r,e)}}function Np(r,e){(e==null||e>r.length)&&(e=r.length);for(var t=0,i=new Array(e);t<e;t++)i[t]=r[t];return i}function B`
- `static/vendor/tailwind.min.js:27` — ``),v=y.length-1,v>0?(k=a+v,S=w-y[v].length):(k=a,S=s),T=D.comment,a=k,p=k,d=w-S):c===D.slash?(w=o,T=c,p=a,d=o-s,l=w+1):(w=OA(t,o),T=D.word,p=a,d=w-s),l=w+1;break}e.push([T,a,o-s,p,d,o,l]),S&&(s=S,S=null),o=l}return e}});var kd=x((ki,xd)=>{u();"use strict";ki.__esModule=!0;ki.default=void 0;var IA=je(Da()),fo=je($a()),DA=je(Na()),md=je(Fa()),qA=je(za()),$A=je(Ha()),co=je(Ga()),LA=je(Ya()),gd=Vn(to()),MA=je(io()),po=je(so()),NA=je(oo()),BA=je(fd()),O=Vn(hd()),q=Vn(lo()),FA=Vn(Se()),ue=ii(),Vt,ho;f`
- `static/vendor/tailwind.min.js:31` — ``);w.push(`  Use \`${r.replace("[",`[${E}:`)}\` for \`${T.trim()}\``);break}G.warn([`The class \`${r}\` is ambiguous and matches multiple utilities.`,...w,`If this is content and not a class, replace it with \`${r.replace("[","&lsqb;").replace("]","&rsqb;")}\` to silence this warning.`]);continue}}o=o.map(p=>p.filter(h=>Eh(h[1])))}o=o.flat(),o=Array.from(P_(o,i)),o=k_(o,e),s&&(o=S_(o,i));for(let p of n)o=A_(p,o,e);for(let p of o)p[1].raws.tailwind={...p[1].raws.tailwind,candidate:r},p=I_(p,{cont`
- `static/vendor/tailwind.min.js:32` — ``,CHAR_NO_BREAK_SPACE:"\xA0",CHAR_PERCENT:"%",CHAR_PLUS:"+",CHAR_QUESTION_MARK:"?",CHAR_RIGHT_ANGLE_BRACKET:">",CHAR_RIGHT_CURLY_BRACE:"}",CHAR_RIGHT_SQUARE_BRACKET:"]",CHAR_SEMICOLON:";",CHAR_SINGLE_QUOTE:"'",CHAR_SPACE:" ",CHAR_TAB:"	",CHAR_UNDERSCORE:"_",CHAR_VERTICAL_LINE:"|",CHAR_ZERO_WIDTH_NOBREAK_SPACE:"\uFEFF"}});var Nm=x((s6,Mm)=>{u();"use strict";var mE=hs(),{MAX_LENGTH:qm,CHAR_BACKSLASH:dl,CHAR_BACKTICK:gE,CHAR_COMMA:yE,CHAR_DOT:bE,CHAR_LEFT_PARENTHESES:wE,CHAR_RIGHT_PARENTHESES:vE,CH`
- `static/vendor/tailwind.min.js:33` — ``))if(n=n.trim(),!i.has(n))if(i.add(n),Li.get(e).has(n))for(let s of Li.get(e).get(n))t.add(s);else{let s=e(n).filter(o=>o!=="!*"),a=new Set(s);for(let o of a)t.add(o);Li.get(e).set(n,a)}}function T2(r,e){let t=e.offsets.sort(r),i={base:new Set,defaults:new Set,components:new Set,utilities:new Set,variants:new Set};for(let[n,s]of t)i[n.layer].add(s);return i}function Pl(r){return async e=>{let t={base:null,components:null,utilities:null,variants:null};if(e.walkAtRules(y=>{y.name==="tailwind"&&Ob`
- `static/vendor/tailwind.min.js:34` — ``))});c.push([p,d,h])}}for(let[l,[c,f]]of o){let d=[];for(let[h,b,v]of c){let y=[h,...Fg([h],e.tailwindConfig.separator)];for(let[w,k]of v){let S=xs(l),E=xs(k);if(E=E.groups.filter(R=>R.some(F=>y.includes(F))).flat(),E=E.concat(Fg(E,e.tailwindConfig.separator)),S.some(R=>E.includes(R)))throw k.error(`You cannot \`@apply\` the \`${h}\` utility here because it creates a circular dependency.`);let B=ee.root({nodes:[k.clone()]});B.walk(R=>{R.source=f}),(k.type!=="atrule"||k.type==="atrule"&&k.name!=`
- `static/vendor/tailwind.min.js:36` — ``),t}].filter(Boolean)}};Ql.exports.postcss=!0});var _y=x((Gq,Cy)=>{u();Cy.exports=Ay()});var Yl=x((Qq,Ey)=>{u();Ey.exports=()=>["and_chr 114","and_uc 15.5","chrome 114","chrome 113","chrome 109","edge 114","firefox 114","ios_saf 16.5","ios_saf 16.4","ios_saf 16.3","ios_saf 16.1","opera 99","safari 16.5","samsung 21"]});var Rs={};Ge(Rs,{agents:()=>nO,feature:()=>sO});function sO(){return{status:"cr",title:"CSS Feature Queries",stats:{ie:{"6":"n","7":"n","8":"n","9":"n","10":"n","11":"n","5.5":"n`
- `static/vendor/tailwind.min.js:44` — ``))})}displayType(e){for(let t of e.parent.nodes)if(t.prop==="display"){if(t.value.includes("flex"))return"flex";if(t.value.includes("grid"))return"grid"}return!1}gridStatus(e,t){if(!e)return!1;if(e._autoprefixerGridStatus!==void 0)return e._autoprefixerGridStatus;let i=null;if(e.nodes){let n;e.each(s=>{if(s.type==="comment"&&LO.test(s.text)){let a=/:\s*autoplace/i.test(s.text),o=/no-autoplace/i.test(s.text);typeof n!="undefined"?t.warn("Second Autoprefixer grid control comment was ignored. Auto`
- `static/vendor/tailwind.min.js:64` — ``))}gv.exports=Dr;function Dr(...r){let e;if(r.length===1&&V5(r[0])?(e=r[0],r=void 0):r.length===0||r.length===1&&!r[0]?r=void 0:r.length<=2&&(Array.isArray(r[0])||!r[0])?(e=r[1],r=r[0]):typeof r[r.length-1]=="object"&&(e=r.pop()),e||(e={}),e.browser)throw new Error("Change `browser` option to `overrideBrowserslist` in Autoprefixer");if(e.browserslist)throw new Error("Change `browserslist` option to `overrideBrowserslist` in Autoprefixer");e.overrideBrowserslist?r=e.overrideBrowserslist:e.browse`
- `static/vendor/chart.umd.min.js:19` — `*/function _t(t){return t+.5|0}const yt=(t,e,i)=>Math.max(Math.min(t,i),e);function vt(t){return yt(_t(2.55*t),0,255)}function Mt(t){return yt(_t(255*t),0,255)}function wt(t){return yt(_t(t/2.55)/100,0,1)}function kt(t){return yt(_t(100*t),0,100)}const St={0:0,1:1,2:2,3:3,4:4,5:5,6:6,7:7,8:8,9:9,A:10,B:11,C:12,D:13,E:14,F:15,a:10,b:11,c:12,d:13,e:14,f:15},Pt=[..."0123456789ABCDEF"],Dt=t=>Pt[15&t],Ct=t=>Pt[(240&t)>>4]+Pt[15&t],Ot=t=>(240&t)>>4==(15&t);function At(t){var e=(t=>Ot(t.r)&&Ot(t.g)&&Ot`
- `archive/unrelated_modules/templates/realestate/property_detail.html:448` — `email: name.toLowerCase().replace(/\s+/g,'.') + '@email.com',`
- `archive/unrelated_modules/templates/realestate/analytics.html:200` — `labels: typeKeys.map(function(k) { return k.replace(/_/g, ' '); }),`

## `/template.html`
### UI occurrences
- `static/vendor/tailwind.min.js:64` — ``))}gv.exports=Dr;function Dr(...r){let e;if(r.length===1&&V5(r[0])?(e=r[0],r=void 0):r.length===0||r.length===1&&!r[0]?r=void 0:r.length<=2&&(Array.isArray(r[0])||!r[0])?(e=r[1],r=r[0]):typeof r[r.length-1]=="object"&&(e=r.pop()),e||(e={}),e.browser)throw new Error("Change `browser` option to `overrideBrowserslist` in Autoprefixer");if(e.browserslist)throw new Error("Change `browserslist` option `
### Repository references
- `static/vendor/tailwind.min.js:64` — ``))}gv.exports=Dr;function Dr(...r){let e;if(r.length===1&&V5(r[0])?(e=r[0],r=void 0):r.length===0||r.length===1&&!r[0]?r=void 0:r.length<=2&&(Array.isArray(r[0])||!r[0])?(e=r[1],r=r[0]):typeof r[r.length-1]=="object"&&(e=r.pop()),e||(e={}),e.browser)throw new Error("Change `browser` option to `overrideBrowserslist` in Autoprefixer");if(e.browserslist)throw new Error("Change `browserslist` option to `overrideBrowserslist` in Autoprefixer");e.overrideBrowserslist?r=e.overrideBrowserslist:e.browse`