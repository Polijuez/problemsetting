import sys


def median(xs):
    ys = sorted(xs)
    n = len(ys)
    mid = n // 2
    if n % 2 == 1:
        return float(ys[mid])
    return (ys[mid - 1] + ys[mid]) / 2.0


def main():
    if len(sys.argv) > 1:
        fin = open(sys.argv[1], "r")
        fout = open(sys.argv[2], "w")
    else:
        fin = sys.stdin
        fout = sys.stdout

    data = list(map(int, fin.read().split()))
    n = data[0]
    xs = data[1 : 1 + n]
    fout.write(f"{median(xs):.1f}\n")

    if len(sys.argv) > 1:
        fin.close()
        fout.close()


if __name__ == "__main__":
    main()
