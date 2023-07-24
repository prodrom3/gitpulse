import os
import subprocess
import concurrent.futures

def update_repository(repo_path):
    print(f"Updating: {repo_path}")
    try:
        subprocess.run(["git", "pull"], cwd=repo_path, check=True)
        print(f"Successfully updated: {repo_path}")
    except subprocess.CalledProcessError as e:
        print(f"Error updating {repo_path}: {e}")

def main():
    root_directory = os.getcwd()

    repositories = []
    for root, dirs, files in os.walk(root_directory):
        if ".git" in dirs:
            repositories.append(root)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        executor.map(update_repository, repositories)

if __name__ == "__main__":
    main()

