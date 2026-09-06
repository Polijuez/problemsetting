import sys
import argparse
import yaml
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("problem", type=str)
    parser.add_argument("--problemtype", type=str, default="standard")
    parser.add_argument("--solutionlang", type=str, default=".cpp")
    args = parser.parse_args()

    path = Path(f'./{args.problem}')
    model = Path(f'./problem_model')

    if path.exists():
        print("The folder for this problem has already been created", file=sys.stderr)

    path.mkdir()
    for file in get_selection(args):
        copy(model, path, file)
        
    if args.problemtype == "signature":
        copy(model, path, "solution_signature.cpp")
    else:
        copy(model, path, f"solution{args.solutionlang}")

        
    meta = {"problem": args.problem,
            "problemtype": args.problemtype,
            "solutionlang": args.solutionlang}

    with (path / "meta.yml").open("w") as f:
        yaml.safe_dump(meta,f)

def copy(model, path, file):
    with (model / file).open("r") as f:
        cont = f.read()
    with (path / file).open("w") as f:
        f.write(cont)

def get_selection(args):
    match (args.problemtype):
        case ("standard"):
            return ["checker.py","generator.py"]
        case ("signature"):
            return ["checker.py","generator.py","signature.hpp","evaluator.cpp"]
    return None

if __name__ == "__main__":
    main()
