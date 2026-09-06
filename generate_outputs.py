import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import yaml

hashes = {
    "files": {},
    "deps": {},
}

class Target:
    def __init__(self, path, build, deps=None):
        self.path = path
        self._build = build
        self.deps = deps or []
        self.result = None

    def add_dep(self, dep):
        self.deps.append(dep)

    # INV: is only called after all deps are built and their hashes are updated
    def build(self):

        if not self.is_up_to_date():
            self._build()
            hashes["files"][str(self.path)] = file_checksum(self.path)
            hashes["deps"][str(self.path)] = {str(dep.path): hashes["files"][str(dep.path)] for dep in self.deps}

    def is_up_to_date(self):
        if str(self.path) not in hashes["files"] or str(self.path) not in hashes["deps"]:
            return False

        for dep in self.deps:
            if hashes["deps"][str(self.path)].get(str(dep.path), "") != hashes["files"][str(dep.path)]:
                return False

        if not self.path.exists():
            return False

        if len(self.deps) == 0:
            return False

        return True

def do_nothing():
    return

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("problem", type=str)
    args = parser.parse_args()

    problem_dir = Path(__file__).parent / args.problem

    metadata_dir = problem_dir / "__meta__"
    metadata_dir.mkdir(exist_ok=True)

    global hashes

    hash_file = metadata_dir / "hashes.json"
    if hash_file.exists():
        with hash_file.open("r") as f:
            hashes = json.load(f)

    cases_dir = problem_dir / "cases"
    cases_dir.mkdir(exist_ok=True)

    outputs = []

    meta_file = problem_dir / 'meta.yml'
    if meta_file.exists():
        with meta_file.open() as f:
            metadata = yaml.safe_load(f.read())
    else:
        metadata=dict()

    metadata.setdefault('problemtype','standard')
    metadata.setdefault('solutionlang','.cpp')

    runner = get_runner(metadata)
    solution_src_path = problem_dir / f"solution{metadata['solutionlang']}"
    solution_src = Target(solution_src_path, do_nothing)

    if metadata['problemtype'] == 'signature' and metadata['solutionlang'] == '.cpp':
        evaluator_src_path = problem_dir / "evaluator.cpp"
        signature_hdr_path = problem_dir / "signature.hpp"

        signature_hdr = Target(signature_hdr_path, do_nothing)
        evaluator_src = Target(evaluator_src_path, do_nothing)

        exe_path = problem_dir / "solution.exe"

        exe = Target(exe_path, runner.compile_solution(solution_src_path, exe_path), [signature_hdr, solution_src, evaluator_src])

    elif metadata['solutionlang'] == '.cpp':
        exe_path = problem_dir / "solution.exe"

        exe = Target(exe_path, runner.compile_solution(solution_src_path,exe_path), [solution_src])

    elif metadata['solutionlang'] == '.py':
        exe_path = solution_src_path

        exe = Target(exe_path, runner.compile_solution(solution_src_path,exe_path), [solution_src])
    elif metadata['solutionlang'] == '.hs':
        exe_path = problem_dir / "solution.exe"

        exe = Target(exe_path, runner.compile_solution(solution_src_path,exe_path), [solution_src])

    else:
        raise Exception

    for case in cases_dir.glob("*.in"):
        case_in = Target(case, do_nothing)
        case_out = Target(case.with_suffix(".out"), runner.run_solution(exe.path, case), [exe, case_in])
        outputs.append(case_out)

    order = []
    visited = set()
    def visit(target):
        visited.add(target)
        for dep in target.deps:
            if dep not in visited:
                visit(dep)
        order.append(target)
    for output in outputs:
        visit(output)

    with ThreadPoolExecutor() as executor:

        for target in order:

            # wait for deps to finish
            for dep in target.deps:
                dep.result.result()

            target.result = executor.submit(lambda t=target: t.build())

        # wait for all targets to finish
        for target in order:
            target.result.result()

    with hash_file.open("w") as f:
        json.dump(hashes, f)


def file_checksum(path, algo='md5', chunk_size=8192):
    h = hashlib.new(algo)
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(chunk_size), b''):
            h.update(chunk)
    return h.hexdigest()


class CppRunner:
    def compile_solution(self, src, exe):
        def task():
            command = ["g++", str(src), "-o", str(exe)]
            print(' '.join(command), file=sys.stderr)
            subprocess.run(command)
        return task


    def run_solution(self, exe, case):
        def task():
            output = case.with_suffix(".out")
            print(str(exe), str(case), str(output), file=sys.stderr)
            subprocess.run([str(exe), str(case), str(output)])
        return task


class CppSignatureRunner(CppRunner):
    def compile_solution(self, src, exe):
        def task():
            evaluator = src.with_name('evaluator.cpp')
            command = ["g++", str(src), str(evaluator), "-o", str(exe)]
            print(' '.join(command), file=sys.stderr)
            subprocess.run(command)

        return task

class PythonRunner:
    def compile_solution(self, src, exe):
        return do_nothing

    def run_solution(self, exe, case):
        def task():
            command = ['uv','run','python3',str(exe)]
            print(' '.join(command), file=sys.stderr)
            subprocess.run(command)

        return task

class HaskellRunner:
    def compile_solution(self, src, exe):
        def task():
            command = ["ghc", str(src), "-o", str(exe)]
            print(' '.join(command), file=sys.stderr)
            subprocess.run(command)
        return task

    def run_solution(self, exe, case):
        def task():
            output = case.with_suffix(".out")
            print(str(exe), str(case), str(output), file=sys.stderr)
            subprocess.run([str(exe), str(case), str(output)])
        return task

def get_runner(metadata):
    match (metadata['problemtype'], metadata['solutionlang']):
        case ('standard', '.cpp'):
            return CppRunner()
        case ('signature', '.cpp'):
            return CppSignatureRunner()
        case (_, '.hs'):
            return HaskellRunner()
        case (_, '.py'):
            return PythonRunner()
    return None


if __name__ == '__main__':
    main()
