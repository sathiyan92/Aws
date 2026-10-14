"""
Root entrypoint for Render and cloud hosting providers.
Dynamically resolves project structure and binds 'src' package with official ModuleSpec.
"""
import os
import sys
import importlib.util

# 1. Determine project root
project_root = os.path.dirname(os.path.abspath(__file__))

# 2. Locate backend directory and application 'src' directory
def locate_backend_and_src(root):
    # Candidate 1: Standard monorepo layout (backend/src)
    c1 = os.path.join(root, "backend", "src")
    if os.path.isdir(c1) and (os.path.exists(os.path.join(c1, "main.py")) or os.path.exists(os.path.join(c1, "api"))):
        return os.path.join(root, "backend"), c1

    # Candidate 2: Root-level src layout (src)
    c2 = os.path.join(root, "src")
    if os.path.isdir(c2) and (os.path.exists(os.path.join(c2, "api")) or os.path.exists(os.path.join(c2, "main.py"))):
        return root, c2

    # Candidate 3: Deep search for directory named 'src' containing api or db
    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) == "src" and ("api" in dirnames or "db" in dirnames or "main.py" in filenames):
            return os.path.dirname(dirpath), dirpath

    # Fallback to candidate 1
    return os.path.join(root, "backend"), c1

backend_dir, backend_src_dir = locate_backend_and_src(project_root)
print(f">>> Detected Backend Directory: {backend_dir}")
print(f">>> Detected Backend Src Directory: {backend_src_dir}")
if os.path.exists(backend_src_dir):
    print(f">>> Files in backend/src: {os.listdir(backend_src_dir)}")
else:
    print(">>> WARNING: backend_src_dir does not exist yet!")

# 3. Ensure __init__.py files exist so importlib and Python loaders never fail
os.makedirs(backend_src_dir, exist_ok=True)
src_init_path = os.path.join(backend_src_dir, "__init__.py")
if not os.path.isfile(src_init_path):
    try:
        with open(src_init_path, "w", encoding="utf-8") as f:
            f.write("# Package marker\n")
    except Exception as e:
        print(f">>> Notice creating src/__init__.py: {e}")

backend_init_path = os.path.join(backend_dir, "__init__.py")
if not os.path.isfile(backend_init_path):
    try:
        with open(backend_init_path, "w", encoding="utf-8") as f:
            f.write("# Package marker\n")
    except Exception as e:
        print(f">>> Notice creating backend/__init__.py: {e}")

# 4. Add backend to sys.path at position 0
if backend_dir in sys.path:
    sys.path.remove(backend_dir)
sys.path.insert(0, backend_dir)

# 5. Explicitly bind 'src' package using standard ModuleSpec
spec = importlib.util.spec_from_file_location(
    "src",
    src_init_path,
    submodule_search_locations=[backend_src_dir],
)
src_pkg = importlib.util.module_from_spec(spec)
sys.modules["src"] = src_pkg
spec.loader.exec_module(src_pkg)

# 6. Bootstrap database tables and seed records on first cloud launch
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

# 7. Import and expose FastAPI application instance
from src.main import app
