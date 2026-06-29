import ast
import os

missing = []
total = 0
init_count = 0
for root, dirs, files in os.walk('index_app'):
    if '__pycache__' in dirs:
        dirs.remove('__pycache__')
    for f in files:
        if not f.endswith('.py'):
            continue
        fp = os.path.join(root, f)
        total += 1
        if f == '__init__.py':
            init_count += 1
            continue

        try:
            with open(fp, encoding='utf-8', errors='replace') as file:
                content = file.read()

            tree = ast.parse(content)
            has_module_level = any(
                isinstance(n, ast.Assign) and
                any(isinstance(t, ast.Name) and t.id == '__all__' for t in n.targets)
                for n in ast.iter_child_nodes(tree)
            )

            if not has_module_level:
                missing.append(os.path.relpath(fp))
        except Exception:
            missing.append(os.path.relpath(fp))

print(f'Total .py files: {total} ({init_count} __init__.py, {total-init_count} non-init)')
print(f'Missing __all__: {len(missing)}')
for m in missing:
    print(f'  {m}')
