-- Market data ingestion (phase 1): ISIN per security and the raw labels of B3 events.

ALTER TABLE securities ADD COLUMN isin VARCHAR;

ALTER TABLE corporate_actions ADD COLUMN share_class VARCHAR;
ALTER TABLE corporate_actions ADD COLUMN source_label VARCHAR;  -- as published, e.g. JRS CAP PROPRIO
ALTER TABLE corporate_actions ADD COLUMN related_to VARCHAR;    -- e.g. 2º Trimestre/2026
