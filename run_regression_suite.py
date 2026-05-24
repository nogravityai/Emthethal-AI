#!/usr/bin/env python3
# Host wrapper to execute the regression suite inside the running docker container
import subprocess
import sys

def main():
    cmd = ["docker", "exec", "-t", "emthethal_backend", "python3", "/app/scripts/run_regression_suite.py"] + sys.argv[1:]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
