INSERT INTO users (
    id, org_id, email, full_name, role, status,
    password_hash, password_changed_at, mfa_enabled,
    created_at, updated_at
) VALUES (
    gen_random_uuid(), NULL,
    'second.admin@yourcompany.com',
    'Second Admin',
    'super_admin', 'active',
    'PASTE_HASH_HERE',
    now(), false,
    now(), now()
);

create hash for the password using the following command in psql:
SELECT crypt('your_password_here', gen_salt('bf'));