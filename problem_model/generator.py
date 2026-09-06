import random

class TestCase:
    def __init__(self, N, xs):
        self.N = N
        self.xs = xs

    def check(self):
        assert(len(self.xs) == self.N)
        assert(all(1 <= x <= 10**9 for x in self.xs))
        assert(self.N<=10**5)

    def write_file(self, f):
        f.write(f"{self.N}\n")
        f.write(" ".join(map(str, self.xs)) + "\n")

def gen_st1(cases):
    return [TestCase(5,[1,2,3,4,5]),
            TestCase(5,[1,1,1,1,1]),
            TestCase(5,[10**9,10**9,10**9,10**9,10**9]),
            TestCase(6,[1,2,3,4,5,6])]

class Generator:
    def __init__(self, seed=3141592):
        random.seed(seed)

    def get_cases(self):
        casos = []
        
        gen_st1(casos)

        return casos

    def get_subtasks(self):
        def check_st1(case):
            return True

        return [
            (100, check_st1),
        ]
