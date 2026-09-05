import argparse
import importlib
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("problem", type=str)
    args = parser.parse_args()
    
    problem_dir = Path(__file__).parent / args.problem
    assert problem_dir.is_dir()

    module = importlib.import_module(f"{args.problem}.generator")
    generate_files(module.Generator(), problem_dir)

def generate_files(generator, problem_dir):
    
    problem_name = problem_dir.name
    case_data = generator.get_cases()
    subtasks = generator.get_subtasks()

    cases = []

    (problem_dir / "cases").mkdir(exist_ok=True)
    for i, case in enumerate(case_data):
        input_name = f"{i}.in"
        output_name = f"{i}.out"
        case.write_file((problem_dir / "cases" / input_name).open("w"))
        cases.append((case, input_name, output_name))
    
    with (problem_dir / "init.yml").open("w") as f:
        f.write(f"archive: {problem_name}.zip\n")
        f.write("checker: checker.py\n")
        f.write("signature_grader: {entry: evaluator.cpp, header: signature.hpp}\n")
        f.write("test_cases:\n")
        for points, checker in subtasks:
            f.write(f"- points: {points}\n")
            f.write("  batched:\n")
            for case, input_name, output_name in cases:
                if checker(case):
                    f.write(f"  - {{ in: cases/{input_name}, out: cases/{output_name} }}\n")

if __name__ == "__main__":
    main()
