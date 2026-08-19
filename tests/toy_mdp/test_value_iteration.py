"""Hand-verifiable toy MDPs, built directly (bypassing concretize/real actions)
to test value_iteration.py in isolation against closed-form answers."""
from poe2craft.domain.items import Rarity
from poe2craft.solver.featurize import AbstractState
from poe2craft.solver.model_learning import MDP
from poe2craft.solver.value_iteration import value_iteration


class _FakeAction:
    def __init__(self, name: str, cost: float):
        self.name = name
        self._cost = cost

    def cost(self) -> float:
        return self._cost


def _state(satisfied: bool) -> AbstractState:
    return AbstractState(rarity=Rarity.RARE, prefix_count=0, suffix_count=0, status=(2 if satisfied else 0,))


def test_geometric_wait_matches_1_over_p():
    """One action, success probability p per attempt, reward -1/step. Expected
    steps to succeed is the classic geometric-distribution mean 1/p."""
    S, G = _state(False), _state(True)
    p = 0.25
    mdp = MDP(start=S, states={S, G}, goal_states={G}, transitions={(S, "try"): {G: p, S: 1 - p}})
    actions = {"try": _FakeAction("try", cost=1.0)}

    result = value_iteration(mdp, actions, objective="steps", gamma=0.99999, tol=1e-8, max_iterations=500_000)

    assert result.converged
    expected_steps = 1 / p
    assert abs(-result.value[S] - expected_steps) < 0.05
    assert result.policy[S] == "try"


def test_cost_objective_prefers_lower_expected_cost_action():
    """Two actions: 'cheap' costs 1/attempt at 20% success, 'expensive' costs 5/
    attempt at 90% success. Expected cost to succeed is cost/p: cheap = 5.0,
    expensive = 5.555..., so the cost-minimizing policy must pick 'cheap'
    despite its lower per-attempt success rate."""
    S, G = _state(False), _state(True)
    mdp = MDP(
        start=S,
        states={S, G},
        goal_states={G},
        transitions={
            (S, "cheap"): {G: 0.2, S: 0.8},
            (S, "expensive"): {G: 0.9, S: 0.1},
        },
    )
    actions = {"cheap": _FakeAction("cheap", cost=1.0), "expensive": _FakeAction("expensive", cost=5.0)}

    result = value_iteration(mdp, actions, objective="cost", gamma=0.99999, tol=1e-8, max_iterations=500_000)

    assert result.converged
    assert result.policy[S] == "cheap"
    assert abs(-result.value[S] - 5.0) < 0.05


def test_dead_end_state_gets_a_large_negative_value_not_zero():
    """A non-goal state with no applicable actions at all must not be treated
    as free (0.0, same as a goal) -- that would corrupt any neighboring
    state's decision about whether to step into it."""
    S, DEAD = _state(False), _state(False)  # distinct objects standing in for two different abstract states
    DEAD2 = AbstractState(rarity=Rarity.RARE, prefix_count=1, suffix_count=0, status=(0,))
    G = _state(True)
    mdp = MDP(
        start=S,
        states={S, DEAD2, G},
        goal_states={G},
        transitions={(S, "risky"): {G: 0.5, DEAD2: 0.5}},  # DEAD2 has no outgoing transitions at all
    )
    actions = {"risky": _FakeAction("risky", cost=1.0)}

    result = value_iteration(mdp, actions, objective="steps")

    assert DEAD2 in result.dead_ends
    assert result.value[DEAD2] < -1000
    assert DEAD2 not in result.policy
