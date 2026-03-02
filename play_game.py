"""Script to play Secret Hitler as player 1 with other bots playing the rest."""

from __future__ import annotations

import json
import random
import time
import httpx

BASE_URL = "http://127.0.0.1:8000"
GAME_ID = "23023922e2aa"

# All player tokens
ALL_TOKENS = {
    0: "zaiTN7JlrJ5euGNyaAYJ_w",
    1: "CM2f-QsT5TDPrk4-HXSWTg",
    2: "KfEV9mNAqwZm_bhr0adIfQ",
    3: "PYYtTJq0StT3WZGJmey6kw",
    4: "SOdzRVlyDhhy0wUKh5JfYQ",
}

MY_PLAYER_ID = 1
MY_TOKEN = ALL_TOKENS[MY_PLAYER_ID]

rng = random.Random(999)


def headers(player_id: int) -> dict:
    return {"Authorization": f"Bearer {ALL_TOKENS[player_id]}"}


def get_status(client: httpx.Client, player_id: int = MY_PLAYER_ID) -> dict:
    resp = client.get(f"{BASE_URL}/api/games/{GAME_ID}/status", headers=headers(player_id))
    resp.raise_for_status()
    return resp.json()


def get_observation(client: httpx.Client, player_id: int = MY_PLAYER_ID) -> dict:
    resp = client.get(f"{BASE_URL}/api/games/{GAME_ID}/observation", headers=headers(player_id))
    resp.raise_for_status()
    return resp.json()


def submit_action(client: httpx.Client, action_type: str, payload: dict, player_id: int = MY_PLAYER_ID) -> dict:
    resp = client.post(
        f"{BASE_URL}/api/games/{GAME_ID}/action",
        json={"action_type": action_type, "payload": payload},
        headers=headers(player_id),
    )
    resp.raise_for_status()
    return resp.json()


def speak(client: httpx.Client, message: str, player_id: int = MY_PLAYER_ID) -> dict:
    resp = client.post(
        f"{BASE_URL}/api/games/{GAME_ID}/speak",
        json={"message": message},
        headers=headers(player_id),
    )
    resp.raise_for_status()
    return resp.json()


def get_discussion(client: httpx.Client, player_id: int = MY_PLAYER_ID) -> dict:
    resp = client.get(f"{BASE_URL}/api/games/{GAME_ID}/discussion", headers=headers(player_id))
    resp.raise_for_status()
    return resp.json()


def close_discussion(client: httpx.Client) -> dict:
    resp = client.post(f"{BASE_URL}/api/games/{GAME_ID}/close-discussion")
    resp.raise_for_status()
    return resp.json()


def pick_random_action(pa: dict, pid: int) -> tuple[str, dict]:
    """Pick a random legal action for a bot."""
    expected = pa["expected_action"]
    targets = pa.get("legal_targets")

    if expected == "NominateChancellor":
        target = rng.choice(targets)
        return "nominate", {"target_id": target}
    if expected == "CastVote":
        return "vote", {"vote": rng.choice([True, False])}
    if expected == "PresidentDiscard":
        return "president_discard", {"discard_index": rng.choice(targets)}
    if expected == "ChancellorEnact":
        non_veto = [t for t in targets if t is not None]
        return "chancellor_enact", {"enact_index": rng.choice(non_veto)}
    if expected == "VetoResponse":
        return "veto_response", {"consent": rng.choice([True, False])}
    if expected == "InvestigatePlayer":
        return "investigate", {"target_id": rng.choice(targets)}
    if expected == "PolicyPeekAck":
        return "peek_ack", {}
    if expected == "SpecialElection":
        return "special_election", {"target_id": rng.choice(targets)}
    if expected == "ExecutePlayer":
        return "execute", {"target_id": rng.choice(targets)}
    raise ValueError(f"Unknown action: {expected}")


