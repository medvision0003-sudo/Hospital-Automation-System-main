from sqlalchemy import create_engine, inspect, text

from app.database.migrations import _migrate_task_proof


def test_task_proof_migration_adds_metadata_without_losing_existing_rows():
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE employee (employee_id INTEGER PRIMARY KEY)"))
            connection.execute(text("CREATE TABLE users (user_id INTEGER PRIMARY KEY)"))
            connection.execute(
                text(
                    "CREATE TABLE task_proof "
                    "(proof_id INTEGER PRIMARY KEY, proof_image_path VARCHAR(255) NOT NULL)"
                )
            )
            connection.execute(
                text("INSERT INTO task_proof (proof_id, proof_image_path) VALUES (1, 'uploads/proof.jpg')")
            )

        inspector = inspect(engine)
        _migrate_task_proof(engine, inspector, "sqlite")

        with engine.connect() as connection:
            columns = {
                column["name"] for column in inspect(engine).get_columns("task_proof")
            }
            row = connection.execute(
                text(
                    "SELECT proof_id, proof_image_path, verification_attempts "
                    "FROM task_proof WHERE proof_id = 1"
                )
            ).one()

        assert {
            "employee_id",
            "ai_decision",
            "verification_attempts",
            "verified_at",
            "reviewer_user_id",
        }.issubset(columns)
        assert tuple(row) == (1, "uploads/proof.jpg", 1)
    finally:
        engine.dispose()
