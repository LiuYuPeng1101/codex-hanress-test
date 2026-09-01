# Order Status Rules

- `CREATED`: order has been created but is not yet paid.
- `PAID`: payment is complete and the order is waiting for processing.
- `PROCESSING`: warehouse/order processing is in progress; do not claim that the order has shipped.
- `SHIPPED`: order has left the warehouse. If an expected delivery date is available, present it as an estimate.
- `COMPLETED`: order is complete.
- `CANCELLED`: order has been cancelled.
- `NOT_FOUND`: no matching order exists. Never fabricate order details.
