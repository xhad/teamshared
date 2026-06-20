-- teamshared 031: drop the consent_grants table (retire consent-first capture).
--
-- Consent-first capture was retired from the product on 2026-06-19: capture is
-- now gated only by settings.capture_enabled, not per-agent consent grants.
-- This migration drops the table created in 011_consent.sql and the associated
-- RLS policy / grants. The code-side ConsentStore, /app/consent console UI, and
-- consent_denied_capture metric were removed in the same change.
--
-- 011_consent.sql is intentionally left on disk as a historical artifact so the
-- applied-migration history remains intact (see AGENTS.md: "Never rewrite an
-- applied migration; add a new one").

DROP POLICY IF EXISTS org_isolation ON consent_grants;
DROP TABLE IF EXISTS consent_grants CASCADE;
