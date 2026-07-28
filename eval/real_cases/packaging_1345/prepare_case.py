"""Prepare a tracked local reproducer for pypa/packaging pull request #1345."""

import argparse
import os
import subprocess


UPSTREAM = "https://github.com/pypa/packaging.git"
BASE_COMMIT = "0bfc3cea4f9fe1b1b0c80ce06f02bd2433500c81"
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
        "-m", "test: reproduce upstream pull request 1345", cwd=destination,
    )
    print(destination)


if __name__ == "__main__":
    main()
