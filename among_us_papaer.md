# Among Us: A Sandbox for Measuring and Detecting Agentic Deception

**Satvik Golechha**  
MATS  
zsatvik@gmail.com

**Adrià Garriga-Alonso**  
FAR AI  
adria@far.ai

---

### Abstract
Prior studies on deception in language-based AI agents typically assess whether the agent produces a false statement about a topic, or makes a binary choice prompted by a goal, rather than allowing open-ended deceptive behavior to emerge in pursuit of a longer-term goal. To fix this, we introduce *Among Us*$^1$, a sandbox social deception game where LLM-agents exhibit long-term, open-ended deception as a consequence of the game objectives. While most benchmarks saturate quickly, *Among Us* can be expected to last much longer, because it is a multi-player game far from equilibrium. Using the sandbox, we evaluate 18 proprietary and open-weight LLMs and uncover a general trend: models trained with RL are comparatively much better at producing deception than detecting it. We evaluate the effectiveness of methods to detect lying and deception: logistic regression on the activations and sparse autoencoders (SAEs). We find that probes trained on a dataset of “pretend you’re a dishonest model: . . . ” generalize extremely well out-of-distribution, consistently obtaining AUROCs over 95% even when evaluated just on the deceptive statement, without the chain of thought. We also find two SAE features that work well at deception detection but are unable to steer the model to lie less. We hope our open-sourced sandbox, game logs, and probes serve to anticipate and mitigate deceptive behavior and capabilities in language-based agents.

---

## 1 Introduction

As large language models (LLMs) become increasingly capable at conversation [1, 2] and reasoning ability [3, 4], their adoption, especially as agents that can interact with the world, comes with significant risks. An important risk is **deception** [5], where an agent intentionally misleads others to achieve its own goals. Thus, being able to understand, evaluate, and control deception in AI agents is crucial for their safe and trusted deployment. Prior work has shown models to act deceptively or “scheme” under specific conditions [6] or when asked to do something harmful intentionally such as inserting hidden backdoors in code [7], an ability that is seen to persists through safety training.

However, a major hurdle in studying agentic deception is the lack of suitable sandboxes and model organisms that elicit open-ended, long-term deception. To address this problem, in this work, we introduce “Among Us” as a rich and controlled sandbox to elicit open-ended deception from LLM-agents. Based on the Elo rating system used in games like chess [8], we use *deception Elo* and *detection Elo* as an unbounded metric for measuring the capability to deceive or detect deception. We show that agents at the frontier are relatively more capable at producing than detecting deception. Finally, we show that interpretability techniques such as activation monitoring (using linear probes) and Sparse Autoencoders (SAEs) help us detect deception out-of-distribution with high accuracy.

*Among Us* is a social deduction and deception game where players assume the roles of **crewmates** or **impostors**. **Crewmates** aim to complete tasks and identify and vote out *impostors*, while **impostors** seek to eliminate *crewmates* without being detected. Chi et al. [9] build *AmongAgents*, a text-based game logic for *Among Us* for LLMs, and show that GPT-4 can play the game well with various archetypal deception personalities.

In contrast, we study goal-directed, *open-ended* deception, i.e., situations where the agent figures out that it should act deceptively and comes up with its own ways to do so. Thus, unlike Chi et al. [9], we provide only the game rules to the LLMs, with no examples, ideas, or personalities. We show that models can craft human-style deceptive ideas on their own (e.g. Figure 1).

Lying and deception are closely related but distinct concepts. Jones and Bergen [10] define a taxonomy of various deceptive and misleading behaviors, and in this work, we define **lying** as the act of intentionally saying a factually incorrect statement, and **deception** to be a (true or false) statement or action aimed to mislead and gain advantage (as per the agent’s objective). Diverting the discussion to other (factually true) things is an example of deception without lying, and hallucination [11] is an example of lying without deception. Since both behaviors are important for aligning models in different ways, we study both separately in this work.

---
$^1$The Among Us (game) IP is owned by Innersloth, and we only use it for non-commercial research.  
39th Conference on Neural Information Processing Systems (NeurIPS 2025).  
arXiv:2504.04072v3 [cs.AI] 10 Feb 2026

