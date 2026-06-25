# Fix corrupted __all__ exports across core/ modules.
# Detects __all__ inside SQL strings, f-strings, docstrings, etc.
# and moves them to proper module-level position.

import ast
import os
import re
import py_compile


def get_module_level_all(filepath):
    """Check if __all__ is defined at module level via AST."""
    with open(filepath, encoding='utf-8', errors='replace') as f:
        content = f.read()
    try:
        tree = ast.parse(content, filename=filepath)
    except SyntaxError:
        return None, content
    
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == '__all__':
                    return True, content
    return False, content


def extract_all_from_text(content):
    """Extract __all__ list text from file content."""
    lines = content.split('\n')
    all_lines = []
    in_all = False
    bracket_depth = 0
    for line in lines:
        stripped = line.strip()
        if not in_all and '__all__' in stripped and '=' in stripped and '[' in stripped:
            in_all = True
            bracket_depth = stripped.count('[') - stripped.count(']')
            all_lines.append(stripped)
        elif in_all:
            bracket_depth += stripped.count('[') - stripped.count(']')
            all_lines.append(stripped)
            if bracket_depth <= 0:
                break
    return all_lines


def insert_all_at_module(content, all_lines):
    """Insert __all__ list at module level (after imports/before code)."""
    if not all_lines:
        return content
    
    lines = content.split('\n')
    
    # Find insertion point: after last import
    insert_at = 0
    in_docstring = False
    for i, line in enumerate(lines):
        s = line.strip()
        if i == 0 and s.startswith(("'''", '"""')):
            in_docstring = True
        if in_docstring:
            if s and s[-1] in ("'", '"') and (s.startswith("'''") or s.startswith('"""')):
                if len(s) >= 3 and (s.startswith("'''") and s.endswith("'''") and len(s) > 3) or \
                   (s.startswith('"""') and s.endswith('"""') and len(s) > 3):
                    # This closes the docstring on the same line it started
                    in_docstring = False
                    insert_at = i + 1
                elif s == "'''" or s == '"""':
                    in_docstring = False
                    insert_at = i + 1
            continue
        
        if s.startswith(('import ', 'from ')):
            insert_at = i + 1
    
    # Verify we're not inserting into existing code block
    for i in range(insert_at, min(insert_at + 3, len(lines))):
        s = lines[i].strip()
        if s and not s.startswith('#') and not s.startswith(('"""', "'''")):
            if s.startswith(('@', 'class ', 'def ')):
                break
    
    # Check if __all__ already exists at module level
    for line in lines[insert_at:insert_at+5]:
        if line.strip().startswith('__all__'):
            return content  # Already exists
    
    # Insert __all__ block
    all_text = '\n'.join(all_lines)
    new_lines = lines[:insert_at]
    new_lines.append('')
    new_lines.append(all_text)
    new_lines.append('')
    new_lines.extend(lines[insert_at:])
    return '\n'.join(new_lines)


def fix_file(filepath):
    """Fix a single file. Returns (was_fixed, message)."""
    ok, content = get_module_level_all(filepath)
    if ok:
        return False, "Already has module-level __all__"
    if content is None:
        return False, "Syntax error in file"
    
    original = content
    lines = content.split('\n')
    new_lines = []
    removed_all = False
    
    # Phase 1: Remove __all__ blocks that are NOT at module level
    # Detect if we're inside a triple-quoted string
    in_triple = False
    triple_type = None
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # Track triple-quoted strings
        if not in_triple:
            if '"""' in stripped or "'''" in stripped:
                # Check if this opens a triple-quoted string
                idx = stripped.find('"""') if '"""' in stripped else stripped.find("'''")
                if idx >= 0:
                    remaining = stripped[idx:]
                    if remaining.count('"""' if '"""' in stripped else "'''") % 2 == 1:
                        in_triple = True
                        triple_type = '"""' if '"""' in stripped else "'''"
        else:
            if triple_type in stripped:
                cnt = stripped.count(triple_type)
                if cnt % 2 == 1:
                    in_triple = False
        
        # Check if this line contains a real __all__ assignment
        # that should be removed from its current location
        if '__all__' in stripped and '=' in stripped and '[' in stripped:
            indent = len(line) - len(line.lstrip())
            is_at_module_level = (indent == 0)
            is_in_triple = in_triple
            
            if is_in_triple or not is_at_module_level:
                # Skip this line and continue until the list is closed
                removed_all = True
                # Count brackets to find end of list
                depth = stripped.count('[') - stripped.count(']')
                if depth <= 0 and stripped.strip().endswith(']'):
                    # Single-line __all__ - just skip this line
                    continue
                elif depth > 0:
                    # Multi-line __all__ - skip subsequent lines until closed
                    for j in range(i + 1, len(lines)):
                        ls = lines[j].strip()
                        depth += ls.count('[') - ls.count(']')
                        if depth <= 0:
                            break
                    # Update i to skip all lines (we'll continue outer loop)
                    # Mark the file as needing those lines skipped
                    # We handle this differently - continue tracking
                    continue
                else:
                    continue
        
        new_lines.append(line)
    
    content = '\n'.join(new_lines)
    
    if not removed_all:
        # Check if this is a docstring-only pattern
        # Find __all__ text in original and extract it
        pass
    
    if content == original and removed_all:
        # The __all__ was removed, but we need to track the removed lines
        # Simpler approach: find all __all__ blocks in original, filter to module-level only
        return fix_file_v2(filepath)
    
    if removed_all:
        # Extract __all__ text from original
        all_lines = extract_all_from_text(original)
        content = insert_all_at_module(content, all_lines)
    
    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        # Verify
        ok2, _ = get_module_level_all(filepath)
        if ok2:
            return True, "Fixed"
        else:
            return False, "Fix failed verification"
    
    # If we get here, the file has __all__ text but not as module-level assignment
    # Check for docstring-only pattern
    return fix_file_v2(filepath)


