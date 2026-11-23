-- PostgreSQL 16 seed data, applied after gost-schema.sql on new installations.
BEGIN;
INSERT INTO app_user (id, username, pwd, role_id, exp_time, flow, in_flow, out_flow, flow_reset_time, num, created_time, updated_time, status) VALUES
(1, 'admin_user', '3c85cdebade1c51cf64ca9f3c09d182d', 0, 2727251700000, 99999, 0, 0, 1, 99999, 1748914865000, 1754011744252, 1);
INSERT INTO vite_config (id, name, value, time) VALUES (1, 'app_name', 'flux', 1755147963000);
SELECT setval(pg_get_serial_sequence('app_user', 'id'), (SELECT MAX(id) FROM app_user));
SELECT setval(pg_get_serial_sequence('vite_config', 'id'), (SELECT MAX(id) FROM vite_config));
COMMIT;
