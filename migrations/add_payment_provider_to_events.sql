-- Migration: Add payment_provider column to client_payment_events
-- Date: 2026-01-15
-- Purpose: Support account payment tracking (Click/Payme) in addition to cash payments

-- Step 1: Add payment_provider column (nullable for backward compatibility)
ALTER TABLE client_payment_events
ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(20) NULL;

-- Step 2: Add comment for documentation
COMMENT ON COLUMN client_payment_events.payment_provider IS
'Payment provider: null (legacy cash), ''cash'', ''click'', ''payme''';

-- Step 3: Create index for provider-based queries (optional but recommended for stats)
CREATE INDEX IF NOT EXISTS ix_client_payment_events_provider
ON client_payment_events(payment_provider);

-- Step 4: Add check constraint to ensure valid values
ALTER TABLE client_payment_events
ADD CONSTRAINT check_payment_provider_values
CHECK (payment_provider IS NULL OR payment_provider IN ('cash', 'click', 'payme'));

-- Backward compatibility notes:
-- - Existing records will have payment_provider = NULL (treated as legacy cash payments)
-- - New cash payments should set payment_provider = 'cash'
-- - Account payments use 'click' or 'payme'

-- Rollback script (if needed):
-- ALTER TABLE client_payment_events DROP CONSTRAINT IF EXISTS check_payment_provider_values;
-- DROP INDEX IF EXISTS ix_client_payment_events_provider;
-- ALTER TABLE client_payment_events DROP COLUMN IF EXISTS payment_provider;
