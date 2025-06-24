# GitRepo Tools

<p align="center">
  <img src="https://img.shields.io/badge/Version-3.0.3-blue.svg" alt="Version"/>
  <img src="https://img.shields.io/badge/Arch-Linux-1793D1.svg?logo=arch-linux" alt="Arch Linux"/>
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"/>
</p>

A comprehensive set of tools for BigCommunity Linux distribution development and management. Includes tools for package building (Build Package) and ISO image generation (Build ISO).

## Included Tools

### Build Package

A comprehensive tool for package building, testing, and deployment. Streamlines Git operations, automates builds and manages package workflows for BigCommunity repositories and AUR packages.

<p align="center">
   <img src="https://github.com/user-attachments/assets/72484258-00f3-4c30-b136-baea8388a661" alt="build-package" />
</p>

### Build ISO

A specialized tool for creating and managing Linux distribution ISO images. Automates the process of creating custom ISOs through GitHub Actions integration.

<p align="center">
   <img src="https://github.com/user-attachments/assets/64f2e9b7-0f1e-4978-b453-b71db3f2c59b" alt="build-iso" />
</p>

## Build Package

### Overview

Build Package is a specialized tool designed to simplify the package building process for BigCommunity repositories. It provides a streamlined interface for common Git operations, automates package builds, and integrates with GitHub Actions workflows for continuous integration.

### Features

- **Interactive TUI Interface** - User-friendly terminal interface with colored menus
- **Git Integration** - Automated commit, push, and branch management
- **Package Building** - Generate packages from repositories with simplified workflows
- **AUR Support** - Build packages directly from the Arch User Repository
- **CI/CD Integration** - Trigger GitHub Actions workflows automatically
- **Repository Management** - Clean up old branches, tags, and CI jobs

### Requirements

- Python 3.6+
- Git
- curl
- Rich library for Python
- Arch Linux environment (or compatible)

### Installation

#### Using package (recommended)

Install the package using your package manager:

```bash
sudo pacman -U gitrepo-25.05.24-0106-x86_64.pkg.tar.zst
```

Or build and install from source:

```bash
cd pkgbuild
makepkg -si
```

### Usage

#### Interactive Mode

Simply run the command without arguments to enter interactive mode:

```bash
bpkg
```

#### Command Line Arguments

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

## Build ISO

### Overview

Build ISO is a powerful tool designed to simplify the creation of Linux distribution ISO images. It features a **plug-and-play architecture** that allows anyone to easily add their organization and create custom ISOs without modifying the main code. The tool automates the entire process through GitHub Actions integration and dynamically fetches available options from ISO profile repositories.

### Features

- **Plug-and-Play Configuration** - Add new organizations by simply editing the configuration file
- **Dynamic Content Discovery** - Automatically detects available build directories and desktop editions from ISO profile repositories via GitHub API
- **Interactive Menu Interface** - User-friendly navigation with colored terminal menus
- **GitHub Actions Integration** - Trigger ISO build workflows remotely with comprehensive status monitoring
- **Multi-Organization Support** - Pre-configured for BigCommunity, BigLinux, and community forks
- **Distribution Customization** - Support for various Manjaro-based distributions with flexible branching
- **Desktop Editions** - Automatically discovers available desktop environments from your ISO profiles
- **Kernel Selection** - Options for different kernel versions (latest, lts, oldlts, xanmod)
- **Automatic Mode** - Zero-interaction builds using organization-specific defaults
- **Real-time Validation** - All options are validated against live repository contents

### Requirements

- Python 3.6+
- Git
- curl
- Rich library for Python
- GitHub API token with appropriate permissions

### Installation

Build ISO is distributed as part of the GitRepo package:

```bash
sudo pacman -U gitrepo-1.0.0-1-any.pkg.tar.zst
```

### Usage

#### Interactive Mode

Run the command without arguments to enter interactive mode:

```bash
build-iso
```

This displays a menu with available options to configure and build an ISO. All build directories and editions are dynamically fetched from your chosen ISO profiles repository.

#### Automatic Mode

Use automatic mode for quick builds with predefined settings:

```bash
# Build with organization defaults
build-iso -o big-comm --auto

# Override specific settings
build-iso -o biglinux --auto -e kde -k latest
```

#### Command Line Arguments

```
Usage: build-iso [options]

Options:
  -o, --org, --organization  Configure GitHub organization (default: big-comm)
  -d, --distro, --distroname Set the distribution name
  -e, --edition              Set the edition (desktop environment)
  -k, --kernel               Set the kernel type
  -a, --auto, --automatic    Automatic mode using default values
  -n, --nocolor              Suppress color printing
  -V, --version              Print application version
  -t, --tmate                Enable tmate for debugging
```

