"""
Single-entrypoint server runner for IoT Fleet Platform.
Can be executed from any folder or terminal, locally and on Render.com cloud.
"""
import os
import sys

# Ensure backend root is always in Python's import search path
project_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(project_root, "backend")

if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import uvicorn

def init_cloud_database():
    """Ensure database tables and initial seed data exist upon fresh cloud deploy."""
    try:
        from src.db.session import engine, SessionLocal
        from src.db.base import Base
        from src.db.seed import seed_database
        from src.db.models.user import User

        print(">>> Initializing database schema...")
        Base.metadata.create_all(bind=engine)

        session = SessionLocal()
        admin_user = session.query(User).filter_by(username="admin").first()
        if not admin_user:
            print(">>> Fresh cloud deployment detected: Seeding initial devices & admin...")
            seed_database(session)
            print(">>> Seed data created successfully.")
        session.close()
    except Exception as e:
        print(f">>> Database bootstrap notice: {e}")

if __name__ == "__main__":
    init_cloud_database()

    # Read port from Render.com environment or fallback to 8000
    port = int(os.environ.get("PORT", 8000))
    print("==================================================")
    print(">>> Starting IoT Fleet Platform Server...")
    print(f">>> Backend Directory: {backend_dir}")
    print(f">>> Port: {port}")
    print(f">>> Local Portal URL : http://localhost:{port}/portal")
    print("==================================================")

    uvicorn.run(
        "src.main:app",
        app_dir=backend_dir,
        host="0.0.0.0",
        port=port,
        reload=False,
    )
