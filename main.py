"""
Root entrypoint for Render and cloud hosting providers.
Resolves Render /opt/render/project/src directory name collision using official ModuleSpec.
"""
import os
import sys
import importlib.util

# 1. Determine absolute paths
project_root = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(project_root, "backend")
backend_src_dir = os.path.join(backend_dir, "src")
src_init_path = os.path.join(backend_src_dir, "__init__.py")

# 2. Add backend to sys.path at position 0
if backend_dir in sys.path:
    sys.path.remove(backend_dir)
sys.path.insert(0, backend_dir)

# 3. Explicitly bind 'src' package to backend/src using standard ModuleSpec
spec = importlib.util.spec_from_file_location(
    "src",
    src_init_path,
    submodule_search_locations=[backend_src_dir],
)
src_pkg = importlib.util.module_from_spec(spec)
sys.modules["src"] = src_pkg
spec.loader.exec_module(src_pkg)

# 4. Bootstrap database tables and seed records on first cloud launch
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

# 5. Import and expose FastAPI application instance
from src.main import app
