-- A single subscription for this single-recipient application; never stores a phone.
create table public.subscription_state (
    id boolean primary key default true check (id),
    suppressed boolean not null default false,
    updated_at timestamptz not null default now()
);
insert into public.subscription_state (id, suppressed)
select true, exists (select 1 from public.facts where twilio_error_code = 21610);

-- Run with the server-side table owner. Owners retain runtime access via RLS bypass.
-- API roles must not own these tables or be used as the runtime database login.
do $$
declare
    table_name text;
    api_role text;
begin
    foreach table_name in array array[
        'generation_runs', 'facts', 'generation_attempts',
        'schema_migrations', 'subscription_state'
    ] loop
        execute format('alter table public.%I enable row level security', table_name);
        execute format('revoke all on table public.%I from public', table_name);
        foreach api_role in array array['anon', 'authenticated', 'service_role'] loop
            if exists (select 1 from pg_roles where rolname = api_role) then
                execute format('revoke all on table public.%I from %I', table_name, api_role);
            end if;
        end loop;
    end loop;
end $$;
