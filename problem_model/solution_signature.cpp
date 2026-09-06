#include "signature.hpp"
#include <algorithm>
#include <vector>

using namespace std;

float solve(int N, const vector<long long>& a) {
	vector<long long> ys = a;
	sort(ys.begin(), ys.end());

	if (N % 2 == 1) {
		return static_cast<float>(ys[N / 2]);
	}
	return static_cast<float>(ys[N / 2 - 1] + ys[N / 2]) / 2.0f;
}
