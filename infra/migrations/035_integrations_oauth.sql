-- teamshared 035: OAuth-connected integrations (Gmail, Slack) on top of the
-- existing connector framework.
--
-- Connections become per-human (account-scoped) for the OAuth kinds: the
-- ``connectors.account_id`` column, when set, marks a personal connection whose
-- credential belongs to that account. When NULL the row is a legacy org-scoped
-- connector (manual token paste) as before. Ingested content still lands in the
-- org shared brain (org-scoped recall); only the credential is personal.
--
-- ``connector_tokens`` gains the OAuth refresh/expiry/scope fields so the
-- ConnectorService can refresh short-lived access tokens lazily before each
-- adapter call. Existing envelope encryption (ciphertext + nonce + key_id)
-- covers the new columns unchanged: refresh_token is stored as plaintext inside
-- the encrypted envelope (the vault encrypts a JSON blob of all token fields).

ALTER TABLE connectors
    ADD COLUMN IF NOT EXISTS account_id UUID REFERENCES accounts(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS connectors_account_idx ON connectors (account_id);

ALTER TABLE connector_tokens
    ADD COLUMN IF NOT EXISTS refresh_token TEXT,
    ADD COLUMN IF NOT EXISTS access_token_expires_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS token_type TEXT,
    ADD COLUMN IF NOT EXISTS scope TEXT;

-- account_id is a refinement of org isolation (a user only manages their own
-- connections); the org_isolation RLS policy from 006_rls.sql still governs
-- tenant boundaries. No new RLS policy needed here.
