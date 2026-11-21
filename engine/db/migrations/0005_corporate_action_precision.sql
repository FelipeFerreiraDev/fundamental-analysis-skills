-- B3 publishes cash events with up to 11 decimal places (e.g. 0,10245643978). DECIMAL(24,10)
-- rounded them, so the stored value no longer matched the published one and a second sync
-- inserted the same event again. 14 decimal places keep the published value exactly.

ALTER TABLE corporate_actions ALTER value_per_share TYPE DECIMAL(28, 14);
ALTER TABLE corporate_actions ALTER factor TYPE DECIMAL(28, 14);
