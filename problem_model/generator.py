import random

class TestCase:
    def __init__(self, N, K):
        self.N = K
        self.K = K

    def write_file(self, f):
        f.write(f"{self.N} {self.K}\n")

class Generator:
    def __init__(self, seed=3141592):
        random.seed(seed)

    def get_cases(self):

        def todos(N):
            return ((N, K) for K in range(1, N+1))

        def randoms(max_N, max_K, cnt):
            max_K = min(max_N, max_K)
            def case():
                N = -2
                K = -1
                while N < K:
                    N = random.randint(1, max_N)
                    K = random.randint(1, max_K)
                return (N, K)
            return (case() for _ in range(cnt))

        casos = [
            # subtareas
            *todos(1),
            *((N, N) for N in (1, 7, 10, 51, 100, 127, 396, 789, 1000)),
            *todos(2),
            *todos(3),
            *todos(4),
            *((N, 1) for N in (1, 7, 10, 51, 100, 127, 396, 789, 1000)),

            # extremos
            (1000, 1000), (1000, 1),

            # aleatorios
            *randoms(10, 10, 5),
            *randoms(100, 10, 5),
            *randoms(100, 100, 5),
            *randoms(1000, 10, 5),
            *randoms(1000, 100, 5),
            *randoms(1000, 1000, 5),
        ]

        dedup = []
        for caso in casos:
            if caso not in dedup:
                dedup.append(caso)
        casos = dedup

        return [TestCase(N, K) for N, K in casos]

    def get_subtasks(self):
        def check_st1(case):
            return case.N == 1

        def check_st2(case):
            return case.N == case.K

        def check_st3(case):
            return case.N == 2

        def check_st4(case):
            return case.N == 3

        def check_st5(case):
            return case.N == 4

        def check_st6(case):
            return case.K == 1

        def check_st7(case):
            return True

        return [
            (5,  check_st1),
            (10, check_st2),
            (7,  check_st3),
            (9,  check_st4),
            (13, check_st5),
            (30, check_st6),
            (26, check_st7),
        ]
