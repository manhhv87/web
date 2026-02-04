import os
import sys

# Ensure project root is on sys.path
proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, proj_root)

from flask import Flask
from app.db_models import db, OrganizationUnit, Division, ensure_user_org_columns

# Create a fresh Flask app pointing to a temporary SQLite DB to avoid touching existing data
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///test_tmp.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

with app.app_context():
    print('App context ready, DB URI =', app.config.get('SQLALCHEMY_DATABASE_URI'))
    db.create_all()
    # Ensure helper creates index and triggers for SQLite
    ensure_user_org_columns(app)
    # Inspect sqlite_master to show created indexes/triggers
    from sqlalchemy import text
    try:
        rows = db.session.execute(text("SELECT type, name, sql FROM sqlite_master WHERE type IN ('index','trigger')")).fetchall()
        print('\n--- sqlite_master entries (index/trigger) ---')
        for r in rows:
            print(r[0], r[1])
            print(r[2])
            print('---')
    except Exception as e:
        print('Could not read sqlite_master:', e)

    # Test invalid unit_type insertion
    try:
        ou = OrganizationUnit(name='Test OU Invalid', code='TU1', unit_type='invalid')
        db.session.add(ou)
        db.session.commit()
        print('ERROR: invalid unit_type was inserted')
    except Exception as e:
        print('Invalid unit_type rejected as expected:', type(e).__name__, str(e))
        db.session.rollback()

    # Test duplicate division.code within same org
    try:
        ou2 = OrganizationUnit(name='Test OU Valid', code='TU2', unit_type='faculty')
        db.session.add(ou2)
        db.session.commit()
        print('Inserted org unit id=', ou2.id)

        div1 = Division(name='Div1', code='DUP', organization_unit_id=ou2.id)
        db.session.add(div1)
        db.session.commit()
        print('Inserted first division')

        div2 = Division(name='Div2', code='DUP', organization_unit_id=ou2.id)
        db.session.add(div2)
        db.session.commit()
        print('ERROR: duplicate division.code was inserted')
    except Exception as e:
        print('Duplicate division.code rejected as expected:', type(e).__name__, str(e))
        db.session.rollback()

    print('Test script finished')
