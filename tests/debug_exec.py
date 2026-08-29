import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from unittest.mock import Mock

from core.ports.execution.execution_port import OrderRequest, OrderType
from core.services.execution_service import ExecutionService, ExecutionServiceConfig

print('Creating broker mock')
broker_mock = Mock()
expected = type('R', (), {'order_id':'order_123','status':None})

# Construct an OrderResult-like object
from core.ports.execution.execution_port import OrderResult, OrderStatus

expected_result = OrderResult(order_id='order_123', status=OrderStatus.FILLED, filled_quantity=50, average_price=22000.0)

broker_mock.place_order.return_value = expected_result
print('Creating service')
service = ExecutionService(broker_port=broker_mock, config=ExecutionServiceConfig())
print('Calling execute_order')
order_request = OrderRequest(symbol='NIFTY24SepFUT', direction='BUY', strike_price=22000.0, lot_size=50, order_type=OrderType.MARKET, strategy_id='test')
res = service.execute_order(order_request)
print('Result:', res)
print('Done')
