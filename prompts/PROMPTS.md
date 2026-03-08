# prompts/

System prompt templates for LLM agents playing Secret Hitler.
Assembled at runtime by `build_system_prompt()` in `orchestration/backends.py`.

## Files

| File | Purpose |
|------|---------|
| `base_rules.md` | Always included. Game rules, role/team structure, turn flow, MCP tool reference, and behavioral guidelines. Contains template placeholders (`{player_id}`, `{num_players}`, `{max_player_id}`, `{game_premise}`) filled at build time. |
| `liberal.md` | Appended when the agent is assigned the Liberal role. Covers trust-building, voting/legislative analysis, executive power usage, and common traps. |
| `fascist.md` | Appended when the agent is assigned the Fascist role. Covers deception, legislative sabotage, protecting Hitler, coordinating with teammates, and the Hitler-chancellor win play. |
| `hitler.md` | Appended when the agent is assigned the Hitler role. Covers survival-first play, mimicking Liberal behavior, and positioning for the chancellor election win. Distinguishes 5-6p (knows Fascists) vs 7+p (plays blind). |

## Assembly

`build_system_prompt(skin, role, player_id, num_players, game_premise)` loads
`base_rules.md`, fills its placeholders, then appends the role-specific file
(`liberal.md`, `fascist.md`, or `hitler.md`) separated by a horizontal rule.
The resulting string is used as the agent's system prompt for the entire game.
