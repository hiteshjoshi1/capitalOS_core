-- Risk page concentration thresholds, per user (#253, D-68). Settings → Risk thresholds.
--
-- Each is the percent above which the Risk page calls a figure concentrated: the
-- largest position and the top N positions (shares of net worth), and the largest
-- platform (share of gross assets, as the Overview platform donut). Only an upper
-- threshold warns; a lower figure is never flagged. NULL means "the app's default"
-- (web/src/lib/risk.ts), so a default can change without touching stored rows.
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS risk_largest_position_warn_pct NUMERIC(5, 2);
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS risk_top_n_warn_pct NUMERIC(5, 2);
ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS risk_platform_warn_pct NUMERIC(5, 2);

-- A threshold is a percent in (0, 100]. No existing row sets one, so validation scans nothing it rejects.
ALTER TABLE user_preferences ADD CONSTRAINT user_preferences_risk_thresholds_range CHECK ((risk_largest_position_warn_pct IS NULL OR (risk_largest_position_warn_pct > 0 AND risk_largest_position_warn_pct <= 100)) AND (risk_top_n_warn_pct IS NULL OR (risk_top_n_warn_pct > 0 AND risk_top_n_warn_pct <= 100)) AND (risk_platform_warn_pct IS NULL OR (risk_platform_warn_pct > 0 AND risk_platform_warn_pct <= 100))) NOT VALID;
ALTER TABLE user_preferences VALIDATE CONSTRAINT user_preferences_risk_thresholds_range;
