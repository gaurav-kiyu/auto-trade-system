# OPB Web Closure WIP20

## Focus
Runtime-safe button semantics in dynamically generated enterprise UI controls.

## Finding
Static HTML button checks passed in previous WIPs, but buttons generated inside JavaScript template strings were not parsed by BeautifulSoup. Several enterprise `data-action` buttons therefore still lacked an explicit `type` attribute.

Affected templates included:
- admin_config.html
- admin_portfolio_analyzer.html
- user_signals.html
- payoff_calculator.html
- pricing_plans.html
- governance.html

## Repair
All enterprise `<button>` opening tags, including dynamically generated template-string buttons, now explicitly declare `type="button"` unless an explicit type was already present.

This prevents accidental form submission/navigation when these controls are clicked.

## Validation
- `test_web_button_contract.py`: PASS
- `test_web_closure_contract.py`: PASS
- `test_web_route_contract.py`: PASS
- `test_web_rbac_parity.py`: PASS
- `test_control_rbac.py`: PASS
- Combined selected tests: 47 passed
- Same-line button type scan: 0 missing

## Deployment
Not deployed to AWS.
Not production certified.
