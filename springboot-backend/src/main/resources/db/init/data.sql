-- Safe defaults: never overwrite existing users, settings, or migrated business records.
-- The IDENTITY columns generate IDs automatically, avoiding sequence resets.
INSERT INTO app_user
    (username,pwd,role_id,exp_time,flow,in_flow,out_flow,flow_reset_time,num,created_time,updated_time,status)
SELECT 'admin_user','3c85cdebade1c51cf64ca9f3c09d182d',0,2727251700000,99999,0,0,1,99999,1748914865000,1754011744252,1
WHERE NOT EXISTS (SELECT 1 FROM app_user)
ON CONFLICT DO NOTHING;

INSERT INTO vite_config (name,value,time)
SELECT 'app_name','flux',1755147963000
WHERE NOT EXISTS (SELECT 1 FROM vite_config WHERE lower(name) = 'app_name')
ON CONFLICT DO NOTHING;
