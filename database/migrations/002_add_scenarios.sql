-- ============================================================================
-- Add scenario tracking columns to investment_theses
-- Backward compatible: all new columns have defaults
-- ============================================================================

-- Scenarios JSON: stores array of {label, probability, trigger, invalidation, ...}
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS scenarios_json TEXT DEFAULT '[]';

-- Primary scenario label: BULLISH / BASE / BEARISH
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS primary_scenario TEXT DEFAULT 'BASE';

-- Re-evaluation triggers: JSON array of trigger strings
ALTER TABLE investment_theses
    ADD COLUMN IF NOT EXISTS reeval_triggers TEXT DEFAULT '[]';