### Adding Your Organization

The tool is designed to be **completely plug-and-play**. To add your organization:

1. **Add your organization to the valid list** in `config.py`:

```python
VALID_ORGANIZATIONS = [
    "big-comm",
    "biglinux", 
    "talesam",
    "leoberbert",
    "your-organization"  # Add here
]
```

2. **Configure your ISO profiles repository** (if you have one):

```python
ISO_PROFILES = [
    "https://github.com/big-comm/iso-profiles",
    "https://github.com/biglinux/iso-profiles",
    "https://github.com/leoberbert/iso-profiles",
    "https://github.com/your-organization/iso-profiles"  # Add here
]

DEFAULT_ISO_PROFILES = {
    "big-comm": "https://github.com/big-comm/iso-profiles",
    "biglinux": "https://github.com/biglinux/iso-profiles", 
    "leoberbert": "https://github.com/leoberbert/iso-profiles",
    "your-organization": "https://github.com/your-organization/iso-profiles"
}

API_PROFILES = {
    "https://github.com/big-comm/iso-profiles": "https://api.github.com/repos/big-comm/iso-profiles/contents/",
    "https://github.com/biglinux/iso-profiles": "https://api.github.com/repos/biglinux/iso-profiles/contents/",
    "https://github.com/leoberbert/iso-profiles": "https://api.github.com/repos/leoberbert/iso-profiles/contents/",
    "https://github.com/your-organization/iso-profiles": "https://api.github.com/repos/your-organization/iso-profiles/contents/"
}
```

3. **Set your default configuration** in the `ORG_DEFAULT_CONFIGS` section:

```python
ORG_DEFAULT_CONFIGS = {
    # ... existing configurations ...
    
    "your-organization": {
        "distroname": "bigcommunity",  # or "biglinux" or your own distro
        "iso_profiles_repo": "https://github.com/your-organization/iso-profiles", 
        "branches": {
            "manjaro": "stable",     # stable, testing, unstable
            "community": "stable",   # stable, testing, unstable (leave "" if not used)
            "biglinux": "stable"     # stable, testing, unstable (leave "" if not used)
        },
        "kernel": "latest",          # latest, lts, oldlts, xanmod
        "build_dir": "bigcommunity", # directory name in your iso-profiles repository
        "edition": "xfce"            # your preferred default desktop environment
    }
}
```

**That's it!** Your organization is now fully integrated. The tool will:
- ✅ Automatically discover your available build directories via GitHub API
- ✅ Dynamically fetch your available desktop editions
- ✅ Work in both interactive and automatic modes
- ✅ Use your custom defaults when running `--auto` mode

### Configuration Fields Explained

- **distroname**: Base distribution (`"bigcommunity"` or `"biglinux"`)
- **iso_profiles_repo**: URL to your ISO profiles repository
- **branches**: Version branches for each component:
  - `manjaro`: Manjaro base system branch (stable/testing/unstable)
  - `community`: BigCommunity customizations branch (leave `""` if not used)
  - `biglinux`: BigLinux customizations branch (leave `""` if not used)
- **kernel**: Default kernel type (`latest`, `lts`, `oldlts`, `xanmod`)
- **build_dir**: Directory name in your iso-profiles repository (validated via API)
- **edition**: Default desktop environment (validated via API)

## GitHub Token Configuration

Both tools require a GitHub Personal Access Token with specific permissions.

### Creating a GitHub Token

1. Go to GitHub Settings > Developer settings > Personal access tokens > Tokens (classic)
2. Click "Generate new token" > "Generate new token (classic)"
3. Add a descriptive note (e.g. "CD/CI Community - Big-Comm")
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
talesam=ghp_another_token_here
```

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
    │   ├── bpkg              # Build Package executable script
    │   └── build-iso         # Build ISO executable script
    └── share/
        └── gitrepo/          # Application files
            ├── build_package/
            │   ├── main.py            # Entry point
            │   ├── config.py          # Configuration settings
            │   ├── logger.py          # Logging system
            │   ├── git_utils.py       # Git repository utilities
            │   ├── github_api.py      # GitHub API interaction
            │   ├── menu_system.py     # Interactive menu system
            │   └── build_package.py   # Main package class
            └── build_iso/
                ├── main.py            # Entry point
                ├── config.py          # Configuration settings
                ├── logger.py          # Logging system
                ├── git_utils.py       # Git repository utilities
                ├── github_api.py      # GitHub API interaction
                ├── menu_system.py     # Interactive menu system
                └── build_iso.py       # Main ISO class
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
