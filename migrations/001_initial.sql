create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table if not exists public.generation_runs (
    id uuid primary key,
    run_key text unique not null,
    run_type text not null check (run_type in ('DAILY', 'DRY_RUN')),
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    status text not null check (status in ('RUNNING', 'SUCCEEDED', 'FAILED', 'NOOP')),
    attempts integer not null default 0,
    failure_code text,
    failure_reason text,
    research_model text not null,
    style_model text not null,
    embedding_model text not null,
    dry_run boolean not null default false
);

create table if not exists public.facts (
    id uuid primary key,
    run_id uuid not null unique references public.generation_runs(id),
    fact_text text not null,
    normalized_fact text not null,
    sms_text text,
    category text not null,
    subjects text[] not null,
    source_url text not null,
    source_title text,
    sources jsonb not null default '[]'::jsonb,
    embedding extensions.vector(1536) not null,
    status text not null check (status in ('PENDING', 'SEND_ATTEMPTED', 'SUBMITTED', 'SENT', 'DELIVERED', 'FAILED', 'DRY_RUN')),
    send_attempted_at timestamptz,
    twilio_sid text,
    twilio_status text,
    twilio_error_code integer,
    generated_at timestamptz not null default now(),
    sent_at timestamptz,
    delivered_at timestamptz
);

create table if not exists public.generation_attempts (
    id uuid primary key,
    run_id uuid not null references public.generation_runs(id),
    attempt_number integer not null,
    candidate_fact text,
    normalized_fact text,
    category text,
    subjects text[],
    source_url text,
    source_title text,
    sources jsonb,
    similarity_score double precision,
    matched_fact_id uuid references public.facts(id),
    accepted boolean not null default false,
    rejection_code text,
    rejection_reason text,
    created_at timestamptz not null default now(),
    unique (run_id, attempt_number)
);

create index if not exists facts_generated_at_idx on public.facts (generated_at desc);
create index if not exists facts_status_idx on public.facts (status);
create index if not exists facts_category_idx on public.facts (category);
create index if not exists facts_subjects_idx on public.facts using gin (subjects);
create index if not exists facts_embedding_hnsw_idx on public.facts using hnsw (embedding extensions.vector_cosine_ops);
create unique index if not exists facts_deliverable_normalized_unique
    on public.facts (normalized_fact)
    where status in ('SEND_ATTEMPTED', 'SUBMITTED', 'SENT', 'DELIVERED');

create index if not exists generation_attempts_run_idx on public.generation_attempts (run_id, attempt_number);
