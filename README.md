# RepoRevamp - Efficient GitHub Repository Updater

RepoRevamp is a Python script designed to efficiently update multiple GitHub repositories present in the current directory and its subdirectories. It utilizes multi-threading to significantly improve the update process, making it a swift and agile tool for keeping your cloned repositories up-to-date.

## Purpose
Have you ever found yourself with a bunch of cloned GitHub repositories scattered across your local machine? Keeping them all up-to-date manually can be time-consuming and tedious. That's where RepoRevamp comes to the rescue! It automates the process of updating your repositories with the latest changes from their respective remotes on GitHub.


## Installation

1. Clone this repository to your local machine using the following command:

```bash
git clone https://github.com/yourusername/RepoRevamp.git
```
2. Navigate to the cloned directory:

```bash
cd RepoRevamp
```

3. Before running the script, ensure you have Python installed on your system. If not, you can download it from the official Python website: Python Downloads

4. Install the required requests library by executing the following command:

```bash
pip install requests
```

## Usage
1. Place the RepoRevamp.py script in the directory where your cloned GitHub repositories are located, or in a parent directory if they are spread across subdirectories.

2. Open a terminal or command prompt and navigate to the directory containing RepoRevamp.py.

3. Run the script using the following command:

```bash
python RepoRevamp.py
```

4. Sit back and relax while RepoRevamp works its magic! The script will efficiently update all your repositories using multi-threading, saving you precious time and effort.


## Logging
RepoRevamp also includes a logging feature to keep track of the repository updates. The log file named reporevamp.log will be created in the same directory where the script is located. This file will contain information about each repository's update status, and any errors encountered during the process.

Please review the log file if you encounter any issues during the updates. It will help you identify any errors and take appropriate actions if needed.

## Caution

- Before running the script, make sure to back up your repositories or have them safely stored on remote servers like GitHub to avoid any unintended data loss.
- Ensure that your repositories have the correct credentials (username/password or SSH keys) configured for Git, as the script will attempt to pull updates using your existing Git configurations.

## Contribution
If you find any bugs or have ideas for improvements, feel free to open an issue or create a pull request on this repository. Your contributions are highly appreciated!

Happy updating with RepoRevamp! 🚀