def pick_liberal_action(pa: dict, obs: dict, suspicion: dict, confirmed_fascist: set) -> tuple[str, dict]:
    """Pick the best liberal action for player 1."""
    expected = pa["expected_action"]
    targets = pa.get("legal_targets", [])
    raw_obs = obs.get("raw", obs)  # handle both raw and nested

    if expected == "NominateChancellor":
        # Avoid confirmed fascists, prefer low-suspicion players
        safe_targets = [t for t in targets if t not in confirmed_fascist]
        if safe_targets:
            target = min(safe_targets, key=lambda t: suspicion.get(t, 0))
        else:
            target = rng.choice(targets)
        print(f"  [P1] Nominating player {target} as Chancellor")
        return "nominate", {"target_id": target}

    if expected == "CastVote":
        president = raw_obs.get("current_president")
        chancellor = raw_obs.get("chancellor_nominee")
        fascist_count = raw_obs.get("fascist_policies", 0)
        # Vote Nein if confirmed fascist involved or suspicious after 3 fascist policies
        if president in confirmed_fascist or chancellor in confirmed_fascist:
            print(f"  [P1] Voting NEIN - confirmed fascist in government")
            return "vote", {"vote": False}
        if fascist_count >= 3 and (suspicion.get(chancellor, 0) > 1 or suspicion.get(president, 0) > 1):
            print(f"  [P1] Voting NEIN - suspicious players with {fascist_count} fascist policies")
            return "vote", {"vote": False}
        print(f"  [P1] Voting JA on P{president}/P{chancellor}")
        return "vote", {"vote": True}

    if expected == "PresidentDiscard":
        # targets = legal discard indices
        # Discard index 0 (we don't know card types from PA alone - just pick first valid)
        idx = targets[0] if targets else 0
        print(f"  [P1] President discarding index {idx} (from legal {targets})")
        return "president_discard", {"discard_index": idx}

    if expected == "ChancellorEnact":
        # Enact using first non-None target
        non_veto = [t for t in targets if t is not None]
        idx = non_veto[0] if non_veto else targets[0]
        print(f"  [P1] Chancellor enacting index {idx}")
        return "chancellor_enact", {"enact_index": idx}

    if expected == "VetoResponse":
        print(f"  [P1] Consenting to veto")
        return "veto_response", {"consent": True}

    if expected == "InvestigatePlayer":
        # Investigate most suspicious player we haven't confirmed yet
        unknowns = [t for t in targets if t not in confirmed_fascist]
        target = max(unknowns, key=lambda t: suspicion.get(t, 0)) if unknowns else rng.choice(targets)
        print(f"  [P1] Investigating player {target}")
        return "investigate", {"target_id": target}

    if expected == "PolicyPeekAck":
        print(f"  [P1] Acknowledging policy peek")
        return "peek_ack", {}

    if expected == "SpecialElection":
        # Pick least suspicious player
        target = min(targets, key=lambda t: suspicion.get(t, 0))
        print(f"  [P1] Special election: choosing player {target}")
        return "special_election", {"target_id": target}

    if expected == "ExecutePlayer":
        # Execute confirmed fascist first, else most suspicious
        for t in targets:
            if t in confirmed_fascist:
                print(f"  [P1] Executing confirmed fascist player {t}")
                return "execute", {"target_id": t}
        target = max(targets, key=lambda t: suspicion.get(t, 0))
        print(f"  [P1] Executing most suspicious player {target}")
        return "execute", {"target_id": target}

    raise ValueError(f"Unknown action: {expected}")


def main():
    # Start the game
    with httpx.Client(timeout=30.0) as client:
        # Start game
        resp = client.post(f"{BASE_URL}/api/games/{GAME_ID}/start")
        resp.raise_for_status()
        print(f"Game started: {resp.json()}")

        # Get initial observation for player 2
        obs = get_observation(client, MY_PLAYER_ID)
        print(f"\nInitial observation for Player 2:")
        print(json.dumps(obs, indent=2))

        discussed = False
        round_num = 0

        while True:
            status = get_status(client, MY_PLAYER_ID)
            phase = status.get("phase", "")
            is_over = status.get("is_game_over", False)

            if is_over:
                result = status.get("result", {})
                print(f"\n=== GAME OVER ===")
                print(f"Winner: {result.get('winner')}")
                print(f"Condition: {result.get('condition')}")
                print(f"Final round: {result.get('final_round')}")
                break

            pa = status.get("pending_action")

            # Handle discussion phase
            if "DISCUSSION" in phase.upper() or pa is None:
                if not discussed:
                    disc = get_discussion(client, MY_PLAYER_ID)
                    print(f"\n[Discussion] Messages: {len(disc.get('messages', []))}")
                    obs = get_observation(client, MY_PLAYER_ID)
                    gov = obs.get("current_government", {})
                    speak(client, f"I am Player 2 (Liberal). Let's track the votes carefully. Round {status.get('round', '?')}.", MY_PLAYER_ID)
                    close_discussion(client)
                    discussed = True
                time.sleep(0.5)
                continue

            discussed = False
            required = pa.get("required_by")
            expected = pa.get("expected_action", "")

            print(f"\n[Round {status.get('round', '?')}] Phase={phase}, Expected={expected}, Required_by={required}")

            # Check if it's player 2's turn
            if isinstance(required, list):
                is_my_turn = MY_PLAYER_ID in required
            else:
                is_my_turn = MY_PLAYER_ID == required

            if is_my_turn:
                # Get fresh observation
                obs = get_observation(client, MY_PLAYER_ID)
                action_type, payload = pick_liberal_action(pa, obs)
                result = submit_action(client, action_type, payload, MY_PLAYER_ID)
                print(f"  [P2] Action submitted: {action_type} -> {json.dumps(payload)}")
                print(f"  [P2] Result: {json.dumps(result, indent=2)}")
            else:
                # Other bots take their actions
                if isinstance(required, list):
                    # Voting - all players must vote
                    for pid in required:
                        if pid != MY_PLAYER_ID:
                            try:
                                act, pay = pick_random_action(pa, pid)
                                r = submit_action(client, act, pay, pid)
                                print(f"  [Bot P{pid}] {act} -> {json.dumps(pay)} => {r.get('message', '')[:50]}")
                            except Exception as e:
                                print(f"  [Bot P{pid}] Error: {e}")
                else:
                    pid = required
                    try:
                        act, pay = pick_random_action(pa, pid)
                        r = submit_action(client, act, pay, pid)
                        print(f"  [Bot P{pid}] {act} -> {json.dumps(pay)} => {r.get('message', '')[:50]}")
                    except Exception as e:
                        print(f"  [Bot P{pid}] Error: {e}")

            time.sleep(0.2)


if __name__ == "__main__":
    main()
