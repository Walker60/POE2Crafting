"""q_value/q_values_at -- the on-demand per-action Q lookup behind the web
API's alternative-actions view. Verified against the exact numbers
value_iteration itself converges to, not just "doesn't crash"."""
from poe2craft.domain.items import Rarity
from poe2craft.solver.featurize import AbstractState
from poe2craft.solver.model_learning import MDP
from poe2craft.solver.value_iteration import q_value, q_values_at, value_iteration


class _FakeAction:
    def __init__(self, name: str, cost: float):
        self.name = name
        self._cost = cost

    def cost(self) -> float:
        return self._cost


def _state(satisfied: bool) -> AbstractState:
    return AbstractState(rarity=Rarity.RARE, prefix_count=0, suffix_count=0, status=(2 if satisfied else 0,))


def test_q_value_of_the_policy_action_equals_its_own_converged_value():
    S, G = _state(False), _state(True)
    mdp = MDP(start=S, states={S, G}, goal_states={G}, transitions={(S, "try"): {G: 0.25, S: 0.75}})
    actions = {"try": _FakeAction("try", cost=1.0)}
    result = value_iteration(mdp, actions, objective="steps", gamma=0.99999, tol=1e-8, max_iterations=500_000)

    q = q_value(mdp, actions, result.value, result.objective, S, "try", result.gamma)
    assert abs(q - result.value[S]) < 1e-6  # the only action, so its Q must equal V


def test_q_values_at_ranks_the_worse_action_below_the_chosen_one():
    S, G = _state(False), _state(True)
    mdp = MDP(
        start=S,
        states={S, G},
        goal_states={G},
        transitions={(S, "cheap"): {G: 0.2, S: 0.8}, (S, "expensive"): {G: 0.9, S: 0.1}},
    )
    actions = {"cheap": _FakeAction("cheap", cost=1.0), "expensive": _FakeAction("expensive", cost=5.0)}
    result = value_iteration(mdp, actions, objective="cost", gamma=0.99999, tol=1e-8, max_iterations=500_000)
    assert result.policy[S] == "cheap"

    qs = q_values_at(mdp, actions, result, S)
    assert set(qs) == {"cheap", "expensive"}
    assert qs["cheap"] > qs["expensive"]  # higher Q (less negative cost) is better
    assert abs(qs["cheap"] - result.value[S]) < 1e-6  # matches the policy's own chosen value


def test_q_values_at_omits_actions_with_no_transition_from_the_state():
    S, G = _state(False), _state(True)
    mdp = MDP(start=S, states={S, G}, goal_states={G}, transitions={(S, "try"): {G: 1.0}})
    # "unrelated" is a real registered action, just never applicable/sampled from S.
    actions = {"try": _FakeAction("try", cost=1.0), "unrelated": _FakeAction("unrelated", cost=1.0)}
    result = value_iteration(mdp, actions, objective="steps")

    qs = q_values_at(mdp, actions, result, S)
    assert set(qs) == {"try"}


def test_q_value_returns_none_for_an_inapplicable_action():
    S, G = _state(False), _state(True)
    mdp = MDP(start=S, states={S, G}, goal_states={G}, transitions={(S, "try"): {G: 1.0}})
    actions = {"try": _FakeAction("try", cost=1.0), "unrelated": _FakeAction("unrelated", cost=1.0)}
    result = value_iteration(mdp, actions, objective="steps")

    assert q_value(mdp, actions, result.value, result.objective, S, "unrelated", result.gamma) is None
