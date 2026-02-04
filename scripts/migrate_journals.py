"""
Migrate journal data from SQLite (database/publications.db) to PostgreSQL (journal_catalog table).

Usage:
    python scripts/migrate_journals.py

Requires DATABASE_URL environment variable to be set.
"""

import os
import sys
import sqlite3

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SQLITE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "database",
    "publications.db",
)


def main():
    if not os.path.exists(SQLITE_PATH):
        print(f"ERROR: SQLite database not found at {SQLITE_PATH}")
        sys.exit(1)

    # Import Flask app to get DB connection
    from app import create_app
    from app.db_models import db, JournalCatalog

    app = create_app()

    with app.app_context():
        # Ensure table exists
        JournalCatalog.__table__.create(db.engine, checkfirst=True)

        # Check if data already migrated
        existing_count = JournalCatalog.query.count()
        if existing_count > 0:
            print(f"journal_catalog already has {existing_count} rows. Skipping migration.")
            print("To re-migrate, truncate the table first:")
            print("  TRUNCATE TABLE journal_catalog RESTART IDENTITY;")
            return

        # Read from SQLite
        conn = sqlite3.connect(SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM publications")
        rows = cursor.fetchall()
        conn.close()

        print(f"Read {len(rows)} journals from SQLite")

        # Batch insert into PostgreSQL
        batch_size = 500
        inserted = 0

        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            objects = []
            for row in batch:
                obj = JournalCatalog(
                    name=row["name"],
                    publication_type=row["publication_type"] if "publication_type" in row.keys() else None,
                    region=row["region"] if "region" in row.keys() else None,
                    indexing=row["indexing"] if "indexing" in row.keys() else None,
                    issn=row["issn"] if "issn" in row.keys() else None,
                    e_issn=row["e_issn"] if "e_issn" in row.keys() else None,
                    sjr_year=row["sjr_year"] if "sjr_year" in row.keys() else None,
                    sjr_publisher=row["sjr_publisher"] if "sjr_publisher" in row.keys() else None,
                    sjr_score=row["sjr_score"] if "sjr_score" in row.keys() else None,
                    sjr_best_quartile=row["sjr_best_quartile"] if "sjr_best_quartile" in row.keys() else None,
                    sjr_h_index=row["sjr_h_index"] if "sjr_h_index" in row.keys() else None,
                )
                objects.append(obj)
            db.session.bulk_save_objects(objects)
            db.session.commit()
            inserted += len(batch)
            print(f"  Inserted {inserted}/{len(rows)}...")

        final_count = JournalCatalog.query.count()
        print(f"Migration complete. {final_count} journals in PostgreSQL.")


if __name__ == "__main__":
    main()
