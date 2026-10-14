"""
Single-entrypoint server runner for IoT Fleet Platform.
Can be executed from any folder or terminal, locally and on Render.com cloud.
"""
import os
import sys
import importlib.util

# 1. Determine project root
project_root = os.path.dirname(os.path.abspath(__file__))

# 2. Locate backend directory and application 'src' directory
def locate_backend_and_src(root):
    c1 = os.path.join(root, "backend", "src")
    if os.path.isdir(c1):
        return os.path.join(root, "backend"), c1

    c2 = os.path.join(root, "src")
    if os.path.isdir(c2) and (os.path.exists(os.path.join(c2, "api")) or os.path.exists(os.path.join(c2, "main.py"))):
        return root, c2

    for dirpath, dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) == "src" and ("api" in dirnames or "db" in dirnames or "main.py" in filenames):
            return os.path.dirname(dirpath), dirpath

    return os.path.join(root, "backend"), c1

backend_dir, backend_src_dir = locate_backend_and_src(project_root)

# 3. Ensure __init__.py files exist
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
