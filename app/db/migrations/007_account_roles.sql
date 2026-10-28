ALTER TABLE desk_users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'
 CHECK (role IN ('user', 'admin'));
