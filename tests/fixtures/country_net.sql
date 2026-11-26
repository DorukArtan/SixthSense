SELECT country, SUM(net_u) AS net_sales_u
FROM sales
WHERE invoice_at >= :start_at AND invoice_at < :end_at
  AND country IN (:first_country, :second_country)
GROUP BY country
ORDER BY net_sales_u DESC, country ASC;
