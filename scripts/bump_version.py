#!/usr/bin/env python3
"""
Bump version script for mac-messages-mcp package.

Usage:
    python scripts/bump_version.py [major|minor|patch]
    python scripts/bump_version.py --help
    
Default is patch if no argument is provided.]
"""

import os
import re
import subprocess
import sys
from pathlib import Path

# Define version pattern
VERSION_PATTERN = r'\d+\.\d+\.\d+'

def print_help():
    """Print help information"""
    print(__doc__)
    sys.exit(0)

def get_current_version():
    """Read the current version from pyproject.toml"""
    pyproject_path = Path("pyproject.toml")
    if not pyproject_path.exists():
        print("Error: pyproject.toml not found!")
        sys.exit(1)
    
    content = pyproject_path.read_text()
    version_match = re.search(r'version = "(' + VERSION_PATTERN + ')"', content)
    if not version_match:
        print("Error: Could not find version in pyproject.toml!")
        sys.exit(1)
    
    return version_match.group(1)

def bump_version(current_version, bump_type):
    """Bump the version according to the specified type"""
    major, minor, patch = map(int, current_version.split('.'))
    
    if bump_type == "major":
        major += 1
        minor = 0
        patch = 0
    elif bump_type == "minor":
        minor += 1
        patch = 0
    elif bump_type == "patch":
        patch += 1
    else:
        print(f"Error: Invalid bump type '{bump_type}'!")
        print("Usage: python scripts/bump_version.py [major|minor|patch]")
        sys.exit(1)
    
    return f"{major}.{minor}.{patch}"

def update_files(new_version):
    """Update version in all relevant files"""
    # Update pyproject.toml
    pyproject_path = Path("pyproject.toml")
    content = pyproject_path.read_text()
    updated_content = re.sub(
        r'version = "' + VERSION_PATTERN + '"',
        f'version = "{new_version}"',
        content
    )
    pyproject_path.write_text(updated_content)
    
    # Update __init__.py
    init_path = Path("mac_messages_mcp/__init__.py")
    content = init_path.read_text()
    updated_content = re.sub(
        r'__version__ = "' + VERSION_PATTERN + '"',
        f'__version__ = "{new_version}"',
        content
    )
    init_path.write_text(updated_content)
    
    print(f"Updated version to {new_version} in pyproject.toml and __init__.py")

def create_git_tag(new_version):
    """Create a new git tag and push it"""
    tag_name = f"v{new_version}"
    
    # Create tag
    subprocess.run(["git", "tag", tag_name], check=True)
    print(f"Created git tag: {tag_name}")
    
    # Inform how to push the tag
    print("\nTo push the tag to GitHub and trigger a release, run:")
    print(f"  git push origin {tag_name}")

def main():
    # Check for help request
    if len(sys.argv) > 1 and sys.argv[1] in ["-h", "--help", "help"]:
        print_help()
    
    # Determine bump type
    bump_type = "patch"  # Default
    if len(sys.argv) > 1:
        bump_type = sys.argv[1].lower()
        if bump_type not in ["major", "minor", "patch"]:
            print(f"Invalid bump type: {bump_type}")
            print("Usage: python scripts/bump_version.py [major|minor|patch]")
            sys.exit(1)
    
    # Get current version
    current_version = get_current_version()
    print(f"Current version: {current_version}")
    
    # Bump version
    new_version = bump_version(current_version, bump_type)
    print(f"New version: {new_version}")
    
    # Update files
    update_files(new_version)
    
    # Ask to commit changes
    commit_changes = input("Do you want to commit these changes? [y/N]: ").lower()
    if commit_changes == "y":
        subprocess.run(["git", "add", "pyproject.toml", "mac_messages_mcp/__init__.py"], check=True)
        subprocess.run(["git", "commit", "-m", f"Bump version to {new_version}"], check=True)
        print("Changes committed.")
        
        # Create git tag
        create_tag = input(f"Do you want to create git tag v{new_version}? [y/N]: ").lower()
        if create_tag == "y":
            create_git_tag(new_version)

if __name__ == "__main__":
    main() 