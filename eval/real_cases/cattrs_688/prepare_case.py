"""Prepare a tracked local reproducer for python-attrs/cattrs pull request #688."""

import argparse
import os
import subprocess


UPSTREAM = "https://github.com/python-attrs/cattrs.git"
BASE_COMMIT = "29f3a4ecff1f375791c036493f67f38656c9d571"
HERE = os.path.dirname(os.path.abspath(__file__))


def run(*args, cwd=None):
    subprocess.run(args, cwd=cwd, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("destination")
    args = parser.parse_args()
    destination = os.path.realpath(args.destination)
    if os.path.exists(destination):
        raise SystemExit(f"destination already exists: {destination}")
    run("git", "clone", UPSTREAM, destination)
    run("git", "checkout", "--detach", BASE_COMMIT, cwd=destination)
    run("git", "apply", os.path.join(HERE, "reproduction.patch"), cwd=destination)
    run("git", "add", "tests", cwd=destination)
    run(
        "git", "-c", "user.name=Luna Case Reproducer",
        "-c", "user.email=luna@example.invalid", "commit",
        "-m", "test: reproduce upstream pull request 688", cwd=destination,
    )
    print(destination)


if __name__ == "__main__":
    main()
