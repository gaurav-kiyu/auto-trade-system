"""Cross-Module Integrations - wiring new modules into existing patterns.

This package contains integration bridges that connect the 10 new
Architecture Standard modules with the existing platform patterns:

1. event_bus_mediator   - Wire Event Bus into Mediator's publish()
2. cqrs_event_sourcing  - Auto-append events to Event Store from CQRS
3. plugin_strategy      - Register strategies via Plugin Registry
4. secrets_config       - Config pulls from Secrets Vault with vault:// prefix
5. tracing_mediator     - Auto-wrap command/query execution with tracing spans
6. security_feeds       - Feed Threat Intel + Vuln findings into Security Auditor
7. feature_flag_guards  - Guard module behavior with Feature Flags
"""

from core.integrations.cqrs_event_sourcing import wire_cqrs_to_event_sourcing
from core.integrations.event_bus_mediator import wire_event_bus_to_mediator
from core.integrations.feature_flag_guards import FeatureFlagGuard, wire_feature_flag_guards
from core.integrations.plugin_strategy import wire_plugin_to_strategy
from core.integrations.secrets_config import SecretsConfigBridge, wire_secrets_to_config
from core.integrations.security_feeds import wire_security_feeds
from core.integrations.tracing_mediator import wire_tracing_to_mediator

__all__ = [
    "wire_event_bus_to_mediator",
    "wire_cqrs_to_event_sourcing",
    "wire_plugin_to_strategy",
    "SecretsConfigBridge",
    "wire_secrets_to_config",
    "wire_tracing_to_mediator",
    "wire_security_feeds",
    "FeatureFlagGuard",
    "wire_feature_flag_guards",
]