def fix_file_v2(filepath):
    """Alternative fix: find __all__ text anywhere and add it at module level."""
    with open(filepath, encoding='utf-8', errors='replace') as f:
        content = f.read()
    
    # Find __all__ = [...] pattern anywhere in file (even in docstrings)
    all_match = re.search(r'__all__\s*=\s*\[.*?\]', content, re.DOTALL)
    if not all_match:
        return False, "No __all__ text found"
    
    # Remove all instances of __all__ = [...] from non-module context
    # by finding ALL occurrences and keeping only the ones at indent=0
    lines = content.split('\n')
    new_lines = []
    in_all_block = False
    kept_lines = []
    
    for line in lines:
        stripped = line.strip()
        if '__all__' in stripped and '=' in stripped and '[' in stripped:
            indent = len(line) - len(line.lstrip())
            if indent == 0:
                # This is module-level - keep it
                in_all_block = True
                kept_lines.append(stripped)
                # Continue to collect the list
                depth = stripped.count('[') - stripped.count(']')
                if depth <= 0:
                    in_all_block = False
            else:
                # Skip this and subsequent list lines
                depth = stripped.count('[') - stripped.count(']')
                if depth > 0:
                    # Multi-line, skip until closed
                    for _next_line in lines[lines.index(line)+1:]:
                        ls = _next_line.strip()
                        depth += ls.count('[') - ls.count(']')
                        if depth <= 0:
                            break
        elif in_all_block:
            kept_lines.append(stripped)
            if stripped.endswith(']') and not stripped.endswith('[]'):
                in_all_block = False
        else:
            new_lines.append(line)
    
    # Reconstruct content with module-level __all__
    if kept_lines:
        all_text = '\n'.join(kept_lines)
        content2 = insert_all_at_module('\n'.join(new_lines), [all_text])
        if content2 != '\n'.join(new_lines):
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content2)
            ok2, _ = get_module_level_all(filepath)
            if ok2:
                return True, "Fixed (v2)"
            else:
                return False, "v2 fix failed"
    
    return False, "No fixable __all__ found"


def check_syntax(filepath):
    """Check Python syntax."""
    try:
        py_compile.compile(filepath, doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def main():
    files_to_check = []
    for root, dirs, files in os.walk('core'):
        if '__pycache__' in dirs:
            dirs.remove('__pycache__')
        for fname in sorted(files):
            if fname.endswith('.py'):
                files_to_check.append(os.path.join(root, fname))
    
    print(f"Checking {len(files_to_check)} files...")
    
    fixed = 0
    failed = 0
    skipped = 0
    syntax_broken = []
    
    for filepath in files_to_check:
        try:
            ok, _ = get_module_level_all(filepath)
            if ok:
                skipped += 1
                continue
            
            success, msg = fix_file(filepath)
            if success:
                # Verify syntax
                if check_syntax(filepath):
                    fixed += 1
                    print(f"  FIXED: {filepath}")
                else:
                    syntax_broken.append(filepath)
                    failed += 1
                    print(f"  SYNTAX BROKEN: {filepath}")
            else:
                failed += 1
                # Print as debug
                # print(f"  SKIP: {filepath} - {msg}")
        except Exception as e:
            failed += 1
            syntax_broken.append(filepath)
            print(f"  ERROR: {filepath}: {e}")
    
    print(f"\n=== Summary ===")
    print(f"  Total files: {len(files_to_check)}")
    print(f"  Already have __all__: {skipped}")
    print(f"  Fixed: {fixed}")
    print(f"  Failed: {failed}")
    if syntax_broken:
        print(f"  Syntax errors: {len(syntax_broken)}")
        for f in syntax_broken:
            print(f"    {f}")
    
    return fixed, failed


if __name__ == '__main__':
    main()
