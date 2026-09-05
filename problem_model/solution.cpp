#include "signature.hpp"

using namespace std;

string pegatina(int N, int K) {
    string resultado;
    for (int i = 1; i <= N; ++i) {
        if (i % K == 0) {
            resultado += to_string(i);
        }
    }
    return resultado;
}
