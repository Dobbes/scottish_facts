-- Recipient identities are configuration slots, never phone numbers or hashes.
-- facts retains the original primary-recipient fields for backwards-compatible history.
create table public.sms_deliveries (
    id uuid primary key,
    fact_id uuid not null references public.facts(id),
    recipient_slot text not null check (recipient_slot in ('primary', 'secondary')),
    status text not null check (status in ('PENDING', 'SEND_ATTEMPTED', 'SUBMITTED', 'SENT', 'DELIVERED', 'FAILED')),
    send_attempted_at timestamptz,
    twilio_sid text,
    twilio_status text,
    twilio_error_code integer,
    created_at timestamptz not null default now(),
    sent_at timestamptz,
    delivered_at timestamptz,
    unique (fact_id, recipient_slot)
);

-- Preserve every historical production boundary, including ambiguous/failed sends.
-- No preview becomes sendable and no historical secondary delivery is created.
insert into public.sms_deliveries (
    id, fact_id, recipient_slot, status, send_attempted_at,
    twilio_sid, twilio_status, twilio_error_code, created_at, sent_at, delivered_at
)
select id, id, 'primary', status, send_attempted_at,
    twilio_sid, twilio_status, twilio_error_code, generated_at, sent_at, delivered_at
from public.facts where status <> 'DRY_RUN';

create index sms_deliveries_unresolved_idx on public.sms_deliveries (created_at)
    where status in ('SEND_ATTEMPTED', 'SUBMITTED', 'SENT');
create unique index sms_deliveries_sid_unique on public.sms_deliveries (twilio_sid)
    where twilio_sid is not null;

alter table public.sms_deliveries enable row level security;
revoke all on table public.sms_deliveries from public;
do $$
declare api_role text;
begin
    foreach api_role in array array['anon', 'authenticated', 'service_role'] loop
        if exists (select 1 from pg_roles where rolname = api_role) then
            execute format('revoke all on table public.sms_deliveries from %I', api_role);
        end if;
    end loop;
end $$;
