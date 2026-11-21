-- CVM ingestion support (phase 1).

-- Conditional downloads: a file already ingested for a company is not processed again
-- while its ETag (or Last-Modified) stays the same.
ALTER TABLE source_files ADD COLUMN etag VARCHAR;

-- Which companies were loaded from each source file (files contain the whole market,
-- but only the analyzed companies and their peers are kept).
CREATE TABLE source_file_scopes (
    source_file_id UUID NOT NULL REFERENCES source_files (id),
    cnpj           VARCHAR NOT NULL,
    PRIMARY KEY (source_file_id, cnpj)
);

-- Link back to the original document on the CVM system.
ALTER TABLE filings ADD COLUMN cvm_document_id INTEGER;
ALTER TABLE filings ADD COLUMN document_url VARCHAR;

-- Raw registry data kept for traceability of the sector classification.
ALTER TABLE companies ADD COLUMN cvm_sector VARCHAR;       -- SETOR_ATIV
ALTER TABLE companies ADD COLUMN control_type VARCHAR;     -- CONTROLE_ACIONARIO (e.g. ESTATAL)
ALTER TABLE companies ADD COLUMN registration_status VARCHAR;

-- Latest value of each mapped account, expressed as a canonical contract concept.
CREATE VIEW v_concept_facts AS
SELECT
    l.cnpj,
    c.accounting_template,
    m.concept,
    l.statement,
    l.basis,
    l.account_code,
    l.account_name,
    l.period_type,
    l.period_start,
    l.period_end,
    l.value * m.sign AS value,
    l.unit,
    l.doc_type,
    l.reference_date,
    l.version,
    l.received_at,
    l.filing_id
FROM v_financial_facts_latest AS l
JOIN companies AS c ON c.cnpj = l.cnpj
JOIN account_map AS m
    ON m.accounting_template = c.accounting_template
   AND m.statement = l.statement
   AND m.account_code = l.account_code
   AND l.period_end >= m.valid_from
   AND (m.valid_to IS NULL OR l.period_end <= m.valid_to)
WHERE l.statement_column = '';
