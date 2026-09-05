import os
import sys
from pathlib import Path

def create_folder(path, modelpath):
    if os.path.exists(path):
        raise Exception("The folder for this problem has already been created")

    os.mkdir(path)
    copy(path, modelpath, "generator.py")
    copy(path, modelpath, "signature.hpp")
    copy(path, modelpath, "evaluator.cpp")
    copy(path, modelpath, "solution.cpp")
    copy(path, modelpath, "checker.py")
    os.mkdir(path / 'cases')

def copy(path, modelpath, filename):
    model = ""
    with open(modelpath.joinpath(filename), "r") as f:
        model = f.read()
    with open(path.joinpath(filename), "w") as f:
        f.write(model)

usage = """
usage: init_problem <problem_name>

Creates a new problem with a default folder structure and common utilities.
The folder is named after the <problem_name>.
"""

if len(sys.argv) > 1:
    try:
        p = Path(f'./{sys.argv[1]}')
        model = Path(f'./problem_model')
        create_folder(p, model)
    except Exception as error:
        print(error)
else:
    print(usage)
