# OPB Web Closure WIP14 — Functional Contract Guard

## Scope
This pass adds static regression guards for the Web production surface. It does not claim browser-level certification.

## Checks
- Enterprise templates contain no HTML inline event-handler attributes.
- Enterprise templates contain no hard-coded `localhost:8000` URLs.
- Internal enterprise `href` targets resolve against discovered FastAPI routes.
- Placeholder `href="#"` links are rejected.

## Result
`tests/test_web_closure_contract.py`: **4/4 PASS**

## Important limitation
This is a contract guard, not a substitute for authenticated browser acceptance. The next closure pass must exercise every interactive control through the browser against a running application and verify the complete request/authorization/response/DOM chain.

## Deployment
Not approved for AWS deployment from this pass alone.
