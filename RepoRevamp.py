import os
import subprocess
import concurrent.futures
import logging
import datetime
import sys

def update_repository(repo_path):
    logging.info(f"Updating: {repo_path}")
    try:
        subprocess.run(["git", "pull"], cwd=repo_path, check=True)
        logging.info(f"Successfully updated: {repo_path}")
        return repo_path
    except subprocess.CalledProcessError as e:
        print(f"Error updating {repo_path}: {e}")

def setup_logging():
    logs_directory = "logs"
    if not os.path.exists(logs_directory):
        os.makedirs(logs_directory)

    log_file_name = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + ".log"
    log_file_path = os.path.join(logs_directory, log_file_name)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s]: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file_path, mode="w")
        ]
    )


def main():
    setup_logging()
    if len(sys.argv) > 1:
        root_directory = sys.argv[1]
    else:
        root_directory = os.getcwd()

    repositories = []
    for root, dirs, files in os.walk(root_directory):
        if ".git" in dirs:
            repositories.append(root)

    updated_repositories = set()
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = executor.map(update_repository, repositories)
        for result in results:
            if result:
                updated_repositories.add(result)

    if updated_repositories:
        print("\nRepositories successfully updated:")
        for repo in updated_repositories:
            print(repo)

if __name__ == "__main__":
    main()