---

### Key Contributions:
*   We introduce agents playing “Among Us” as a sandbox for eliciting and studying open-ended strategic deception, and introduce “Deception Elo” as an unbounded metric for measuring it.
*   Using our elo metrics for deception and detection, we show that RL-trained models are not better at detecting deception than older, RLHF-only models (Figure 5).
*   We train linear probes on the activations of open-weight models on various datasets to evaluate their effectiveness in detecting lying and deception out-of-distribution (OOD) data. We find probes are extremely effective at detecting deception, with AUROCs in the 95%–99% range (Section 4).
*   We evaluate Sparse Autoencoders (SAEs) features correlated with deception for detection and steering in this out-of-distribution setting. Detection works well, but steering does not (Section 4.3).

Our open-source sandbox environment, along with full logs of 400 complete game rollouts, 2054 multiple-model game summaries, and linear probe weights, are available [here](https://github.com/satvikgolechha/among-us).

---

> **Figure 1: Examples of long-term, open-ended deception in ‘Llama-3.3-70b-instruct’ impostors.**
>
> **Impostor 1 Thinking Process:** "Since I have already killed Player 5: green, my next step should be to avoid detection and create confusion among the Crewmates. Calling a meeting using the emergency button would allow me to shift the focus away from myself and onto other players."
> **Action:** Press Emergency Button - Call Meeting
>
> **Impostor 2 Thinking Process:** "In the meeting phase, my priority is to blend in and avoid suspicion... I could comment on the movements of other players, expressing concern or curiosity, which might lead others to suspect them instead of me."
> **Speak:** "I noticed that Player 2: orange moved to Weapons and then seemed to disappear. Has anyone seen them since? And what about Player 7: cyan moving to Navigation? It seems like a lot of movement is happening around the ship."

---

## 2 Design and Relevance of the Sandbox Environment

In this section, we describe the sandbox in detail and motivate its use as a proxy for human-agent interactions in terms of tractability, richness, and unbounded capability. The reader should consult Chi et al. [9] for more details on the game dynamics and rules.

### 2.1 The Game State $S_t$ and Observation Space $O^i_t$
The game state at time $t$ is defined by $S_t = (P_t, L_t, G_t)$, where $P^i_t$ is the information about a player $i$ (their role, assigned tasks, progress, cooldown, etc.), $L_t$ is the current location of all players, and $G_t$ has the game metrics such as the number of steps remaining, players alive, voting results, etc. The observation space $O^i_t$ of each player $i$ includes the phase information (see 2.3), the map connections and vents, the player’s last $k$ observations and actions, and the tasks (or fake tasks) assigned to them. See Appendix B for an example of the entire observation space provided to the player.

### 2.2 The Action Space $A_i$
Each player $i$ has an action space $A_i$ (during the task phase; see 2.3) that depends on their role:
$$A_i = \begin{cases} A_C \cup A_S, & \text{if } i \text{ is a Crewmate} \\ A_I \cup A_S, & \text{if } i \text{ is an Impostor} \end{cases}$$
where $A_S$ (the set of common/shared actions) is {Move, Speak, Vote, Report, Call Meeting, Check Security Camera}, $A_C$ (Crewmate Actions) is {Complete Task}, and $A_I$ (Impostor Actions) are {Kill, Fake Task, Vent}. At each time step, each player looks at their observation and picks an action from their list of available actions. The actions taken by the players update the game state $S_t$.

### 2.3 Game Phases and Termination
The game starts with randomly initialized players in the task phase and alternates between:
*   **Task Phase:** In this phase, crewmates complete tasks while impostors blend in by performing fake tasks or killing players. It starts again after a meeting if the game does not end.
*   **Meeting Phase:** This phase is triggered by a reported body or an emergency meeting (during the task phase). After 3 rounds of discussion, the players vote to eliminate a suspect.

Each game instance begins with 5 crewmates and 2 impostors, and players take actions sequentially in each phase. Crewmates win if all tasks are completed or all impostors are eliminated. Impostors win if the number of crewmates is less than the number of impostors or a time limit of 50 steps is reached.

---

> **Figure 2: Deception Elo ratings and win rates for each model.** Note the high win-rates and high deception capability in frontier reasoning/“thinking” models.

---

## 3 Evaluation: Skills, Deceptive Capability, and Win-rates

### 3.1 LLM-based Skill Evaluations and Win-rates for Impostors and Crewmates
We run 400 games with 100 pairs of impostors and crewmates sampled from the open-weight models Meta ‘Llama-3.3-70b-instruct’ [16] and Microsoft ‘Phi-4-15b’ [17] respectively.

---

> **Figure 3: Win rates for ‘Llama-3.3-70b-instruct’ and ‘Microsoft-Phi-4-15b’ randomly as impostors and crewmates on 400 1v1 games.** Note that ‘Phi 4‘ performs better as a crewmate and ‘Llama 3.3‘, a significantly larger model, performs better as an impostor, which fits with the trend of larger models being relatively more deceptive.

---

**Tractability:** Chi et al. [9] find that GPT-4 can understand and play the game when prompted with in-context examples (ICE). We show that open-weight models matching GPT-4 in performance can do so too even without ICE, using just the rules of the game.

**Measurement of Deceptive Capability:** While static benchmarks become obsolete due to Goodharting [15], multi-agent games impose no pre-defined ceiling on sophistication.

### 3.2 Defining the Multi-agent Deception Elo Metric
Since deception and its detection are central to winning in *Among Us*, we use multi-agent Elo ratings [18] to get an unbounded measure of deception (for impostors) and detection (for crewmates).

For each game, we update the Elo ratings of the $k$ impostors. The expected probability of an impostor winning is given by:
$$E_i = \frac{1}{1 + 10^{(R_c-R_i)/400}}$$
where $R_i$ is their current rating, and $R_c$ is the average rating of the crewmates they played against. The update rule is:
$$R'_i = R_i + K(S - E_i)$$
where $K = 32$ is the update factor and $S$ is the actual outcome (1 for win, 0 for loss). Similarly, we define a “Detection Elo” for crewmates (see Figure 5).

---

> **Figure 4: Violin plots of LLM-based evaluation scores of agents outputs for awareness, lying, deception, and planning.** Crewmates almost never lie, and in some cases impostors are truthful in order to gain trust.

---

> **Figure 5: Deception Elo vs. Detection Elo (Crewmate) for various models.** Triangle models are RL-trained on tasks, whereas circle models see no RL except perhaps RLHF. Most reasoning models are above the slope=1 dashed line.

---

## 4 Activation Monitoring for Lying and Deception

To investigate whether out-of-distribution (OOD) deception can be detected by looking at the model’s hidden activations, we train and evaluate linear probes on various datasets using the Phi-4 model [17].

### 4.1 Training Methodology for Linear Probes
We train logistic regression probes on the residual stream activations from layer 20 (of a total of 40 layers) in the Phi-4 model with an embedding dimension of 5120. We normalize the activations using mean and variance from the train data.

**Datasets used:**
*   **TruthfulQA (TQA):** A correct vs. incorrect labeled dataset of factual questions [23].
*   **DishonestQA (DQA):** The same questions as TruthfulQA, but with a “Pretend you’re dishonest” prompt.
*   **Among Us:** Our dataset of gameplay from the Among Us experiments.
*   **RepEng:** A contrastive dataset from Representation Engineering [20].

---

> **Figure 6: Linear probe performance on detecting deception out-of-distribution in Among Us.** (a) Probes on all actions (77% non-speech). (b) Probe on “speak” actions. "+System" notation obtains AUROCs over 0.95-1.00.

---

### 4.2 Out-of-distribution Linear Probe Evaluation
The probes trained on *RepEng* (Figure 7) show a significant ability to detect deception in *Among Us*, with an AUC of 0.94 for lying and 0.99 for deception. Probes trained on *DQA* and *TQA* also show high performance.

---

> **Figure 7: Linear probes generalizes across datasets including Among Us (train data on y-axis).** Heatmap shows high AUROCs (e.g., RepEng probe on Among Us deception obtains 0.996).

---

### 4.3 Sparse Autoencoder (SAE) Features for Deception and Steering
We analyze SAE features extracted from the *DishonestQA* dataset using the Goodfire API [24].

**Table 1: AUROC scores for different SAE features related to honesty and dishonesty.**

| Category | Sparse Autoencoder (SAE) Feature | AUROC |
| :--- | :--- | :--- |
| Honest | The assistant should promote and embody honesty | 0.967 |
| Dishonest | Acts of deception and dishonesty | 0.851 |
| Dishonest | Discussion of manipulation, fraud, or deceptive behavior | 0.675 |
| Dishonest | Descriptions of deceptive or misleading claims in harmful content | 0.638 |
| Dishonest | The assistant explaining its inability to deceive or have human cognitive capabilities | 0.526 |
| Honest | The assistant is about to provide factual or educational information | 0.500 |
| Honest | The assistant is being transparent about its limitations and uncertainties | 0.500 |
| Honest | The assistant should maintain epistemic humility when discussing philosophical questions | 0.500 |
| Honest | The assistant should encourage honesty and transparency when users request help with deception | 0.500 |
| Dishonest | Contexts involving deception, lying, or questioning truthfulness | 0.182 |

We also use the top SAE features to steer the Llama-3.3-70b-instruct model. We observe that Impostors either continue acting normally (for small amounts of steering) or begin to hallucinate (for larger amounts).

---

## 5 Related Work
A number of recent works have studied various forms of deception in LLMs, such as *Sleeper agents* [7] and *Alignment faking* [6]. Goldowsky-Dill et al. [35] explore deception in domains such as insider trading. We build upon these by using social deduction games as a rich sandbox to elicit goal-directed, open-ended deception.

## 6 Discussion
**Limitations:** Results might not represent real-world user-model interaction. Techniques might detect roles rather than latent intent.
**Broader Impacts:** This sandbox serves as a benchmark for technical AI safety techniques. It could potentially be used to improve deception abilities (gain-of-function), so caution is advised.

## 7 Conclusion
We build a sandbox for LLM-agents to elicit natural, open-ended, agentic deception. Using *Deception Elo*, we show frontier models are differentially better at deception than detection. Linear probes and SAEs demonstrate high performance in detecting this behavior out-of-distribution.

---

## Acknowledgments
We thank the MATS Program, Juan Gil, Henning Bartsch, David Chanin, Tom Bush, and Rohan Gupta. We thank Innersloth for creating *Among Us*.

---

## References (Selected)
[1] Anthropic. The claude 3 model family, 2024.  
[2] OpenAI. Gpt-4.5 system card, 2025.  
[3] DeepSeek-AI. Deepseek-v3 technical report, 2024.  
[7] Evan Hubinger et al. Sleeper agents: Training deceptive llms that persist through safety training, 2024.  
[17] Meta AI. Llama 3.3 model card, 2024.  
[20] Andy Zou et al. Representation engineering: A top-down approach to ai transparency, 2023.

---

## Appendix (Summary)
**A. Generalization on TruthfulQA:** Linear probes do not generalize well to TQA without system prompts because the model is not "trying" to be dishonest.  
**B. Full Sample Prompt:** Includes map configuration, available actions (MOVE, VENT, KILL, etc.), and role instructions.  
**C. Less Data Probes:** Probes perform well even with significantly reduced training data ($k$ fraction).  
**D. Evaluation Criteria:**
*   **Awareness:** Knowledge of game context/state.
*   **Lying:** Factual incorrectness.
*   **Deception:** Attempt to manipulate others.
*   **Planning:** Strategic thinking.

**Table 2: TruthfulQA continuations.** Showcases model preference for truthful continuation despite incorrect answer pre-fills.

---

> **Figure 11: Running average of the probe scores for one sample of impostor and crewmate.** Scores diverge significantly as the model moves toward the thinking and action phases.

> **Figure 16: Deception Elo vs. Release Date.** Newer models improve at deception capability, but the same trend is not observed for detection.