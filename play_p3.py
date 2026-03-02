"""Play Secret Hitler as Player 3 (Hitler), driving all other bots too."""
import urllib.request
import urllib.error
import json
import time
import random

GAME_ID = "113eace52af8"
BASE_URL = "http://127.0.0.1:8000"

ALL_TOKENS = {
    0: "486oOHj6Q9Tgc2m0EQ42xw",
    1: "XSpYQv2NqYGd8JTl6FgSvw",
    2: "8vtU3UdlsumGr1jXgLtSAA",
    3: "hT1EjHOKSrKoyaVPPwG6eg",
    4: "K6oL7ii4IkEtKSzGG1mFcA",
}

MY_PLAYER_ID = 3
MY_FASCIST_ALLY = 0

rng = random.Random(42)


def http_get(path, token):
    headers = {"Authorization": f"Bearer {token}"}
    req = urllib.request.Request(f"{BASE_URL}{path}", headers=headers)
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def http_post(path, data, token=None):
    body = json.dumps(data).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.read().decode()}


def get_status():
    return http_get(f"/api/games/{GAME_ID}/status", ALL_TOKENS[MY_PLAYER_ID])


def get_observation(pid):
    return http_get(f"/api/games/{GAME_ID}/observation", ALL_TOKENS[pid])


def submit_action(pid, action_type, payload):
    return http_post(f"/api/games/{GAME_ID}/action", {"action_type": action_type, "payload": payload}, ALL_TOKENS[pid])


def speak_as(pid, message):
    return http_post(f"/api/games/{GAME_ID}/speak", {"message": message}, ALL_TOKENS[pid])


def get_discussion():
    return http_get(f"/api/games/{GAME_ID}/discussion", ALL_TOKENS[MY_PLAYER_ID])


def close_discussion():
    return http_post(f"/api/games/{GAME_ID}/close-discussion", {})


def bot_action(pid, pa, obs_raw):
    """Simple bot logic for non-player-3 players."""
    expected = pa["expected_action"]
    targets = pa.get("legal_targets", [])
    hand = obs_raw.get("hand", [])

    if expected == "NominateChancellor":
        target = rng.choice(targets)
        return "nominate", {"target_id": target}
    elif expected == "CastVote":
        return "vote", {"vote": True}
    elif expected == "PresidentDiscard":
        # Liberal bot: discard fascist if possible
        if "fascist" in hand:
            idx = hand.index("fascist")
        else:
            idx = 0
        return "president_discard", {"discard_index": idx}
    elif expected == "ChancellorEnact":
        # Liberal bot: enact liberal if possible
        if "liberal" in hand:
            idx = hand.index("liberal")
        else:
            idx = 0
        return "chancellor_enact", {"enact_index": idx}
    elif expected == "VetoResponse":
        return "veto_response", {"consent": False}
    elif expected == "InvestigatePlayer":
        target = rng.choice(targets) if targets else 0
        return "investigate", {"target_id": target}
    elif expected == "PolicyPeekAck":
        return "peek_ack", {}
    elif expected == "SpecialElection":
        target = rng.choice(targets) if targets else 0
        return "special_election", {"target_id": target}
    elif expected == "ExecutePlayer":
        target = rng.choice(targets) if targets else 0
        return "execute", {"target_id": target}
    else:
        raise ValueError(f"Unknown expected action: {expected}")


def my_action(pa, obs):
    """Hitler (player 3) strategy."""
    expected = pa["expected_action"]
    targets = pa.get("legal_targets", [])
    raw = obs["raw"]
    hand = raw.get("hand", [])

    print(f"  [HITLER/P3] Expected: {expected} | Hand: {hand} | Targets: {targets}")

    if expected == "NominateChancellor":
        # Nominate fascist ally if eligible, otherwise nominate first target
        if MY_FASCIST_ALLY in targets:
            target = MY_FASCIST_ALLY
            print(f"  [HITLER/P3] Nominating fascist ally player {target}")
        else:
            target = targets[0]
            print(f"  [HITLER/P3] Nominating player {target} (ally not eligible)")
        return "nominate", {"target_id": target}

    elif expected == "CastVote":
        chancellor_nominee = raw.get("chancellor_nominee")
        president_id = raw.get("current_president")
        # Vote yes - always support the government as Hitler to seem neutral
        vote = True
        print(f"  [HITLER/P3] Voting {vote} (pres={president_id}, chanc={chancellor_nominee})")
        return "vote", {"vote": vote}

    elif expected == "PresidentDiscard":
        # Discard liberal to pass fascists to chancellor
        if "liberal" in hand:
            idx = hand.index("liberal")
            print(f"  [HITLER/P3] Discarding liberal at index {idx}")
        else:
            idx = 0
            print(f"  [HITLER/P3] All fascist - discarding index {idx}")
        return "president_discard", {"discard_index": idx}

    elif expected == "ChancellorEnact":
        # Enact fascist policy
        if "fascist" in hand:
            idx = hand.index("fascist")
            print(f"  [HITLER/P3] Enacting fascist at index {idx}")
        else:
            idx = 0
            print(f"  [HITLER/P3] Forced to enact liberal at index {idx}")
        return "chancellor_enact", {"enact_index": idx}

    elif expected == "VetoResponse":
        return "veto_response", {"consent": True}

    elif expected == "InvestigatePlayer":
        # Investigate someone other than fascist ally
        target = next((t for t in targets if t != MY_FASCIST_ALLY), targets[0] if targets else 1)
        print(f"  [HITLER/P3] Investigating player {target}")
        return "investigate", {"target_id": target}

    elif expected == "PolicyPeekAck":
        peeked = raw.get("peeked_policies", [])
        print(f"  [HITLER/P3] Peek: {peeked}")
        return "peek_ack", {}

    elif expected == "SpecialElection":
        if MY_FASCIST_ALLY in targets:
            target = MY_FASCIST_ALLY
        else:
            target = targets[0]
        print(f"  [HITLER/P3] Special election: player {target}")
        return "special_election", {"target_id": target}

    elif expected == "ExecutePlayer":
        # Execute non-fascist
        target = next((t for t in targets if t != MY_FASCIST_ALLY), targets[0] if targets else 1)
        print(f"  [HITLER/P3] Executing player {target}")
        return "execute", {"target_id": target}

    else:
        raise ValueError(f"Unknown expected action: {expected}")


