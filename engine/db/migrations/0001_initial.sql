-- Initial warehouse schema (docs/architecture.md §7).
--
-- Integrity rules:
--   * Facts are append-only: a restatement is a new filing version, never an UPDATE.
--   * Monetary values are DECIMAL, already normalized to units (CVM ESCALA_MOEDA applied).
--   * Percentages are stored as fractions (0.06 = 6%).
--   * Raw files are not kept; source_files is the manifest that makes every row traceable.

-- Ingestion manifest -------------------------------------------------------------------

CREATE TABLE ingestion_runs (
    id          UUID PRIMARY KEY DEFAULT uuid(),
    provider    VARCHAR NOT NULL CHECK (provider IN ('cvm', 'b3', 'brapi', 'bcb', 'tesouro', 'company_ri')),
    dataset     VARCHAR NOT NULL,            -- e.g. dfp, itr, cad, cotahist, sgs, ifdata, quote
    started_at  TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status      VARCHAR NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    error       VARCHAR
);

CREATE TABLE source_files (
    id               UUID PRIMARY KEY DEFAULT uuid(),
    ingestion_run_id UUID NOT NULL REFERENCES ingestion_runs (id),
    url              VARCHAR NOT NULL,
    retrieved_at     TIMESTAMP NOT NULL,
    sha256           VARCHAR NOT NULL,
    size_bytes       BIGINT NOT NULL,
    last_modified    TIMESTAMP,
    rows_loaded      BIGINT
);

-- Companies and securities -------------------------------------------------------------

CREATE TABLE companies (
    cnpj                VARCHAR PRIMARY KEY,   -- digits only
    cvm_code            INTEGER NOT NULL UNIQUE,
    name                VARCHAR NOT NULL,
    accounting_template VARCHAR NOT NULL CHECK (accounting_template IN ('non_financial', 'bank', 'insurance')),
    sector              VARCHAR,               -- sector profile id (docs/architecture.md §5)
    updated_at          TIMESTAMP NOT NULL
);

CREATE TABLE securities (
    ticker      VARCHAR NOT NULL,
    cnpj        VARCHAR NOT NULL,
    share_class VARCHAR NOT NULL CHECK (share_class IN ('ON', 'PN', 'PNA', 'PNB', 'UNIT')),
    valid_from  DATE NOT NULL,
    valid_to    DATE,
    PRIMARY KEY (ticker, valid_from)
);

-- Financial statements (CVM DFP/ITR) ---------------------------------------------------

CREATE TABLE filings (
    id             UUID PRIMARY KEY DEFAULT uuid(),
    cnpj           VARCHAR NOT NULL,
    doc_type       VARCHAR NOT NULL CHECK (doc_type IN ('DFP', 'ITR')),
    reference_date DATE NOT NULL,
    version        INTEGER NOT NULL,
    received_at    DATE NOT NULL,              -- DT_RECEB: when the filing became public
    source_file_id UUID NOT NULL REFERENCES source_files (id),
    UNIQUE (cnpj, doc_type, reference_date, version)
);

CREATE TABLE financial_facts (
    filing_id        UUID NOT NULL REFERENCES filings (id),
    statement        VARCHAR NOT NULL CHECK (statement IN ('BPA', 'BPP', 'DRE', 'DRA', 'DFC_MD', 'DFC_MI', 'DMPL', 'DVA')),
    statement_column VARCHAR NOT NULL DEFAULT '',   -- DMPL column (COLUNA_DF); empty elsewhere
    basis            VARCHAR NOT NULL CHECK (basis IN ('consolidated', 'individual')),
    account_code     VARCHAR NOT NULL,              -- CD_CONTA
    account_name     VARCHAR NOT NULL,              -- DS_CONTA
    fixed_account    BOOLEAN,                       -- ST_CONTA_FIXA
    period_type      VARCHAR NOT NULL CHECK (period_type IN ('INSTANT', '3M', 'YTD', 'FY')),
    period_start     DATE,
    period_end       DATE NOT NULL,
    value            DECIMAL(38, 4) NOT NULL,
    unit             VARCHAR NOT NULL DEFAULT 'BRL',
    PRIMARY KEY (filing_id, statement, statement_column, basis, account_code, period_type, period_end),
    CHECK ((period_type = 'INSTANT') = (period_start IS NULL))
);

-- Links a CVM account, per accounting template, to a canonical contract concept.
CREATE TABLE account_map (
    accounting_template VARCHAR NOT NULL CHECK (accounting_template IN ('non_financial', 'bank', 'insurance')),
    statement           VARCHAR NOT NULL,
    account_code        VARCHAR NOT NULL,
    concept             VARCHAR NOT NULL,
    sign                SMALLINT NOT NULL DEFAULT 1 CHECK (sign IN (-1, 1)),
    valid_from          DATE NOT NULL DEFAULT DATE '1900-01-01',
    valid_to            DATE,
    notes               VARCHAR,
    PRIMARY KEY (accounting_template, statement, account_code, valid_from)
);

CREATE TABLE shares_outstanding (
    cnpj           VARCHAR NOT NULL,
    share_class    VARCHAR NOT NULL CHECK (share_class IN ('ON', 'PN', 'PNA', 'PNB', 'UNIT')),
    reference_date DATE NOT NULL,
    total          BIGINT NOT NULL,
    treasury       BIGINT NOT NULL DEFAULT 0,
    filing_id      UUID REFERENCES filings (id),
    source_file_id UUID NOT NULL REFERENCES source_files (id),
    PRIMARY KEY (cnpj, share_class, reference_date, source_file_id)
);

-- Market data --------------------------------------------------------------------------

