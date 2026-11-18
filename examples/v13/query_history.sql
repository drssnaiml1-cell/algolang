-- Past analyst queries (used by `algo ontology discover --history` to propose measures)
SELECT customers.region, SUM(order_lines.amount) AS net_revenue FROM order_lines JOIN orders ON order_lines.order_id = orders.id JOIN customers ON orders.customer_id = customers.id GROUP BY customers.region;
SELECT AVG(order_lines.amount) AS average_line_value FROM order_lines;
SELECT SUM(order_lines.quantity * products.unit_price) - SUM(order_lines.amount) AS discount_given FROM order_lines JOIN products ON order_lines.product_id = products.id;
