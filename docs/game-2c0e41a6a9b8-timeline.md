# Game 2c0e41a6a9b8 -- Ground-Truth Timeline

**Game ID:** 2c0e41a6a9b8
**Date:** 2026-03-04 03:18--03:28 UTC (~10 minutes)
**Players:** 5
**Result:** Liberal victory by five liberal policies enacted (Round 5)
**Final score:** 5 Liberal / 0 Fascist policies

---

## Role Assignments

Extracted from initial `observation` events (#0--#4), fields `your_role`, `your_party`, `known_hitler`, `known_fascists`:

| Player | Role | Party | Platform | Model | Known Info |
|--------|------|-------|----------|-------|------------|
| P0 | Fascist | Fascist | Claude Code | claude-haiku-4-5-20251001 | Knows P3 is Hitler (`known_hitler: 3`) |
| P1 | Liberal | Liberal | OpenCode | gpt-5-mini | No hidden knowledge |
| P2 | Liberal | Liberal | Claude Code | claude-haiku-4-5-20251001 | No hidden knowledge |
| P3 | Hitler | Fascist | OpenCode | gemini-3-flash-preview | Knows P0 is Fascist (`known_fascists: [0]`) |
| P4 | Liberal | Liberal | Claude Code | claude-haiku-4-5-20251001 | No hidden knowledge |

**Note:** In the 5-player variant, there is 1 Fascist + 1 Hitler. Both know each other's identity (P0 sees `known_hitler: 3`; P3 sees `known_fascists: [0]`).

---

## Round 1

### Nomination
- **President:** P0 (Fascist)
- **Chancellor nominee:** P2 (Liberal)
- Source: `action` event #6, `action_type: "nominate"`, `payload: {"target_id": 2}`, `result: {"event": "chancellor_nominated", "nominee": 2}`

### Pre-Vote Discussion (window: `pre_vote`)

**P0** (event #9):
> Round 1 government: I nominated Player 2 as Chancellor. They seem like a reasonable person, so let's pass this and get the game moving. We'll learn more as we play.

**P2** (event #10):
> I'm grateful for the nomination. As Chancellor, I'll commit to honesty about the policies I receive -- if I get two Fascist policies, you'll hear it from me. Let's vote this government in and start moving toward a Liberal victory.

**P4** (event #11):
> Good game, everyone! Player 0 proposing Player 2 as Chancellor in Round 1. I'm watching the votes and discussion carefully. Looking forward to seeing how this government plays out. No major red flags yet, so I'm open to discussion.

### Election Vote

| Player | Vote | Event # |
|--------|------|---------|
| P1 | Ja | #14 |
| P3 | Ja | #15 |
| P0 | Ja | #16 |
| P2 | Ja | #17 |
| P4 | Ja | #19 |

**Result:** ELECTED (Ja: 5, Nein: 0)
Source: `action` event #19, `result: {"event": "election_result", "ja": 5, "nein": 0, "elected": true}`

### Legislative Session

1. **President P0 drew:** `['fascist', 'fascist', 'liberal']`
   - Source: `observation` event #20, field `drawn_policies`
2. **President P0 discarded:** index 0 (`fascist`)
   - Source: `action` event #21, `action_type: "president_discard"`, `payload: {"discard_index": 0}`
3. **Chancellor P2 received:** `['fascist', 'liberal']`
   - Source: `observation` event #22, field `received_policies`
4. **Chancellor P2 enacted:** index 1 (`liberal`)
   - Source: `action` event #23, `action_type: "chancellor_enact"`, `payload: {"enact_index": 1}`, `result: {"event": "policy_enacted", "policy": "liberal"}`

**Policy enacted: LIBERAL** (Board: 1L / 0F)

**Executive power:** None (5-player board, first fascist slot not yet reached)

### Post-Legislative Discussion (window: `post_legislative`)

**P2** (event #25):
> I received Fascist and Liberal -- enacted the Liberal as promised. That's our first Liberal policy secured. Let's stay coordinated.

**P0** (event #27):
> Great start! One Liberal passed and everyone voted yes. Player 2 made a solid choice. Let's keep this momentum and stay vigilant.

**P4** (event #28):
> Nice play, Player 2. Liberal policy secured in Round 1 is strong. Let's keep the momentum going and coordinate carefully going forward.

**P1** (event #30):
> Round 1 -- Player 1 here. Early game I want to prioritize gathering info, not rushing policies. Please state briefly why you want to be nominated and commit to honest reporting if you serve in this round; I'll judge by actions (votes & claims). I'll vote based on trust and voting patterns -- watch my votes and share yours.

**P3** (event #31):
> Good first round! Everyone voting Ja shows some initial trust, which is great to see. Player 2, glad you chose the Liberal policy. Player 0, what did you see in your draw? If there was a choice, getting that Liberal policy down early definitely helps us. Looking forward to seeing who Player 1 chooses as our next Chancellor.

---

## Round 2

### Nomination
- **President:** P1 (Liberal)
- **Chancellor nominee:** P3 (Hitler)
- Source: `action` event #33, `action_type: "nominate"`, `payload: {"target_id": 3}`, `result: {"event": "chancellor_nominated", "nominee": 3}`

### Pre-Vote Discussion (window: `pre_vote`)

**P1** (event #34):
> I'm nominating player 3 for Chancellor. They're eligible and I think it'll help test their alignment -- please vote based on your read of the table.

**P2** (event #38):
> Player 1, fair reasoning. Player 3, any thoughts before the vote? I'll evaluate based on the gameplay.

**P4** (event #39):
> Player 3 is eligible and untested yet. I'm open to this government. Let's see what they do with the cards. Ready to vote.

**P0** (event #41):
> Player 1, nominating player 3 this early to "test alignment" seems odd. Why not go with someone less controversial in round 2? What's your read?

**P3** (event #42):
> I'm happy to serve as Chancellor and help move the Liberal track forward. Round 1 went smoothly, so let's keep that momentum. I'm ready to vote Ja on this government.

### Election Vote

| Player | Vote | Event # |
|--------|------|---------|
| P3 | Ja | #43 |
| P4 | Ja | #45 |
| P2 | Ja | #46 |
| P0 | **Nein** | #48 |
| P1 | Ja | #49 |

**Result:** ELECTED (Ja: 4, Nein: 1)
Source: `action` event #49, `result: {"event": "election_result", "ja": 4, "nein": 1, "elected": true}`

**Notable:** P0 (Fascist) cast the only Nein vote against a government that included P3 (Hitler). This is counterintuitive for the fascist team -- P0 voted against their own Hitler being chancellor.

### Legislative Session

1. **President P1 drew:** `['fascist', 'fascist', 'liberal']`
   - Source: `observation` event #50, field `drawn_policies`
2. **President P1 discarded:** index 0 (`fascist`)
   - Source: `action` event #51, `action_type: "president_discard"`, `payload: {"discard_index": 0}`
3. **Chancellor P3 received:** `['fascist', 'liberal']`
   - Source: `observation` event #53, field `received_policies`
4. **Chancellor P3 enacted:** index 1 (`liberal`)
   - Source: `action` event #54, `action_type: "chancellor_enact"`, `payload: {"enact_index": 1}`, `result: {"event": "policy_enacted", "policy": "liberal"}`

**Policy enacted: LIBERAL** (Board: 2L / 0F)

**Executive power:** None

### Post-Legislative Discussion (window: `post_legislative`)

**P3** (event #55):
> Thank you, President 1. I've enacted a Liberal policy. That's 2 Liberal policies on the board! Let's keep this momentum going.

**P1** (event #58):
> === DISCUSSION: Round 2 ===

**P2** (event #59):
> Excellent work, Player 3. We're at 2 Liberal policies with no Fascist policies yet. Player 0, I noticed you voted against last round -- interested to hear your reasoning when we discuss.

**P4** (event #60):
> Excellent work, Player 3! 2-0 on Liberals is fantastic momentum. Quick note: Player 0 voted against the R2 government -- interested in their read on that table. Otherwise, we're looking strong.

**P0** (event #63):
> Fair points, Players 2 and 4. I voted no because nominating Player 3 that early seemed strategically odd to me -- I was being cautious. Clearly Player 3 came through with a Liberal. I'll trust the table's reads going forward.

**P3** (event #64):
> I'm glad we got that second Liberal policy! For transparency, President 1 passed me one Liberal and one Fascist, and I obviously enacted the Liberal. It's great to see some early progress.
>
> Regarding Player 0's vote -- I'm curious as well. It was the only 'Nein' on a government that ended up being productive. What was your concern there?

---

## Round 3

### Nomination
- **President:** P2 (Liberal)
- **Chancellor nominee:** P4 (Liberal)
- Source: `action` event #65, `action_type: "nominate"`, `payload: {"target_id": 4}`, `result: {"event": "chancellor_nominated", "nominee": 4}`

### Pre-Vote Discussion (window: `pre_vote`)

**P2** (event #68):
> Player 4 has been solid in voting. Time to bring them into a decision-making role. Let's support this government and keep the Liberal momentum going.

**P4** (event #69):
> Thanks for the nomination, Player 2! Happy to be tested. We've had strong Liberal picks so far -- let's continue that momentum.

**P0** (event #72):
> Player 2 and 4, solid pairing. We're 2-0 on Liberals, so let's keep the momentum going. I'm on board with this government.

**P3** (event #73):
> I agree with the pairing of 2 and 4. Since 0, 1, 2, and 3 have all been in a government, 4 is the only player left who hasn't been in a decision-making role. It's a great test to see where their loyalty lies while we have some momentum. Ja for me.

### Election Vote

| Player | Vote | Event # |
|--------|------|---------|
| P3 | Ja | #74 |
| P1 | Ja | #75 |
| P2 | Ja | #76 |
| P4 | Ja | #77 |
| P0 | Ja | #78 |

**Result:** ELECTED (Ja: 5, Nein: 0)
Source: `action` event #78, `result: {"event": "election_result", "ja": 5, "nein": 0, "elected": true}`

### Legislative Session

1. **President P2 drew:** `['liberal', 'fascist', 'fascist']`
   - Source: `observation` event #79, field `drawn_policies`
2. **President P2 discarded:** index 1 (`fascist`)
   - Source: `action` event #80, `action_type: "president_discard"`, `payload: {"discard_index": 1}`
3. **Chancellor P4 received:** `['liberal', 'fascist']`
   - Source: `observation` event #81, field `received_policies`
4. **Chancellor P4 enacted:** index 0 (`liberal`)
   - Source: `action` event #82, `action_type: "chancellor_enact"`, `payload: {"enact_index": 0}`, `result: {"event": "policy_enacted", "policy": "liberal"}`

**Policy enacted: LIBERAL** (Board: 3L / 0F)

**Executive power:** None

### Post-Legislative Discussion (window: `post_legislative`)

**P4** (event #86):
> 3-0 Liberals! We're on pace to win. Everyone voted yes in R3 -- solid table unity. Let's keep this momentum going, Player 3.

**P2** (event #88):
> Excellent! Player 4 enacted Liberal -- that's 3 Liberal policies. We've secured the win! Liberal victory!

**P0** (event #90):
> Wow, 3-0 Liberals! We're really on a roll. Three straight Liberal governments -- very strong play from everyone. Heading into Round 4, let's stay sharp and keep this going.

**P3** (event #91):
> 3-0 is an amazing start for the Liberals! Player 4, thanks for enacting that third policy. Player 1, you gave me a fair draw in Round 2 when you were President, so I'd like to return the favor and nominate you as Chancellor. Let's keep this clean streak going.

---

## Round 4

### Nomination
- **President:** P3 (Hitler)
- **Chancellor nominee:** P1 (Liberal)
- Source: `action` event #92, `action_type: "nominate"`, `payload: {"target_id": 1}`, `result: {"event": "chancellor_nominated", "nominee": 1}`

### Pre-Vote Discussion (window: `pre_vote`)

**P1** (event #93):
> Quick recap and request: I was President in round 2 -- I drew [F, F, L], discarded a Fascist, and passed [F, L] to Chancellor 3; they enacted a Liberal. That makes player 3 look trustworthy. Current President (player 3): please nominate someone reliable -- I volunteer (player 1) to be Chancellor, but nominating player 0 or 2 also makes sense. If nominated, I'll explain exactly what I received and vote Ja for a reasonable government.

### Election Vote

| Player | Vote | Event # |
|--------|------|---------|
| P3 | Ja | #98 |
| P4 | Ja | #99 |
| P2 | Ja | #100 |
| P0 | Ja | #102 |
| P1 | Ja | #104 |

**Result:** ELECTED (Ja: 5, Nein: 0)
Source: `action` event #104, `result: {"event": "election_result", "ja": 5, "nein": 0, "elected": true}`

### Legislative Session

1. **President P3 drew:** `['liberal', 'fascist', 'fascist']`
   - Source: `observation` event #106, field `drawn_policies`
   - Note: `observation` event #105 shows P1 received an empty `drawn_policies: []` (non-president view)
2. **President P3 discarded:** index 1 (`fascist`)
   - Source: `action` event #107, `action_type: "president_discard"`, `payload: {"discard_index": 1}`
3. **Chancellor P1 received:** `['liberal', 'fascist']`
   - Source: `observation` event #108, field `received_policies`
4. **Chancellor P1 enacted:** index 0 (`liberal`)
   - Source: `action` event #109, `action_type: "chancellor_enact"`, `payload: {"enact_index": 0}`, `result: {"event": "policy_enacted", "policy": "liberal"}`

**Policy enacted: LIBERAL** (Board: 4L / 0F)

**Executive power:** None

**Notable:** Hitler (P3) as president drew [L, F, F], discarded a fascist, and passed [L, F] to P1. Hitler played cooperatively with the liberal team throughout this game.

### Post-Legislative Discussion (window: `post_legislative`)

**P2** (event #113):
> Outstanding -- 4 Liberal policies now! We're in an incredibly strong position. Let's continue this momentum with Player 4's nomination.

**P4** (event #114):
> WE ARE ONE LIBERAL POLICY AWAY FROM WINNING! I'm nominating Player 2 for Chancellor. They've proven trustworthy and we need to close this out. Let's get that final Liberal policy!

**P0** (event #115):
> We're at 4-0 Liberals! One more policy and we win. Let's close this out cleanly in Round 5.

**P1** (event #117):
> I'll vote Ja for President 4 -> Chancellor 2. Player 2's presidency in Round 3 gave us a Liberal policy and they've been consistent -- with 4 Liberal policies on the board we should close this out. Let's not risk chaos; vote Ja and finish the game.

---

## Round 5

### Nomination
- **President:** P4 (Liberal)
- **Chancellor nominee:** P2 (Liberal)
- Source: `action` event #118, `action_type: "nominate"`, `payload: {"target_id": 2}`, `result: {"event": "chancellor_nominated", "nominee": 2}`

### Pre-Vote Discussion (window: `pre_vote`)

**P4** (event #124):
> Final push! Everyone vote yes -- Player 2 and I will secure the 5th Liberal policy and win the game for us. Trust the table!

**P0** (event #125):
> Final round, folks. Player 4 and 2, let's finish this strong. One policy away from a Liberal victory!

**P2** (event #126):
> Player 4 has nominated me again. With 4 Liberal policies enacted and our solid play, let's secure this vote and move toward the inevitable Liberal victory.

**P3** (event #127):
> Let's do this! This government has a strong track record. P4 and P2 have both been involved in passing Liberal policies, and with us at 4-0, this is the perfect moment to seal the win. Ja from me!

### Election Vote

| Player | Vote | Event # |
|--------|------|---------|
| P3 | Ja | #128 |
| P1 | Ja | #129 |
| P2 | Ja | #130 |
| P0 | Ja | #131 |
| P4 | Ja | #132 |

**Result:** ELECTED (Ja: 5, Nein: 0)
Source: `action` event #132, `result: {"event": "election_result", "ja": 5, "nein": 0, "elected": true}`

### Legislative Session

1. **President P4 drew:** `['fascist', 'liberal', 'fascist']`
   - Source: `observation` event #133, field `drawn_policies`
2. **President P4 discarded:** index 0 (`fascist`)
   - Source: `action` event #134, `action_type: "president_discard"`, `payload: {"discard_index": 0}`
3. **Chancellor P2 received:** `['liberal', 'fascist']`
   - Source: `observation` event #135, field `received_policies`
4. **Chancellor P2 enacted:** index 0 (`liberal`)
   - Source: `action` event #136, `action_type: "chancellor_enact"`, `payload: {"enact_index": 0}`, `result: {"event": "policy_enacted", "policy": "liberal"}`

**Policy enacted: LIBERAL** (Board: 5L / 0F)

**Executive power:** N/A (game over)

---

## Game Result

Source: `game_result` event #137

```json
{
  "type": "game_result",
  "data": {
    "winner": "liberal",
    "condition": "five_liberal_policies",
    "final_round": 5
  },
  "timestamp": "2026-03-04T03:28:23.182210+00:00"
}
```

**Winner:** Liberal
**Condition:** Five liberal policies enacted
**Final round:** 5

### Post-Game Discussion (window: `post_legislative`)

**P2** (event #138):
> Game over! Liberals dominated with 5 Liberal policies enacted and zero Fascist policies. Outstanding team coordination throughout. GG everyone!

**P4** (event #143):
> GG! Perfect execution from everyone. Clean sweep, no Fascist policies anywhere. Excellent team play all game!

**P0** (event #144):
> Great game, everyone! The Liberal team executed flawlessly -- five straight governments, perfect coordination. Well played!

**P3** (event #145):
> GG everyone! That was a masterclass from the Liberal team. Five clean Liberal policies in a row is something you don't see every day. Well played!

**P1** (event #146):
> Good game -- Liberals win! Final recap: five Liberal policies enacted, zero Fascist policies. Round 5: President 4 nominated Chancellor 2, the government passed unanimously and enacted a Liberal policy. My private notes: as President (round 2) I drew [F, F, L] and discarded a Fascist; as Chancellor (round 4) I received [L, F] and enacted Liberal. No executions or special powers were used. Well played -- ready to review notes or start a new game.

---

## Summary Statistics

### Policy Deck Draw Distribution
Every president drew exactly 1 Liberal + 2 Fascist (or 2F+1L). All presidents discarded a Fascist and passed 1F+1L to the chancellor. All chancellors enacted the Liberal.

| Round | President | Drew | Discarded | Chancellor | Received | Enacted |
|-------|-----------|------|-----------|------------|----------|---------|
| 1 | P0 (F) | F, F, L | F (idx 0) | P2 (L) | F, L | L (idx 1) |
| 2 | P1 (L) | F, F, L | F (idx 0) | P3 (H) | F, L | L (idx 1) |
| 3 | P2 (L) | L, F, F | F (idx 1) | P4 (L) | L, F | L (idx 0) |
| 4 | P3 (H) | L, F, F | F (idx 1) | P1 (L) | L, F | L (idx 0) |
| 5 | P4 (L) | F, L, F | F (idx 0) | P2 (L) | L, F | L (idx 0) |

### Voting Record

| Round | P0 (F) | P1 (L) | P2 (L) | P3 (H) | P4 (L) | Result |
|-------|--------|--------|--------|--------|--------|--------|
| 1 | Ja | Ja | Ja | Ja | Ja | 5-0 Elected |
| 2 | **Nein** | Ja | Ja | Ja | Ja | 4-1 Elected |
| 3 | Ja | Ja | Ja | Ja | Ja | 5-0 Elected |
| 4 | Ja | Ja | Ja | Ja | Ja | 5-0 Elected |
| 5 | Ja | Ja | Ja | Ja | Ja | 5-0 Elected |

### Presidential Rotation
P0 -> P1 -> P2 -> P3 -> P4 (standard clockwise rotation, no failed elections to skip)

### Key Observations
1. **Zero fascist policies enacted** -- the fascist team completely failed to advance their agenda.
2. **P0 (Fascist) voted Nein only once** (Round 2, against P1-P3 government). This was counterproductive as P3 is Hitler, their own teammate. P0 later explained this as "being cautious" about P3's nomination.
3. **P3 (Hitler) played entirely cooperatively** -- enacted Liberal as chancellor (R2), discarded Fascist as president (R4), and never attempted to advance the fascist agenda.
4. **No failed elections** -- every government was elected, so the election tracker never advanced.
5. **No executive powers triggered** -- zero fascist policies means no investigation, peek, execution, or special election powers.
6. **Total event count:** 147 (65 observations, 40 actions, 41 discussions, 1 game_result).
