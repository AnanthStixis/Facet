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

-- for firsttime db create automaticatically run the script inside the backend folder on server
docker exec backend python -m alembic upgrade head
docker exec backend python -m app.seed

--for first time default category creation
docker exec backend python -m app.seed_templates

--for fix the export report issue
docker exec backend pip install tzdata==2024.2
docker restart backend