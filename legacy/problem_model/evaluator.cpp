#include "signature.hpp"
#include <cstdio>
#include <iomanip>
#include <iostream>
#include <vector>

int main(int argc, char** argv) {
	if (argc > 1) {
		freopen(argv[1], "r", stdin);
		freopen(argv[2], "w", stdout);
	}

	int N;
	std::cin >> N;
	std::vector<long long> a(N);
	for (int i = 0; i < N; i++) {
		std::cin >> a[i];
	}
	std::cout << std::fixed << std::setprecision(1) << median(N, a) << "\n";
}
