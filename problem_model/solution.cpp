#include <algorithm>
#include <cstdio>
#include <iomanip>
#include <iostream>
#include <vector>

float median(int N, std::vector<long long>& a) {
	std::sort(a.begin(), a.end());
	if (N % 2 == 1) {
		return static_cast<float>(a[N / 2]);
	}
	return static_cast<float>(a[N / 2 - 1] + a[N / 2]) / 2.0f;
}

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
