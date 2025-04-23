# Build Package

<p align="center">
  <img src="https://img.shields.io/badge/Version-3.0.0-blue.svg" alt="Version"/>
  <img src="https://img.shields.io/badge/Arch-Linux-1793D1.svg?logo=arch-linux" alt="Arch Linux"/>
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"/>
</p>

A comprehensive tool for package building, testing, and deployment. Streamlines Git operations, automates builds and manages package workflows for BigCommunity repositories and AUR packages.

<p align="center">
   <img src="https://github.com/user-attachments/assets/cf5e01ff-a01f-45e3-9710-b585a9942d6d" alt="build-package" />
</p>

## Overview

Build Package is a specialized tool designed to simplify the package building process for BigCommunity repositories. It provides a streamlined interface for common Git operations, automates package builds, and integrates with GitHub Actions workflows for continuous integration.

## Features

- **Interactive TUI Interface** - User-friendly terminal interface with colored menus
- **Git Integration** - Automated commit, push, and branch management
- **Package Building** - Generate packages from repositories with simplified workflows
- **AUR Support** - Build packages directly from the Arch User Repository
- **CI/CD Integration** - Trigger GitHub Actions workflows automatically
- **Repository Management** - Clean up old branches, tags, and CI jobs

## Requirements

- Python 3.6+
- Git
- curl
- Rich library for Python
- Arch Linux environment (or compatible)

## Installation

### Using package (recommended)

Install the package using your package manager:

```bash
sudo pacman -U build-package-3.0.0-1-any.pkg.tar.zst
```

Or build and install from source:

```bash
cd pkgbuild
makepkg -si
```

## Configuration

The tool uses `config.py` for main configuration settings:

```python
# Repository settings
REPO_WORKFLOW = "big-comm/build-package"  # Repository containing workflows
DEFAULT_ORGANIZATION = "big-comm"         # Default organization
VALID_ORGANIZATIONS = ["big-comm", "biglinux"]  # Valid organizations

# File containing GitHub token
TOKEN_FILE = "~/.GITHUB_TOKEN"

# Branch settings
VALID_BRANCHES = ["testing", "stable", "extra"]

# Log directory
LOG_DIR_BASE = "/tmp/build-package"
```

GitHub authentication is handled through a token file. Create a file at `~/.GITHUB_TOKEN` with either:
- A single token value
- Multiple tokens in format `organization=token` for different organizations

## GitHub Token Configuration

The application requires a GitHub Personal Access Token with specific permissions to interact with repositories, workflows, and packages.

### Creating a GitHub Token

1. Go to GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)
2. Click "Generate new token" > "Generate new token (classic)"
3. Add a descriptive note (e.g. "CD/CI Community Packages - Big-Comm")
4. Configure the token with these required permissions:
   - `repo` - Full control of repositories (for commit, branch, and PR operations)
   - `workflow` - Update GitHub Action workflows (for triggering builds)
   - `write:packages` - Upload packages to GitHub Package Registry
   - `delete:packages` - Delete packages from GitHub Package Registry (for cleanup)

5. Click "Generate token" and copy the token value

### Saving the Token

Create a file at `~/.GITHUB_TOKEN` containing the token. You can use either format:

```bash
# Single token
ghp_your_token_here

# OR multiple tokens for different organizations
big-comm=ghp_your_token_here
biglinux=ghp_your_different_token_here

## Usage

### Interactive Mode

Simply run the command without arguments to enter interactive mode:

```bash
bpkg
```

This displays a menu with available options:
- Commit and push
- Generate package (commit + branch + build)
- Build AUR package
- Advanced menu

### Command Line Arguments

```
Usage: bpkg [options]

Options:
  -o, --org, --organization  Configure GitHub organization (default: big-comm)
  -b, --build                Commit/push and generate package (testing|stable|extra)
  -c, --commit               Just commit/push with the specified message
  -a, --aur                  Build AUR package
  -n, --nocolor              Suppress color printing
  -V, --version              Print application version
  -t, --tmate                Enable tmate for debugging
  -h, --help                 Show this help message and exit
```

## Examples

### Commit changes

```bash
bpkg --commit "Update package dependencies"
```

### Build a testing package

```bash
bpkg --build testing --commit "Fix build issues"
```

### Build an AUR package

```bash
bpkg --aur package-name
```

### Using a different organization

```bash
bpkg --org biglinux --build stable --commit "Release version 2.0"
```

## Advanced Features

The advanced menu provides additional options:
- Delete branches (except main and the latest branches)
- Delete Action jobs with failures
- Delete Action jobs with success status
- Delete all tags

## Project Structure

```
/
├── LICENSE
├── pkgbuild/
│   ├── PKGBUILD              # Package build script
│   └── pkgbuild.install      # Install script
├── README.md
└── usr/
    ├── bin/
    │   └── bpkg              # Executable script
    └── share/
        └── build-package/    # Application files
            ├── main.py       # Entry point
            ├── config.py     # Configuration settings
            ├── logger.py     # Logging system
            ├── git_utils.py  # Git repository utilities
            ├── github_api.py # GitHub API interaction
            ├── menu_system.py # Interactive menu system
            └── build_package.py # Main package class
```

## Troubleshooting

- **Permission issues**: Ensure the script has execution permissions.
- **Token errors**: Verify that your GitHub token is correctly configured.
- **Git errors**: Make sure you're inside a valid Git repository.

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- BigCommunity
- Arch Linux
- Rich library for Python
