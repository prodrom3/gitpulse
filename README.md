# RepoRevamp

#### Efficient GitHub Repository Updater

`RepoRevamp` is a Python script designed to efficiently update multiple GitHub repositories present in the current directory and its subdirectories. It utilizes multi-threading to significantly improve the update process, making it a swift and agile tool for keeping your cloned repositories up-to-date.

## Purpose
Have you ever found yourself with a bunch of cloned GitHub repositories scattered across your local machine? 

Keeping them all up-to-date manually can be time-consuming and tedious. That's where `RepoRevamp` comes to the rescue! It automates the process of updating your repositories with the latest changes from their respective remotes on GitHub.

## Features
- `Efficient and Fast:` RepoRevamp uses multi-threading to update repositories concurrently, saving you time and effort.
- `Custom Logging:` The script generates a new log file for each run with a timestamp, storing all update information in the "logs" directory.
- `Flexible Usage:` You can provide a specific folder path as an argument to update repositories in that folder and its sub-folders. Otherwise, the script defaults to updating the current directory and its sub-folders.
- `Repository Success Output:` The script outputs the names of repositories that were successfully updated, making it easy to track the updated repositories.

## Installation


1. Clone this repository to your local machine using the following command:

```bash
git clone https://github.com/yourusername/RepoRevamp.git
```
2. Navigate to the cloned directory:

```bash
cd RepoRevamp
```

3. Before running the script, ensure you have Python installed on your system. If not, you can download it from the official Python website: [Python Downloads](https://www.python.org/downloads/)

4. Install the required `requests` library by executing the following command:

```bash
pip install requests
```

## Usage

1. Place the RepoRevamp.py script in the directory where your cloned GitHub repositories are located, or in a parent directory if they are spread across subdirectories.

2. Open a terminal or command prompt and navigate to the directory containing `RepoRevamp.py`.

3. Run the script using the following command:

```bash
python RepoRevamp.py [optional_folder_path]
```

If you provide an optional folder path, the script will update repositories in that folder and its sub-folders. Otherwise, it will default to updating the current directory and its sub-folders.

4. Sit back and relax while RepoRevamp works its magic! The script will efficiently update all your repositories using multi-threading, saving you precious time and effort.



## Logging
RepoRevamp also includes a logging feature to keep track of the repository updates. It automatically generates a new log file for each run. The log files are stored in the "logs" directory with a timestamp in the filename. Each log file contains information about each repository's update status, including any errors encountered during the process.

Please review the log file if you encounter any issues during the updates. It will help you identify any errors and take appropriate actions if needed.

## Caution

- Before running the script, make sure to back up your repositories or have them safely stored on remote servers like GitHub to avoid any unintended data loss.
- Ensure that your repositories have the correct credentials (username/password or SSH keys) configured for Git, as the script will attempt to pull updates using your existing Git configurations.

## Contribution
If you find any bugs or have ideas for improvements, feel free to open an issue or create a pull request on this repository. Your contributions are highly appreciated!

Happy updating with RepoRevamp! 🚀
