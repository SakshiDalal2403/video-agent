import os
import shutil


VECTOR_RUNS_DIR = os.path.join("vector_db", "runs")


def main():
    if os.path.exists(VECTOR_RUNS_DIR):
        shutil.rmtree(VECTOR_RUNS_DIR)

    os.makedirs(VECTOR_RUNS_DIR, exist_ok=True)
    print(f"Cleaned vector database runs at: {VECTOR_RUNS_DIR}")


if __name__ == "__main__":
    main()
