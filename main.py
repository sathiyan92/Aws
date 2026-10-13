"""
Root entrypoint for Render and cloud hosting providers.
Resolves Render /opt/render/project/src directory name collision.
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

# 5. Bootstrap database tables and seed records on first cloud launch
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

# 6. Import and expose FastAPI application instance
from src.main import app
