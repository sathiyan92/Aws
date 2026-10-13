"""
Single-entrypoint server runner for IoT Fleet Platform.
Can be executed from any folder or terminal, locally and on Render.com cloud.
"""
import os
import sys
import types

# 1. Determine absolute paths
project_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(project_root, "backend")
backend_src_dir = os.path.join(backend_dir, "src")

# 2. Add backend to sys.path at position 0
if backend_dir in sys.path:
    sys.path.remove(backend_dir)
sys.path.insert(0, backend_dir)

# 3. Clean any collided 'src' from sys.path or sys.modules (Render path /opt/render/project/src)
for p in list(sys.path):
    if os.path.basename(os.path.normpath(p)) == "src" and p != backend_src_dir:
        sys.path.remove(p)

if "src" in sys.modules:
    del sys.modules["src"]

# 4. Explicitly bind the real 'src' package to backend/src
src_init_path = os.path.join(backend_src_dir, "__init__.py")
src_module = types.ModuleType("src")
src_module.__file__ = src_init_path
src_module.__path__ = [backend_src_dir]
src_module.__package__ = "src"
sys.modules["src"] = src_module

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
