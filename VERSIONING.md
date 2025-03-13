# Versioning System

This project uses automatic semantic versioning that follows the [SemVer](https://semver.org/) specification (MAJOR.MINOR.PATCH).

## How Versioning Works

The versioning system combines manual and automatic processes:

1. **Local Development**: Developers use the `scripts/bump_version.py` script to manually increment version numbers.
2. **CI/CD Pipeline**: When a version tag is pushed, the GitHub Actions workflow automatically builds and publishes the package with the correct version number.

## Version Bumping

### Using the Bump Script

We provide a convenient script to bump version numbers across all relevant files:

```bash
# To increment the patch version (0.1.0 -> 0.1.1)
python scripts/bump_version.py patch

# To increment the minor version (0.1.0 -> 0.2.0)
python scripts/bump_version.py minor

# To increment the major version (0.1.0 -> 1.0.0)
python scripts/bump_version.py major
```

The script will:
1. Update the version in `pyproject.toml`
2. Update the version in `mac_messages_mcp/__init__.py`
3. Optionally commit the changes
4. Optionally create a Git tag

### Publishing a New Version

To publish a new version:

1. Bump the version using the script above
2. Push the tag to GitHub:

```bash
git push origin vX.Y.Z
```

This will trigger the GitHub Actions workflow which will:
1. Build the package with the new version
2. Publish it to PyPI

## Version Files

Versions are stored in the following files:

- `pyproject.toml`: The primary source of version information for the package
- `mac_messages_mcp/__init__.py`: Contains the `__version__` variable used by the package
- Git tags: Used to trigger releases and provide version history

## Versioning Guidelines

Follow these guidelines when deciding which version to bump:

- **PATCH** (0.0.X): Bug fixes and other minor changes
- **MINOR** (0.X.0): New features or improvements that don't break existing functionality
- **MAJOR** (X.0.0): Changes that break backward compatibility

Always test the package before releasing a new version, especially for MAJOR and MINOR releases. 