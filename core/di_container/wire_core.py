"""Core wire functions for the DI container.

Contains: wire_mediator_services, wire_multi_asset_dispatcher
"""

from __future__ import annotations

from typing import Any

from core.di_container.container import DIContainer, _get_container


def wire_mediator_services(container_instance: DIContainer | None = None) -> None:
    """Register Mediator pattern components into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.patterns.mediator import Mediator, MediatorConfig, get_mediator
        if not c.is_registered(Mediator):
            try:
                from index_app.domains.config.manager import ConfigManager as _CM
                cfg_mgr = c.try_resolve(_CM)
                raw_cfg = cfg_mgr.to_dict() if hasattr(cfg_mgr, 'to_dict') else {}
                mediator_cfg = MediatorConfig(
                    enable_logging=bool(raw_cfg.get("mediator_enable_logging", True)),
                    enable_timing=bool(raw_cfg.get("mediator_enable_timing", True)),
                    enable_validation=bool(raw_cfg.get("mediator_enable_validation", True)),
                    enable_retry=bool(raw_cfg.get("mediator_enable_retry", False)),
                    enable_auth=bool(raw_cfg.get("mediator_enable_auth", False)),
                    publish_events=bool(raw_cfg.get("mediator_publish_events", True)),
                    max_retries=int(raw_cfg.get("mediator_max_retries", 3)),
                )
            except ImportError:
                mediator_cfg = MediatorConfig()
            mediator = get_mediator(mediator_cfg)
            c.register_instance(Mediator, mediator)
    except ImportError:
        pass


def wire_multi_asset_dispatcher(container_instance: DIContainer | None = None) -> None:
    """Register Multi-Asset Strategy Dispatcher into the DI container."""
    c = _get_container(container_instance)
    try:
        from core.strategy.multi_asset_dispatcher import (
            MultiAssetStrategyDispatcher,
            get_dispatcher_with_all_engines,
        )
        if not c.is_registered(MultiAssetStrategyDispatcher):
            cfg: dict[str, Any] = {}
            try:
                from index_app.domains.config.manager import ConfigManager as _CM
                cfg_mgr = c.try_resolve(_CM)
                if cfg_mgr is not None:
                    raw = cfg_mgr.to_dict() if hasattr(cfg_mgr, "to_dict") else {}
                    if isinstance(raw, dict):
                        cfg = raw
            except (ImportError, ValueError, TypeError, RuntimeError, AttributeError):
                pass
            dispatcher = get_dispatcher_with_all_engines(config=cfg)
            c.register_instance(MultiAssetStrategyDispatcher, dispatcher)
    except (ImportError, ValueError, TypeError, RuntimeError, AttributeError):
        pass


__all__ = [
    "wire_mediator_services",
    "wire_multi_asset_dispatcher",
]
