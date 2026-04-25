# Meta-Harness

## Source

- **Paper**: [Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052) (Stanford IRIS Lab, 2026)
- **GitHub**: [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)

## Summary

Meta-Harness is an automated framework for optimizing the entire harness (system prompts, tool definitions, completion-checking logic, context management) around an LLM application. It gives an agentic proposer access to a filesystem containing full source code, execution traces, and scores of all prior configurations — up to 10M tokens of diagnostic context per optimization step.

### How It Works

1. An agent reads a filesystem containing all prior candidates' source code, execution traces, and scores.
2. The agent proposes a new harness configuration based on diagnosed failure modes.
3. The proposed harness is evaluated on held-out tasks.
4. All logs are stored in the filesystem, and the loop repeats.

### Key Results

- TerminalBench-2: 76.4% (Claude Opus 4.6) — #2 among all agents
- TerminalBench-2: 37.6% (Claude Haiku 4.5) — #1 among all agents
- +7.7 points over ACE on text classification with 4x fewer context tokens
- +4.7 points average on math reasoning across 5 held-out models

### Key Differentiator

Prior optimization methods compress history into short summaries or scalar scores (~0.001–0.026 Mtok/iter). Meta-Harness provides the proposer with up to 10 Mtok/iter of raw diagnostic data, allowing it to trace failures back to specific pipeline decisions.

## Applicability to This Platform

Meta-Harness maps to the **outer loop** of the AI optimization architecture (see plan.md Section 9.2):

| Meta-Harness Concept | Platform Mapping |
|---|---|
| **Harness** | A group's full AI pipeline: embedding model, connection inference method, item generation prompt, grading rubric, similarity thresholds. |
| **Execution traces** | Logs of what the AI produced: which concepts were embedded, what edges were proposed, what items were generated, user feedback/scores. |
| **Proposer** | Diagnoses why certain AI edges were rejected or items were poor quality by reading the full trace, then proposes pipeline config changes. |
| **Evaluation** | Test new pipeline config on held-out data before deploying to the group. |

Meta-Harness is triggered periodically or when group-level metrics plateau (e.g., edge acceptance rate drops, item completion rate falls). It is heavier than ACE and runs less frequently — think weekly or on-demand by an admin.
