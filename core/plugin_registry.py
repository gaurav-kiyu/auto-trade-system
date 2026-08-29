"""Plugin Registry — Extensible Plugin Architecture (Constitution v4.0).

Provides a plugin registry for third-party extensions including strategy plugins,
broker plugins, data source plugins, and notification plugins. Supports lifecycle
management (load, enable, disable, unload), version compatibility checks, and
dependency resolution.

Architecture Standard: Plugin Architecture
Constitution Principle: Everything as Code, Continuous Improvement

Usage:
    from core.plugin_registry import get_plugin_registry

    registry = get_plugin_registry()

    # Register a plugin class
    registry.register_plugin("my_strategy_v2", MyStrategyPlugin, version="2.0.0")

    # Load and enable a plugin
    plugin = registry.load_plugin("my_strategy_v2")
    registry.enable_plugin("my_strategy_v2")

    # Get all enabled plugins of a type
    strategies = registry.get_enabled_plugins(plugin_type="strategy")
"""

from __future__ import annotations

import importlib
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger(__name__)


# ── Constants ──────────────────────────────────────────────────────────────

PLUGIN_TYPES = ("strategy", "broker", "data_source", "notification", "signal", "indicator", "other")


# ── Data Models ──────────────────────────────────────────────────────────────


@dataclass
class PluginMeta:
    """Metadata for a registered plugin."""

    name: str = ""
    version: str = "1.0.0"
    plugin_type: str = "other"
    description: str = ""
    author: str = ""
    dependencies: list[str] = field(default_factory=list)
    min_core_version: str = "2.54.0"
    tags: list[str] = field(default_factory=list)
    homepage: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "plugin_type": self.plugin_type,
            "description": self.description[:200],
            "author": self.author,
            "dependencies": self.dependencies,
            "min_core_version": self.min_core_version,
            "tags": self.tags,
            "homepage": self.homepage,
        }


@dataclass
class PluginEntry:
    """A registered plugin entry (class + metadata + state)."""

    meta: PluginMeta = field(default_factory=PluginMeta)
    plugin_class: type | None = None
    instance: Any = None
    enabled: bool = False
    loaded: bool = False
    load_error: str = ""
    loaded_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta": self.meta.to_dict(),
            "enabled": self.enabled,
            "loaded": self.loaded,
            "load_error": self.load_error,
            "loaded_at": self.loaded_at,
        }


# ── Plugin Registry ─────────────────────────────────────────────────────────


