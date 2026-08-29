# Workflow — Visual Regression & Quality Assurance

## Purpose
Automated and visual quality assurance pipeline to verify design system integrity and zero backend regression.

## Pre-Release QA Pipeline
1. **Jinja2 Template Compilation**:
   ```bash
   python -c "import jinja2, glob, os; env = jinja2.Environment(loader=jinja2.FileSystemLoader('templates/enterprise')); [env.get_template(os.path.relpath(f, 'templates/enterprise').replace('\\', '/')).render(nonce='x', user={'username': 'admin', 'role': 'admin'}, error=None, current_page='dashboard') for f in glob.glob('templates/enterprise/**/*.html', recursive=True) if not f.endswith('whats_new.html')]"
   ```
2. **Enterprise Dashboard Page Tests**:
   ```bash
   pytest tests/test_enterprise_dashboard_pages.py -v
   ```
3. **Preguard & Postguard Compliance**:
   ```bash
   python scripts/pre_implementation_check.py --verify-analysis
   ```
4. **Link & Route Verification**: Confirm all 30 routes in the 6-tier IA navigation point to valid existing endpoints.
