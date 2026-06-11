"""
Batch convert remaining 'except Exception as X:' blocks to two-tier typed pattern.
SAFE MODE: Only makes changes that have been proven safe by previous manual conversions.
"""
import re
from pathlib import Path

# Files already converted or skipped
ALREADY_DONE = {
    "core/yf_data_provider.py", "core/telegram_queue.py", "core/execution_guards.py",
    "core/report_generator.py", "core/sensitivity_analyzer.py", "core/signal_autopsy.py",
    "core/trade_replayer.py", "core/var_calculator.py", "core/pnl_attribution.py",
    "core/fii_dii_tracker.py",
}

# Exception types for different contexts
DB_TYPES = "(ValueError, TypeError, KeyError, AttributeError, IndexError, OSError)"
NET_TYPES = "(ValueError, TypeError, KeyError, AttributeError, IndexError, ConnectionError, TimeoutError, OSError)"
BASIC_TYPES = "(ValueError, TypeError, KeyError, AttributeError, OSError)"

def choose_types(filepath: str, context: str) -> str:
    """Choose appropriate exception types based on context."""
    net_keywords = ["http", "fetch", "request", "url", "socket", "connect", "network", "yfinance", "yahoo", "download", "ticker"]
    if any(kw in context.lower() for kw in net_keywords):
        return NET_TYPES
    if any(kw in context.lower() for kw in ["db", "sql", "database", "query"]):
        return DB_TYPES
    return BASIC_TYPES

def convert_file(filepath: Path) -> int:
    """Convert a single file. Returns number of blocks converted."""
    content = filepath.read_text(encoding="utf-8", errors="replace")
    lines = content.split("\n")
    
    # Skip if already has typed patterns
    if "except (ValueError, TypeError" in content:
        return 0
    
    converted = 0
    new_lines = list(lines)
    offset = 0
    
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)except\s+Exception\s+as\s+(\w+)\s*:\s*$', line)
        if not m:
            continue
        
        indent = m.group(1)
        var_name = m.group(2)
        
        # Find the handler lines
        handler_start = i + 1
        if handler_start >= len(lines):
            continue
        
        # Count handler lines until next except/other block
        handler_end = handler_start
        while handler_end < len(lines):
            l = lines[handler_end]
            stripped_l = l.strip()
            if stripped_l.startswith(("except ", "def ", "class ", "@", "if ", "elif ", "else:")):
                break
            if stripped_l == "" and handler_end > handler_start + 5:
                break  # Don't go past blank lines deep in the block
            handler_end += 1
        
        handler_lines = lines[handler_start:handler_end]
        if not handler_lines:
            continue
        
        # Check if already has logging
        has_logging = any(
            any(fn in hl for fn in ["_log.", "log.", "logger.", "self._logger"])
            for hl in handler_lines
        )
        
        # Choose exception types based on file context
        context = filepath.read_text(encoding="utf-8", errors="replace")[:500]
        typed = choose_types(str(filepath), context)
        
        # Replace the except line
        new_except = f"{indent}except {typed} as {var_name}:"
        new_lines[i + offset] = new_except
        
        if has_logging:
            # Add second tier with Exception fallback
            # Find the log line to replicate its message
            log_line = ""
            for hl in handler_lines:
                for fn in ["_log.", "log.", "logger.", "self._logger"]:
                    if fn in hl:
                        log_line = hl.strip()
                        break
            
            # Extract the log message if possible
            log_msg_match = re.search(r'"[^"]*"', log_line)
            log_msg = log_msg_match.group(0) if log_msg_match else '"Error"'
            
            # Create second tier
            second_except = f"\n{indent}except Exception as {var_name}:"
            unexpected_log_line = f"{indent}    _log.warning('Exception (unexpected: %s): %s', type({var_name}).__name__, {var_name})"
            
            # Insert after handler lines
            insert_pos = i + offset + len(handler_lines)
            new_lines.insert(insert_pos, unexpected_log_line)
            offset += 1
            new_lines.insert(insert_pos + 1, second_except)
            offset += 1
        else:
            # No logging - simple typed replacement is sufficient
            pass
        
        converted += 1
    
    if converted > 0:
        filepath.write_text("\n".join(new_lines), encoding="utf-8")
        
    return converted


def main():
    root = Path(__file__).resolve().parent.parent
    
    # Scan core/ subdirectories
    total = 0
    files_modified = 0
    
    for f in sorted(root.rglob("core/**/*.py")):
        if "__pycache__" in f.parts or ".git" in f.parts:
            continue
        
        rel = str(f.relative_to(root))
        if rel in ALREADY_DONE:
            continue
        if f.name == "__init__.py":
            continue
        
        try:
            n = convert_file(f)
            if n > 0:
                print(f"  CONVERTED {n} blocks: {rel}")
                total += n
                files_modified += 1
        except Exception as e:
            print(f"  ERROR {rel}: {e}")
    
    print(f"\nTotal: {total} blocks converted in {files_modified} files")

if __name__ == "__main__":
    main()
