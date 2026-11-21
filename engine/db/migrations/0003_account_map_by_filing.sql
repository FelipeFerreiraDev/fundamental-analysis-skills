-- The account_map validity must apply to the filing's reference date, not to the period of
-- the value: the CVM statement layout belongs to the document. A 2020 DFP restates 2019 in
-- the new bank layout, where the same account code can mean something else (e.g. DRE 3.09
-- was net income until 2019 and became "income before profit sharing" from 2020 on).

CREATE OR REPLACE VIEW v_concept_facts AS
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
   AND l.reference_date >= m.valid_from
   AND (m.valid_to IS NULL OR l.reference_date <= m.valid_to)
WHERE l.statement_column = ''
-- One value per concept and period: when the old layout (older filing) and the new layout
-- (newer filing) both report the same period under different codes, the newest filing wins.
QUALIFY row_number() OVER (
    PARTITION BY l.cnpj, m.concept, l.basis, l.period_type, l.period_start, l.period_end
    ORDER BY l.received_at DESC, l.reference_date DESC, l.version DESC
) = 1;
