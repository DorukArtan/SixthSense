-- Rowsetta analytics snapshot. One row of sales represents one accepted invoice line.
-- Money is stored as integer units: 1 GBP = 10,000 units.
PRAGMA foreign_keys = ON;

CREATE TABLE products (
    stock_code TEXT PRIMARY KEY NOT NULL,
    product_name TEXT,
    -- 0 for non-merchandise codes (postage, manual, fees ...); list in config/non_product_codes.json
    is_product INTEGER NOT NULL DEFAULT 1 CHECK (is_product IN (0, 1))
);

CREATE TABLE sales (
    line_id INTEGER PRIMARY KEY,
    invoice_no TEXT NOT NULL,
    invoice_at TEXT NOT NULL,
    country TEXT NOT NULL,
    stock_code TEXT NOT NULL REFERENCES products(stock_code),
    net_qty INTEGER NOT NULL CHECK (typeof(net_qty) = 'integer' AND net_qty <> 0),
    unit_price_u INTEGER NOT NULL CHECK (typeof(unit_price_u) = 'integer' AND unit_price_u > 0),
    sold_qty INTEGER GENERATED ALWAYS AS (max(net_qty, 0)) VIRTUAL,
    gross_u INTEGER GENERATED ALWAYS AS (max(net_qty, 0) * unit_price_u) VIRTUAL,
    credit_u INTEGER GENERATED ALWAYS AS (max(-net_qty, 0) * unit_price_u) VIRTUAL,
    net_u INTEGER GENERATED ALWAYS AS (net_qty * unit_price_u) VIRTUAL
);

CREATE INDEX sales_date_country ON sales(invoice_at, country);
CREATE INDEX sales_product ON sales(stock_code);
