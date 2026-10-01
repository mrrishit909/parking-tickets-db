#!/bin/sh
# Start the project's private PostgreSQL (socket only, no network port) and run the steps in order.
set -e
cd "$(dirname "$0")"
PG=${PG:-$HOME/micromamba/envs/analyst/bin}
[ -d data/pg ] || { "$PG/initdb" -D data/pg -U postgres --auth=trust -E UTF8 --locale=C >/dev/null;
  printf "listen_addresses = ''\nport = 5434\nunix_socket_directories = '%s'\nmax_wal_size = 4GB\nmaintenance_work_mem = 1GB\nshared_buffers = 1GB\n" "$PWD/data" >> data/pg/postgresql.conf; }
"$PG/pg_ctl" -D data/pg status >/dev/null 2>&1 || "$PG/pg_ctl" -D data/pg -l data/pg.log -w start >/dev/null
./venv/bin/python run.py
