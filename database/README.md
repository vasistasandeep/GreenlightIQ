# CineROI AI — Database

PostgreSQL 16+ with the pgvector extension. Alembic manages schema migrations;
`seed/` holds initialization and mock-seed scripts.

```
database/
├── migrations/      # Alembic environment + revision scripts (task 2)
│   ├── versions/
│   ├── env.py
│   └── script.py.mako
├── seed/            # schema init + mock seed data (task 2.3)
└── alembic.ini
```

## Usage

Run migrations (reads `CINEROI_DATABASE_URL` from the environment):

```bash
alembic upgrade head
```

Create a new revision:

```bash
alembic revision -m "describe change"
```
