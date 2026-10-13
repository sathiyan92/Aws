"""
Root entrypoint for Render and cloud hosting providers.
Exposes the FastAPI 'app' directly at root namespace.
"""
import os
import sys

# Ensure backend root is on Python module search path
project_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(project_root, "backend")

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Auto-initialize database schema and seed data on cloud startup
try:
    from src.db.session import engine, SessionLocal
    from src.db.base import Base
    from src.db.seed import seed_database
    from src.db.models.user import User

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    admin = db.query(User).filter_by(username="admin").first()
    if not admin:
        print(">>> First cloud launch: Seeding database with initial fleet records...")
        seed_database(db)
        print(">>> Database seeded successfully.")
    db.close()
except Exception as e:
    print(f">>> Cloud database bootstrap notice: {e}")

# Import and expose FastAPI application instance
from src.main import app