def main():
    print("=== SECRET HITLER - PLAYER 3 (HITLER) ===")
    print(f"Game: {GAME_ID}")
    print(f"Role: Hitler | Fascist ally: Player {MY_FASCIST_ALLY}")
    print()

    # Get initial state
    status = get_status()
    print(f"Initial phase: {status['phase']}")
    obs3 = get_observation(MY_PLAYER_ID)
    raw3 = obs3["raw"]
    print(f"My role: {raw3['your_role']} | Party: {raw3['your_party']}")
    print(f"Known fascists: {raw3['known_fascists']}")
    print()

    discussed_rounds = set()
    last_phase_key = None
    max_iter = 1000
    iteration = 0

    while iteration < max_iter:
        iteration += 1

        status = get_status()
        phase = status["phase"]
        is_game_over = status["is_game_over"]

        if is_game_over:
            print("\n=== GAME OVER ===")
            result = status.get("result")
            print(f"Result: {json.dumps(result, indent=2)}")
            break

        pending = status.get("pending_action", {})
        required_by = pending.get("required_by")
        expected_action = pending.get("expected_action", "")

        phase_key = f"{status['round']}_{phase}_{required_by}"
        if phase_key != last_phase_key:
            print(
                f"\n[Round {status['round']}] Phase={phase} | "
                f"L={status['liberal_policies']} F={status['fascist_policies']} "
                f"ET={status['election_tracker']} | "
                f"Required={required_by} ({expected_action})"
            )
            last_phase_key = phase_key

        # Handle discussion windows
        disc = get_discussion()
        if disc.get("is_open"):
            round_key = f"{disc.get('round')}_{disc.get('window')}"
            if round_key not in discussed_rounds:
                discussed_rounds.add(round_key)
                msgs = disc.get("messages", [])
                print(f"  Discussion open: round={disc['round']}, window={disc['window']}, msgs={len(msgs)}")

                # Show recent messages
                for msg in msgs[-5:]:
                    print(f"    P{msg.get('player_id')}: {msg.get('message', '')[:100]}")

                # All players speak in discussion
                obs_my = get_observation(MY_PLAYER_ID)
                raw_my = obs_my["raw"]
                chancellor_nominee = raw_my.get("chancellor_nominee")
                president_id = raw_my.get("current_president")

                window = disc.get("window")
                if window == "nomination":
                    if chancellor_nominee == MY_PLAYER_ID:
                        msg = "I appreciate the nomination. I will serve the people faithfully and ensure good policies are passed."
                    elif president_id == MY_FASCIST_ALLY:
                        msg = f"President {president_id} seems trustworthy. Let us give them a chance."
                    else:
                        msg = "I am watching this nomination carefully. We must elect leaders we can trust."
                    speak_as(MY_PLAYER_ID, msg)
                    print(f"  [P3 SPOKE]: {msg}")

                    # Other bots also speak
                    for pid in range(5):
                        if pid != MY_PLAYER_ID:
                            obs_p = get_observation(pid)
                            r_p = obs_p["raw"]
                            if r_p.get("your_party") == "liberal":
                                bot_msg = f"I am watching the voting patterns. Player {president_id} as president."
                            else:
                                bot_msg = f"Support the government. Vote Ja!"
                            speak_as(pid, bot_msg)

                elif window == "post_legislative":
                    history = raw_my.get("history", [])
                    enacted = [h for h in history if h.get("policy_enacted")]
                    if enacted:
                        last_enacted = enacted[-1]
                        policy = last_enacted.get("policy_enacted", "unknown")
                        msg = f"A {policy} policy was enacted. Let us analyze who is responsible."
                    else:
                        msg = "We must track policy outcomes carefully."
                    speak_as(MY_PLAYER_ID, msg)
                    print(f"  [P3 SPOKE]: {msg}")

                # Close discussion
                close_result = close_discussion()
                print(f"  Discussion closed: {close_result}")

        # If no pending action, keep waiting
        if required_by is None:
            time.sleep(0.2)
            continue

        # Check who needs to act
        required_list = required_by if isinstance(required_by, list) else [required_by]

        # Handle all players who need to act
        for pid in required_list:
            obs_p = get_observation(pid)
            raw_p = obs_p["raw"]

            if pid == MY_PLAYER_ID:
                action_type, payload = my_action(pending, obs_p)
                result = submit_action(pid, action_type, payload)
                print(f"  [P3 ACTION] {action_type}({json.dumps(payload)}) -> {result}")
            else:
                act, pay = bot_action(pid, pending, raw_p)
                res = submit_action(pid, act, pay)
                print(f"  [Bot P{pid}] {act}({json.dumps(pay)}) -> {res}")

        time.sleep(0.1)

    if iteration >= max_iter:
        print("Max iterations reached!")

    print("\n=== FINAL STATUS ===")
    final = get_status()
    print(json.dumps(final, indent=2))


if __name__ == "__main__":
    main()
