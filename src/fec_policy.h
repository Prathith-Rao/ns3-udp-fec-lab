#ifndef PROJECT_FEC_POLICY_H
#define PROJECT_FEC_POLICY_H
#include <algorithm>
#include <cmath>
#include <string>
#include <vector>
namespace fecproject
{
struct Choice
{
    unsigned k{4}, depth{1};
    double predicted{0}, repairMs{0};
    bool targetMet{false};
    std::string reason;
};
// A project policy, not a new erasure code. IID estimates do not guarantee burst recovery.
inline Choice Choose(double p, unsigned burst, double delay, double interval, double deadline,
                     double budget, double target, bool full)
{
    p = std::clamp(p, 0.0, 1.0);
    Choice plain{1, 1, 1 - p, delay, 1 - p >= target, "direct delivery meets target"};
    if (plain.targetMet)
        return plain;
    const unsigned preferredDepth = full && burst >= 2 ? 2 : 1;
    std::vector<Choice> candidates;
    for (unsigned attempt = 0; attempt < (preferredDepth == 2 ? 2U : 1U); ++attempt)
    {
        const unsigned depth = attempt == 0 ? preferredDepth : 1;
        for (unsigned k : {8U, 4U, 2U})
        {
            if (1.0 / k > budget + 1e-9)
                continue;
            const double worst = (k - 1) * depth * interval + delay + 5;
            if (full && worst > deadline)
                continue;
            const double prediction = 1 - p + p * std::pow(1 - p, k);
            candidates.push_back({k, depth, prediction, worst, prediction >= target,
                                  depth == 2 ? "burst observed; interleave within deadline"
                                  : preferredDepth == 2
                                      ? "interleaving infeasible; shorter ordinary group"
                                      : "loss observed; protect within budget"});
        }
        if (!candidates.empty())
            break;
    }
    for (const auto &c : candidates)
        if (c.targetMet)
            return c;
    if (candidates.empty())
    {
        plain.reason = "no repair configuration fits constraints";
        return plain;
    }
    auto best =
        *std::max_element(candidates.begin(), candidates.end(), [](const Choice &a, const Choice &b)
                          { return a.predicted < b.predicted; });
    best.reason = "target infeasible; strongest permitted protection";
    return best;
}
} // namespace fecproject
#endif