CREATE TABLE prices_daily (               -- unadjusted; adjustments live in corporate_actions
    ticker         VARCHAR NOT NULL,
    trade_date     DATE NOT NULL,
    open           DECIMAL(18, 4),
    high           DECIMAL(18, 4),
    low            DECIMAL(18, 4),
    close          DECIMAL(18, 4) NOT NULL,
    volume         DECIMAL(24, 2),
    trades         BIGINT,
    source         VARCHAR NOT NULL CHECK (source IN ('b3_cotahist', 'brapi')),
    source_file_id UUID REFERENCES source_files (id),
    PRIMARY KEY (ticker, trade_date, source)
);

CREATE TABLE market_quotes (              -- intraday quotes (current price)
    ticker         VARCHAR NOT NULL,
    quoted_at      TIMESTAMP NOT NULL,
    price          DECIMAL(18, 4) NOT NULL,
    source         VARCHAR NOT NULL CHECK (source IN ('brapi')),
    source_file_id UUID REFERENCES source_files (id),
    PRIMARY KEY (ticker, quoted_at, source)
);

CREATE TABLE corporate_actions (
    id               UUID PRIMARY KEY DEFAULT uuid(),
    ticker           VARCHAR NOT NULL,
    action_type      VARCHAR NOT NULL CHECK (action_type IN ('dividend', 'jcp', 'split', 'reverse_split', 'bonus_shares', 'other')),
    declared_at      DATE,
    record_date      DATE NOT NULL,          -- data-com
    ex_date          DATE,
    payment_date     DATE,
    value_per_share  DECIMAL(24, 10),        -- cash events
    is_gross         BOOLEAN,                -- JCP: gross (before withholding) or net
    factor           DECIMAL(24, 10),        -- share events: new shares per old share
    is_extraordinary BOOLEAN NOT NULL DEFAULT false,
    source_file_id   UUID REFERENCES source_files (id),
    document_url     VARCHAR,
    notes            VARCHAR,
    CHECK (source_file_id IS NOT NULL OR document_url IS NOT NULL)
);

-- Macro and banking data ---------------------------------------------------------------

CREATE TABLE macro_series (
    series_code    VARCHAR NOT NULL,         -- e.g. bcb_sgs_432 (Selic target)
    ref_date       DATE NOT NULL,
    value          DECIMAL(24, 10) NOT NULL,
    unit           VARCHAR NOT NULL CHECK (unit IN ('ratio', 'index', 'BRL')),
    source_file_id UUID REFERENCES source_files (id),
    PRIMARY KEY (series_code, ref_date)
);

CREATE TABLE bank_prudential (            -- BCB IF.data, prudential conglomerate basis
    institution_code VARCHAR NOT NULL,
    cnpj             VARCHAR,
    reference_date   DATE NOT NULL,
    report           VARCHAR NOT NULL,
    indicator        VARCHAR NOT NULL,
    value            DECIMAL(38, 10),
    unit             VARCHAR NOT NULL,
    source_file_id   UUID NOT NULL REFERENCES source_files (id),
    PRIMARY KEY (institution_code, reference_date, report, indicator, source_file_id)
);

-- Values extracted from PDFs by the model, kept apart from structured data -------------

CREATE TABLE document_facts (
    id              UUID PRIMARY KEY DEFAULT uuid(),
    cnpj            VARCHAR NOT NULL,
    concept         VARCHAR NOT NULL,
    value           DECIMAL(38, 10) NOT NULL,
    unit            VARCHAR NOT NULL,
    period_type     VARCHAR NOT NULL CHECK (period_type IN ('INSTANT', '3M', 'YTD', 'FY', 'LTM')),
    period_start    DATE,
    period_end      DATE NOT NULL,
    basis           VARCHAR CHECK (basis IN ('consolidated', 'individual', 'prudential', 'managerial')),
    document_url    VARCHAR NOT NULL,
    document_title  VARCHAR,
    published_at    DATE,
    page            INTEGER NOT NULL CHECK (page >= 1),
    excerpt         VARCHAR,                 -- literal text the value was read from
    local_path      VARCHAR,                 -- copy under data/documents/
    document_sha256 VARCHAR,
    extracted_at    TIMESTAMP NOT NULL,
    extracted_by    VARCHAR NOT NULL,
    confidence      VARCHAR NOT NULL CHECK (confidence IN ('high', 'medium', 'low')),
    reviewed        BOOLEAN NOT NULL DEFAULT false,
    reviewed_at     TIMESTAMP,
    notes           VARCHAR,
    CHECK ((period_type = 'INSTANT') = (period_start IS NULL))
);

-- Views --------------------------------------------------------------------------------

-- Latest known value of each fact. A newer filing (or a newer version of the same filing)
-- that reports the same account and period wins, so restatements surface here while the
-- previous values stay in financial_facts for audit.
CREATE VIEW v_financial_facts_latest AS
SELECT
    f.cnpj,
    f.doc_type,
    f.reference_date,
    f.version,
    f.received_at,
    ff.*
FROM financial_facts AS ff
JOIN filings AS f ON f.id = ff.filing_id
QUALIFY row_number() OVER (
    PARTITION BY f.cnpj, ff.statement, ff.statement_column, ff.basis, ff.account_code,
                 ff.period_type, ff.period_start, ff.period_end
    ORDER BY f.received_at DESC, f.reference_date DESC, f.version DESC
) = 1;

-- Last successful ingestion per dataset; sync uses it to decide what is stale.
CREATE VIEW v_ingestion_freshness AS
SELECT provider, dataset, max(finished_at) AS last_success_at
FROM ingestion_runs
WHERE status = 'success'
GROUP BY provider, dataset;
