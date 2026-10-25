-- Explicit Data API (PostgREST) grants on all public-schema tables.
--
-- Why: Supabase is removing the automatic Data API grant (SELECT/INSERT/UPDATE/DELETE
-- to anon/authenticated/service_role) on public-schema tables for every existing
-- project on 2026-10-30 (https://supabase.com/changelog/45329). This repo's entire
-- migration history (13 files) has never contained a table-level GRANT statement, so
-- without this migration every table in this project would silently lose Data API
-- access the moment the default is removed, or on any future full-schema replay
-- (preview branch, CI, `supabase db reset`, disaster recovery) even before then.
--
-- This migration is additive and idempotent (safe to re-run). It does not expand
-- access beyond what already works today -- it formalizes the access each table's
-- *existing* RLS policies already intend, derived from a live query against
-- pg_policies (see docs/roadmap/SUPABASE_DATA_API_GRANT_AUDIT.md in nexusblue-core
-- for the platform-wide program this belongs to). RLS remains the real security
-- boundary; these GRANTs just restore reachability at the PostgREST layer.
--
-- Derivation (live-queried 2026-10-25 against project ayfwyvripnetwrkimxka):
-- Classified every policy by its ACTUAL roles column + qual together, not either
-- field alone (ignoring either one is exactly the bug the reference implementation
-- caught and corrected in nexusblue-core's own migration 122 -- see audit doc).
--
--   app_users            RLS=on. 1 policy: owner_all_app_users
--                         TO authenticated, cmd=ALL, qual=auth.uid()=<fixed owner uid>.
--                         -> authenticated: SELECT/INSERT/UPDATE/DELETE. No anon policy.
--
--   lightspeed_index      RLS=on. 1 policy: owner_all_lightspeed_index
--                         TO authenticated, cmd=ALL, qual=auth.uid()=<fixed owner uid>.
--                         -> authenticated: SELECT/INSERT/UPDATE/DELETE. No anon policy.
--
--   products              RLS=on. 1 policy: owner_all_products
--                         TO authenticated, cmd=ALL, qual=auth.uid()=<fixed owner uid>.
--                         -> authenticated: SELECT/INSERT/UPDATE/DELETE. No anon policy.
--
--   normalized_products   RLS=on. 1 policy: "Users can manage own normalized_products"
--                         roles={public} (no TO clause -- written in a different idiom
--                         than the 3 tables above, which use an explicit TO authenticated),
--                         cmd=ALL, qual=auth.uid()=<same fixed owner uid>.
--                         FLAGGED FOR THE REPO'S OWN FUTURE HYGIENE (not fixed here,
--                         out of this migration's scope, not a live exploit): because
--                         the policy has no TO clause it nominally applies to anon too,
--                         but auth.uid() evaluates NULL for an anon request (no JWT
--                         `sub` claim), so the row filter rejects every row for anon
--                         regardless of grant. Confirmed via grep: this table is not
--                         referenced anywhere in js/ or supabase/functions/ -- it has
--                         no live write path in the current app at all.
--                         -> authenticated: SELECT/INSERT/UPDATE/DELETE (matches the
--                         other 3 owner-scoped tables' effective behavior). No anon.
--
--   project_library       RLS=on. 2 policies:
--                         "Authenticated users read project_library": roles={public},
--                           cmd=SELECT, qual=auth.role()='authenticated'.
--                         "Service role full access on project_library": roles={public},
--                           cmd=ALL, qual=auth.role()='service_role'.
--                         Confirmed via grep: not referenced anywhere in js/ or
--                         supabase/functions/ -- no live app usage found.
--                         -> authenticated: SELECT only. No anon (no policy permits it).
--
--   rate_limits            RLS=on. 1 policy: deny_anon_rate_limits
--                         TO anon, cmd=ALL, qual=false, with_check=false -- an explicit
--                         DENY, not a grant. No policy at all targets authenticated or
--                         public, so with RLS on, authenticated also gets zero rows by
--                         default (no permissive policy matches it). Only service_role
--                         (which bypasses RLS entirely) can read/write. Confirmed via
--                         grep: supabase/functions/extract-product/index.ts is the only
--                         caller, and it uses SUPABASE_SERVICE_ROLE_KEY, never anon/
--                         authenticated -- matches this table's deny-everyone-but-
--                         service-role design.
--                         -> No authenticated grant. No anon grant (deny policy, not a
--                         permitting one).
--
-- Findings for this program, not fixed here (RLS-disabled tables / unguarded
-- qual=true policies would be flagged the same way): NONE. All 6 public tables have
-- rowsecurity=true. No policy anywhere in this schema has a literal unguarded
-- qual=true. No views exist in this schema (pg_class.relkind='v'/'m' returned 0 rows)
-- so the "views are in scope" platform finding does not apply to this repo.
--
-- Sequence privileges checked, not touched: products_id_seq and
-- normalized_products_id_seq both already have USAGE granted to authenticated (and
-- anon) via Postgres's own default privileges, separate from and unaffected by the
-- Data API table-grant removal this migration addresses. Confirmed live via
-- has_sequence_privilege() before writing this file -- no action needed.

-- service_role: always full access, unconditionally, on every table.
GRANT ALL ON TABLE public.app_users TO service_role;
GRANT ALL ON TABLE public.lightspeed_index TO service_role;
GRANT ALL ON TABLE public.normalized_products TO service_role;
GRANT ALL ON TABLE public.products TO service_role;
GRANT ALL ON TABLE public.project_library TO service_role;
GRANT ALL ON TABLE public.rate_limits TO service_role;

-- authenticated: exactly the commands each table's real RLS policy covers.
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.app_users TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.lightspeed_index TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.normalized_products TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.products TO authenticated;
GRANT SELECT ON TABLE public.project_library TO authenticated;
-- rate_limits: intentionally no authenticated grant -- no policy permits it.

-- anon: intentionally no grants anywhere in this migration -- no table has a real,
-- intentional policy permitting the anon role. (rate_limits has an explicit anon
-- DENY policy; every other table restricts to authenticated via a specific owner uid.)
