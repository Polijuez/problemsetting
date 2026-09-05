#include "signature.hpp"
#include <iostream>
int main(int argc, char** argv) {
	if (argc > 1) {
		freopen(argv[1], "r", stdin);
		freopen(argv[2], "w", stdout);
	}

	int N, K;
	std::cin >> N >> K;
	std::cout << pegatina(N, K) << "\n";
}
