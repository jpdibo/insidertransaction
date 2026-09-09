UPDATE reported_transaction_rows
SET consideration_derived_decimal = NULL,
    derivation = NULL
WHERE consideration_derived_decimal IS NOT NULL
  AND (consideration_currency IS NULL OR price_currency IS NULL OR consideration_currency <> price_currency);
