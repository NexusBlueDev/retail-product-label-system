-- Standard project_library table — apply to every Supabase-backed project.
-- This is the portable documentation table that describes a project's
-- features, tools, integrations, architecture, and highlights.
-- When a project is spun off, this table goes with it.

CREATE TABLE IF NOT EXISTS public.project_library (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  category    TEXT NOT NULL CHECK (category IN (
                'feature', 'tool', 'architecture', 'standard',
                'infrastructure', 'integration', 'highlight', 'reference'
              )),
  title       TEXT NOT NULL,
  summary     TEXT NOT NULL,
  content_md  TEXT,
  tags        TEXT[] DEFAULT '{}',
  sort_order  INT DEFAULT 0,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now(),
  UNIQUE(title)
);

CREATE INDEX IF NOT EXISTS idx_project_library_category
  ON public.project_library (category, sort_order);

ALTER TABLE public.project_library ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on project_library"
  ON public.project_library FOR ALL
  USING (auth.role() = 'service_role');

CREATE POLICY "Authenticated users read project_library"
  ON public.project_library FOR SELECT
  USING (auth.role() = 'authenticated');
