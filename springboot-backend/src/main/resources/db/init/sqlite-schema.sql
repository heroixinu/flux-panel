-- SQLite startup schema. AUTOINCREMENT preserves non-reuse of generated IDs.
CREATE TABLE IF NOT EXISTS forward (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id integer NOT NULL,
  user_name varchar(100) NOT NULL,
  name varchar(100) NOT NULL,
  tunnel_id integer NOT NULL,
  in_port integer NOT NULL,
  out_port integer DEFAULT NULL,
  remote_addr text NOT NULL,
  strategy varchar(100) NOT NULL DEFAULT 'fifo',
  interface_name varchar(200) DEFAULT NULL,
  in_flow bigint NOT NULL DEFAULT 0,
  out_flow bigint NOT NULL DEFAULT 0,
  created_time bigint NOT NULL,
  updated_time bigint NOT NULL,
  status integer NOT NULL,
  inx integer NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS node (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name varchar(100) NOT NULL,
  secret varchar(100) NOT NULL,
  ip text,
  server_ip varchar(100) NOT NULL,
  port_sta integer NOT NULL,
  port_end integer NOT NULL,
  version varchar(100) DEFAULT NULL,
  http integer NOT NULL DEFAULT 0,
  tls integer NOT NULL DEFAULT 0,
  socks integer NOT NULL DEFAULT 0,
  created_time bigint NOT NULL,
  updated_time bigint DEFAULT NULL,
  status integer NOT NULL
);

CREATE TABLE IF NOT EXISTS speed_limit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name varchar(100) NOT NULL,
  speed integer NOT NULL,
  tunnel_id integer NOT NULL,
  tunnel_name varchar(100) NOT NULL,
  created_time bigint NOT NULL,
  updated_time bigint DEFAULT NULL,
  status integer NOT NULL
);

CREATE TABLE IF NOT EXISTS statistics_flow (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id integer NOT NULL,
  flow bigint NOT NULL,
  total_flow bigint NOT NULL,
  time varchar(100) NOT NULL,
  created_time bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS tunnel (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name varchar(100) NOT NULL,
  traffic_ratio decimal(10,1) NOT NULL DEFAULT 1.0,
  in_node_id integer NOT NULL,
  in_ip varchar(100) NOT NULL,
  out_node_id integer NOT NULL,
  out_ip varchar(100) NOT NULL,
  type integer NOT NULL,
  protocol varchar(10) NOT NULL DEFAULT 'tls',
  flow integer NOT NULL,
  tcp_listen_addr varchar(100) NOT NULL DEFAULT '[::]',
  udp_listen_addr varchar(100) NOT NULL DEFAULT '[::]',
  interface_name varchar(200) DEFAULT NULL,
  created_time bigint NOT NULL,
  updated_time bigint NOT NULL,
  status integer NOT NULL
);

CREATE TABLE IF NOT EXISTS app_user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username varchar(100) NOT NULL,
  pwd varchar(100) NOT NULL,
  role_id integer NOT NULL,
  exp_time bigint NOT NULL,
  flow bigint NOT NULL,
  in_flow bigint NOT NULL DEFAULT 0,
  out_flow bigint NOT NULL DEFAULT 0,
  flow_reset_time bigint NOT NULL,
  num integer NOT NULL,
  created_time bigint NOT NULL,
  updated_time bigint DEFAULT NULL,
  status integer NOT NULL
);

CREATE TABLE IF NOT EXISTS user_tunnel (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id integer NOT NULL,
  tunnel_id integer NOT NULL,
  speed_id integer DEFAULT NULL,
  num integer NOT NULL,
  flow bigint NOT NULL,
  in_flow bigint NOT NULL DEFAULT 0,
  out_flow bigint NOT NULL DEFAULT 0,
  flow_reset_time bigint NOT NULL,
  exp_time bigint NOT NULL,
  status integer NOT NULL
);

CREATE TABLE IF NOT EXISTS vite_config (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name varchar(200) NOT NULL,
  value varchar(200) NOT NULL,
  time bigint NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS vite_config_name_ci ON vite_config (lower(name));
