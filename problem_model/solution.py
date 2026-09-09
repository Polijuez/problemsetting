import sys


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2 == 1:
        return float(ys[mid])
    return (ys[mid - 1] + ys[mid]) / 2.0


def main():
    data = list(map(int, sys.stdin.read().split()))
    n = data[0]
    xs = data[1 : 1 + n]
    sys.stdout.write(f"{median(xs):.1f}\n")


if __name__ == "__main__":
    main()