class PluginRegistry:
    """Manages plugin registration, loading, and lifecycle.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._plugins: dict[str, PluginEntry] = {}

    # ── Registration ──────────────────────────────────────────────────────

    def register_plugin(
        self,
        name: str,
        plugin_class: type | None = None,
        version: str = "1.0.0",
        plugin_type: str = "other",
        description: str = "",
        author: str = "",
        dependencies: list[str] | None = None,
        min_core_version: str = "2.54.0",
        tags: list[str] | None = None,
        homepage: str = "",
    ) -> PluginEntry:
        """Register a plugin by name and optional class.

        If plugin_class is None, the plugin must be loaded later via
        load_plugin() with a module path.

        Args:
            name: Unique plugin identifier.
            plugin_class: Optional plugin class.
            version: Semantic version string.
            plugin_type: Type category (strategy, broker, etc.).
            description: Short description.
            author: Plugin author.
            dependencies: List of plugin name dependencies.
            min_core_version: Minimum core version required.
            tags: Freeform tags.
            homepage: Project homepage URL.

        Returns:
            The PluginEntry.
        """
        if plugin_type not in PLUGIN_TYPES:
            plugin_type = "other"

        meta = PluginMeta(
            name=name.strip(),
            version=version.strip(),
            plugin_type=plugin_type,
            description=description.strip(),
            author=author.strip(),
            dependencies=[d.strip() for d in (dependencies or []) if d.strip()],
            min_core_version=min_core_version.strip(),
            tags=[t.strip().lower() for t in (tags or []) if t.strip()],
            homepage=homepage.strip(),
        )

        with self._lock:
            entry = PluginEntry(
                meta=meta,
                plugin_class=plugin_class,
                enabled=False,
                loaded=False,
            )
            self._plugins[name] = entry

        _log.info("[PLUGIN] Registered plugin '%s' v%s (type=%s)", name, version, plugin_type)
        return entry

    def unregister_plugin(self, name: str) -> bool:
        """Unregister a plugin.

        Returns True if removed, False if not found.
        """
        with self._lock:
            if name in self._plugins:
                del self._plugins[name]
                return True
            return False

    def get_plugin(self, name: str) -> PluginEntry | None:
        """Get a plugin entry by name."""
        with self._lock:
            return self._plugins.get(name)

    def list_plugins(self, plugin_type: str = "", enabled_only: bool = False,
                     tag: str = "") -> list[PluginEntry]:
        """List registered plugins with optional filters."""
        with self._lock:
            entries = list(self._plugins.values())

        if plugin_type:
            entries = [e for e in entries if e.meta.plugin_type == plugin_type]
        if enabled_only:
            entries = [e for e in entries if e.enabled]
        if tag:
            clean_tag = tag.lower()
            entries = [e for e in entries if clean_tag in e.meta.tags]

        return entries

    def get_plugins_by_type(self) -> dict[str, list[PluginEntry]]:
        """Get plugins grouped by type."""
        with self._lock:
            result: dict[str, list[PluginEntry]] = {}
            for entry in self._plugins.values():
                t = entry.meta.plugin_type
                if t not in result:
                    result[t] = []
                result[t].append(entry)
            return result

    # ── Plugin Lifecycle ──────────────────────────────────────────────────

    def load_plugin(self, name: str, module_path: str = "") -> bool:
        """Load a plugin by name.

        If the plugin was registered with a class, uses that.
        Otherwise, imports the module path to discover the plugin class.

        Args:
            name: Plugin name.
            module_path: Optional module path for dynamic import.

        Returns:
            True if loaded successfully.
        """
        with self._lock:
            entry = self._plugins.get(name)
            if entry is None:
                _log.warning("[PLUGIN] Cannot load unknown plugin '%s'", name)
                return False

            if entry.loaded:
                return True

            # Check version compatibility
            if not self._check_version_compatibility(entry.meta.min_core_version):
                entry.load_error = "Core version too old"
                _log.warning("[PLUGIN] '%s' requires core >= %s", name, entry.meta.min_core_version)
                return False

            # Check dependencies
            for dep in entry.meta.dependencies:
                dep_entry = self._plugins.get(dep)
                if dep_entry is None or not dep_entry.loaded or not dep_entry.enabled:
                    entry.load_error = f"Dependency not satisfied: {dep}"
                    _log.warning("[PLUGIN] '%s' dependency '%s' not satisfied", name, dep)
                    return False

            # Load from class or module path
            try:
                if entry.plugin_class is not None:
                    entry.instance = entry.plugin_class()
                elif module_path:
                    mod = importlib.import_module(module_path)
                    # Look for the plugin class (name -> PascalCase convention)
                    cls_name = "".join(part.capitalize() for part in name.replace("-", "_").split("_"))
                    if hasattr(mod, cls_name):
                        cls = getattr(mod, cls_name)
                        entry.plugin_class = cls
                        entry.instance = cls()
                    else:
                        entry.load_error = f"Class '{cls_name}' not found in {module_path}"
                        return False
                else:
                    entry.load_error = "No plugin class or module path provided"
                    return False

                entry.loaded = True
                entry.loaded_at = time.time()
                _log.info("[PLUGIN] Loaded plugin '%s' v%s", name, entry.meta.version)
                return True

            except Exception as exc:
                entry.load_error = f"{type(exc).__name__}: {exc}"
                _log.warning("[PLUGIN] Failed to load '%s': %s", name, exc)
                return False

    def enable_plugin(self, name: str) -> bool:
        """Enable a loaded plugin.

        Returns True if enabled, False if not found or not loaded.
        """
        with self._lock:
            entry = self._plugins.get(name)
            if entry is None:
                return False
            if not entry.loaded:
                entry.load_error = "Must load before enabling"
                return False
            entry.enabled = True
            # Call on_enable lifecycle hook if exists
            if entry.instance and hasattr(entry.instance, "on_enable"):
                try:
                    entry.instance.on_enable()
                except Exception as exc:
                    _log.warning("[PLUGIN] '%s' on_enable error: %s", name, exc)
            return True

    def disable_plugin(self, name: str) -> bool:
        """Disable a plugin.

        Returns True if disabled, False if not found.
        """
        with self._lock:
            entry = self._plugins.get(name)
            if entry is None:
                return False
            if not entry.enabled:
                return True
            entry.enabled = False
            # Call on_disable lifecycle hook if exists
            if entry.instance and hasattr(entry.instance, "on_disable"):
                try:
                    entry.instance.on_disable()
                except Exception as exc:
                    _log.warning("[PLUGIN] '%s' on_disable error: %s", name, exc)
            return True

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin (disables and clears instance).

        Returns True if unloaded, False if not found.
        """
        with self._lock:
            entry = self._plugins.get(name)
            if entry is None:
                return False
            entry.enabled = False
            entry.loaded = False
            entry.instance = None
            entry.load_error = ""
            return True

    def reload_plugin(self, name: str, module_path: str = "") -> bool:
        """Reload a plugin (unload + load).

        Returns True if reloaded successfully.
        """
        self.unload_plugin(name)
        return self.load_plugin(name, module_path)

    def get_enabled_plugins(self, plugin_type: str = "") -> list[PluginEntry]:
        """Get all enabled plugins, optionally filtered by type."""
        return self.list_plugins(plugin_type=plugin_type, enabled_only=True)

    def call_plugin_method(self, name: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call a method on a specific plugin instance.

        Args:
            name: Plugin name.
            method: Method name to call.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            Method return value, or None if plugin not enabled/loaded.
        """
        with self._lock:
            entry = self._plugins.get(name)
            if entry is None or not entry.enabled or entry.instance is None:
                return None
            if not hasattr(entry.instance, method):
                return None
            try:
                fn = getattr(entry.instance, method)
                return fn(*args, **kwargs)
            except Exception as exc:
                _log.warning("[PLUGIN] Method '%s' on '%s' failed: %s", method, name, exc)
                return None

    # ── Statistics ─────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        """Get plugin registry statistics."""
        with self._lock:
            total = len(self._plugins)
            enabled_count = sum(1 for p in self._plugins.values() if p.enabled)
            loaded_count = sum(1 for p in self._plugins.values() if p.loaded)
            error_count = sum(1 for p in self._plugins.values() if p.load_error)

            by_type: dict[str, int] = {}
            for p in self._plugins.values():
                t = p.meta.plugin_type
                by_type[t] = by_type.get(t, 0) + 1

            return {
                "total_plugins": total,
                "enabled": enabled_count,
                "loaded": loaded_count,
                "errors": error_count,
                "by_type": by_type,
                "versions": {
                    name: entry.meta.version
                    for name, entry in self._plugins.items()
                },
            }

    # ── Internal ──────────────────────────────────────────────────────────

    def _check_version_compatibility(self, min_version: str) -> bool:
        """Check if the current core version meets the minimum requirement.

        Simple tuple-based version comparison (e.g., '2.54.0').
        """
        try:
            # Get current version from VERSION file
            from pathlib import Path
            ver_file = Path("VERSION")
            if ver_file.is_file():
                core_ver = ver_file.read_text().strip()
            else:
                return True  # No version file = no restriction

            def _parse(v: str) -> tuple[int, ...]:
                return tuple(int(p) for p in v.split("."))

            return _parse(core_ver) >= _parse(min_version)
        except (ValueError, OSError, IndexError):
            return True  # Assume compatible on parse error

    def clear_all(self) -> None:
        """Clear all plugins (for testing)."""
        with self._lock:
            self._plugins.clear()


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli() -> None:
    import argparse
    ap = argparse.ArgumentParser(
        prog="python -m core.plugin_registry",
        description="Plugin Registry — Extensible plugin architecture",
    )
    ap.add_argument("--list", action="store_true", help="List all plugins")
    ap.add_argument("--register", type=str, metavar="NAME:TYPE", help="Register a plugin (e.g., 'my_plugin:strategy')")
    ap.add_argument("--enable", type=str, metavar="NAME", help="Enable a plugin")
    ap.add_argument("--disable", type=str, metavar="NAME", help="Disable a plugin")
    ap.add_argument("--stats", action="store_true", help="Show statistics")
    ap.add_argument("--json", action="store_true", help="Output as JSON")
    args = ap.parse_args()

    reg = get_plugin_registry()

    if args.list:
        plugins = reg.list_plugins()
        if args.json:
            import json
            print(json.dumps([p.to_dict() for p in plugins], indent=2))
        else:
            print(f"{'Plugin':<25} {'Type':<15} {'Version':<12} {'Status':<10}")
            print("-" * 62)
            for p in plugins:
                status = "ENABLED" if p.enabled else ("LOADED" if p.loaded else "REGISTERED")
                print(f"{p.meta.name:<25} {p.meta.plugin_type:<15} {p.meta.version:<12} {status:<10}")
        return

    if args.register:
        parts = args.register.split(":")
        name = parts[0]
        plugin_type = parts[1] if len(parts) > 1 else "other"
        entry = reg.register_plugin(name=name, plugin_type=plugin_type)
        if args.json:
            import json
            print(json.dumps(entry.to_dict(), indent=2))
        else:
            print(f"Registered: {name} (type={plugin_type})")
        return

    if args.enable:
        ok = reg.enable_plugin(args.enable)
        print(f"{'Enabled' if ok else 'Failed'}: {args.enable}")
        return

    if args.disable:
        ok = reg.disable_plugin(args.disable)
        print(f"{'Disabled' if ok else 'Not found'}: {args.disable}")
        return

    if args.stats:
        stats = reg.get_stats()
        if args.json:
            import json
            print(json.dumps(stats, indent=2))
        else:
            print("Plugin Registry Stats:")
            for k, v in stats.items():
                print(f"  {k}: {v}")
        return

    ap.print_help()


if __name__ == "__main__":
    _cli()


# ── Singleton ──────────────────────────────────────────────────────────────

_instance: PluginRegistry | None = None
_instance_lock = threading.RLock()


def get_plugin_registry() -> PluginRegistry:
    """Get the singleton PluginRegistry instance."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = PluginRegistry()
        return _instance


def reset_plugin_registry() -> None:
    """Force-reset singleton (for testing)."""
    global _instance
    with _instance_lock:
        _instance = None


__all__ = [
    "PluginEntry",
    "PluginMeta",
    "PluginRegistry",
    "get_plugin_registry",
    "reset_plugin_registry",
]
