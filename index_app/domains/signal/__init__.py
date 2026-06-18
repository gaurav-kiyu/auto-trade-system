"""Signal Domain — signal evaluation, parameter construction, and result conversion.

Extracted from ``core.signal_service._evaluate_v2_signal()`` to separate
signal evaluation orchestration from the ``SignalService`` routing layer.

Provides ``SignalEvaluator`` (OI context, params, evaluation) and
``AdaptiveSignalConverter`` (result → dict).
"""
