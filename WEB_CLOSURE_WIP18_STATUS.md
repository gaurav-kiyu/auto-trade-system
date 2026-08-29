# OPB Web Closure WIP18

## Focus
Granular authorization contract for every mutating Enterprise Admin API.

## Change
Added `tests/test_web_mutation_permission_contract.py` which statically requires every POST/PUT/PATCH/DELETE route in `core/enterprise_dashboard/routes/admin.py` to declare a `require_permission(...)` dependency.

## Validation
- Mutation permission contract: PASS
- Web closure contract: PASS
- Web button contract: PASS
- Web route contract: PASS
- Web runtime control contract: PASS
- Web RBAC parity: PASS
- UI screens/navigation contract: PASS
- Combined selected regression tests: 48 passed
- Python compileall: PASS

## Important boundary
This is a regression guard, not proof that every browser interaction works at runtime. WIP18 is not production-certified and has not been deployed to AWS.
