#!/usr/bin/env python3
"""Copy a stopped MySQL installation into an empty PostgreSQL schema."""
import os
import sys

import pymysql
import psycopg
from psycopg import sql

TABLES = ('forward', 'node', 'speed_limit', 'statistics_flow', 'tunnel', 'user', 'user_tunnel', 'vite_config')
BATCH_SIZE = 500


def required(name):
    value = os.environ.get(name)
    if not value:
        raise ValueError(f'Missing environment variable: {name}')
    return value


def migrate():
    source = pymysql.connect(host=required('MYSQL_HOST'), port=int(os.environ.get('MYSQL_PORT', '3306')),
                             user=required('MYSQL_USER'), password=required('MYSQL_PASSWORD'),
                             database=required('MYSQL_DATABASE'), charset='utf8mb4', autocommit=False)
    try:
        with psycopg.connect(host=required('PGHOST'), port=int(os.environ.get('PGPORT', '5432')),
                             user=required('PGUSER'), password=required('PGPASSWORD'),
                             dbname=required('PGDATABASE')) as target:
            with source.cursor() as meta, target.cursor() as pg:
                meta.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
                meta.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
                meta.execute('SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = %s', ('BASE TABLE',))
                tables = dict(meta.fetchall())
                if set(tables) != set(TABLES) or any((engine or '').lower() != 'innodb' for engine in tables.values()):
                    raise ValueError('Source must have exactly the eight expected InnoDB tables; inspect its schema first')
                for table in TABLES:
                    dest = 'app_user' if table == 'user' else table
                    pg.execute(sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE').format(sql.Identifier(dest)))
                    pg.execute(sql.SQL('SELECT EXISTS (SELECT 1 FROM {})').format(sql.Identifier(dest)))
                    if pg.fetchone()[0]:
                        raise ValueError(f'Target table {dest} is not empty')
                    pg.execute('SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position', (dest,))
                    dest_columns = [r[0] for r in pg.fetchall()]
                    source_columns = ['user' if table == 'user' and c == 'username' else c for c in dest_columns]
                    meta.execute('SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION', (table,))
                    actual = [r[0] for r in meta.fetchall()]
                    if not dest_columns or set(actual) != set(source_columns):
                        raise ValueError(f'Column mismatch in {table}; inspect the actual schema before migration')
                    query = 'SELECT ' + ', '.join('`' + c + '`' for c in source_columns) + ' FROM `' + table + '` ORDER BY `id`'
                    insert = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                        sql.Identifier(dest), sql.SQL(', ').join(map(sql.Identifier, dest_columns)),
                        sql.SQL(', ').join(sql.Placeholder() for _ in dest_columns))
                    with source.cursor(pymysql.cursors.SSCursor) as reader:
                        reader.execute(query)
                        count = 0
                        while rows := reader.fetchmany(BATCH_SIZE):
                            pg.executemany(insert, rows)
                            count += len(rows)
                    # Compare every field from the same snapshot; no values or secrets are logged.
                    verify = sql.SQL('SELECT {} FROM {} ORDER BY id').format(
                        sql.SQL(', ').join(map(sql.Identifier, dest_columns)), sql.Identifier(dest))
                    with source.cursor(pymysql.cursors.SSCursor) as reader, target.cursor(name='verify_' + dest) as check:
                        reader.execute(query)
                        check.execute(verify)
                        while rows := reader.fetchmany(BATCH_SIZE):
                            if list(rows) != check.fetchmany(len(rows)):
                                raise ValueError(f'Data verification failed for {table}')
                        if check.fetchone() is not None:
                            raise ValueError(f'Unexpected extra rows in {dest}')
                    pg.execute('SELECT setval(pg_get_serial_sequence(%s, %s), COALESCE(MAX(id), 1), COUNT(*) > 0) FROM ' + '"' + dest + '"', (dest, 'id'))
                    print(f'{table}: {count} rows verified', flush=True)
                pg.execute('SELECT 1 FROM app_user GROUP BY lower(username) HAVING COUNT(*) > 1 LIMIT 1')
                if pg.fetchone():
                    raise ValueError('Source usernames collide under PostgreSQL case-insensitive comparison')
            # Commit happens only after every table has passed verification.
        source.rollback()
    finally:
        source.close()


if __name__ == '__main__':
    try:
        migrate()
        print('Migration committed. Keep the source read-only until cutover verification is complete.')
    except Exception as exc:
        detail = str(exc) if type(exc) is ValueError else type(exc).__name__
        print(f'Migration failed; target transaction rolled back: {detail}', file=sys.stderr)
        sys.exit(1)
