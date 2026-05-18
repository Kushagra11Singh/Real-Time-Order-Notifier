-- ─────────────────────────────────────────────────────────────────
--  Orders table + Change-Data-Capture trigger
--  PostgreSQL NOTIFY payload is capped at 8 KB.
--  For very large rows, the trigger would instead notify with just
--  the primary key and the application would re-fetch from the DB.
--  Our row is small so we embed the full payload directly.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS orders (
    id            SERIAL PRIMARY KEY,
    customer_name VARCHAR(255)  NOT NULL,
    product_name  VARCHAR(255)  NOT NULL,
    status        VARCHAR(50)   NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'shipped', 'delivered')),
    updated_at    TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- ─────────────────────────────────────────────────────────────────
--  Trigger function: fires on INSERT / UPDATE / DELETE and emits
--  a JSON payload to the 'order_changes' channel.
-- ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION notify_order_change()
RETURNS TRIGGER AS $$
DECLARE
    payload JSON;
BEGIN
    IF TG_OP = 'DELETE' THEN
        payload := json_build_object(
            'event',     TG_OP,
            'table',     TG_TABLE_NAME,
            'timestamp', extract(epoch from NOW())::bigint,
            'data',      row_to_json(OLD)
        );
    ELSE
        payload := json_build_object(
            'event',     TG_OP,
            'table',     TG_TABLE_NAME,
            'timestamp', extract(epoch from NOW())::bigint,
            'data',      row_to_json(NEW)
        );
    END IF;

    -- pg_notify silently drops payloads larger than 8 KB.
    -- Guard: if the serialised row is too large, send only the primary key
    -- and a flag so the application can re-fetch the full row via REST.
    IF length(payload::text) > 7000 THEN
        payload := json_build_object(
            'event',     TG_OP,
            'table',     TG_TABLE_NAME,
            'timestamp', extract(epoch from NOW())::bigint,
            'truncated', true,
            'data',      json_build_object('id', COALESCE(NEW.id, OLD.id))
        );
    END IF;

    PERFORM pg_notify('order_changes', payload::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- Drop and recreate to keep the definition idempotent
DROP TRIGGER IF EXISTS orders_change_trigger ON orders;

CREATE TRIGGER orders_change_trigger
    AFTER INSERT OR UPDATE OR DELETE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION notify_order_change();
