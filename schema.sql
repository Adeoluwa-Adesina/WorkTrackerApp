create table public.leaderboard_stats (
  id uuid not null default gen_random_uuid (),
  user_id uuid not null,
  display_name text not null default ''::text,
  stat_date date not null,
  total_sessions integer not null default 0,
  longest_session_duration_minutes double precision not null default '0'::double precision,
  last_synced timestamp with time zone null default now(),
  constraint leaderboard_stats_pkey primary key (id, stat_date)
) TABLESPACE pg_default;