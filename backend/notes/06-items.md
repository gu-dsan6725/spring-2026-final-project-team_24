# Items (Hyperedges)

**Items** are actionable study and assessment materials. Structurally, each item is a **hyperedge** connecting multiple concept nodes as its foundation — a problem typically requires understanding several concepts, not just one.

## Item as Hyperedge

- An item lists its **foundation concepts** — the set of concepts a user must know to attempt it.
- An item becomes **attemptable** only when all foundation concepts are in the user's knowledge state K.
- **Completing** an item confirms mastery of its foundation concepts (strengthens K).
- **Failing** an item identifies which foundation concept the error relates to, surfacing it for targeted review.

## Item Types

| Item | Description |
|---|---|
| **Problem / Exercise** | A question or task spanning one or more concepts |
| **Definition** | A concise, testable statement extracted from a concept |
| **Proof / Derivation** | Step-by-step logical constructions tied to theoretical concepts |
| **Code Challenge** | Programming tasks derived from data or technical concepts |

## Item Search & Generation

A user can select a set of concepts and edges, optionally include reference items as examples, and either **search** for existing items or **request generation** of new ones.

### Search

1. User selects one or more concepts and/or edges as the desired foundation.
2. System queries existing items whose foundation concepts overlap or match the selection.
3. Results ranked by: exact match on all selected concepts > partial overlap > related via traversal edges.
4. Reference items (if provided by the user) refine the search — find items of similar structure, difficulty, or type.

### Generation

If no suitable items exist, the user can request generation. The system evaluates a **difficulty feasibility check** before proceeding:

| Domain / Complexity | Action |
|---|---|
| **High-complexity formal domains** (e.g., IMO-level number theory + geometry proofs, advanced mathematical olympiad, novel theorem construction) | **Abandon** — decline the request. LLM-generated items in these domains are unreliable and risk producing incorrect or trivially flawed problems. Surface a message: "This combination requires expert-authored items." |
| **Standard academic domains** (e.g., undergraduate math, statistics, CS, engineering) | **Generate with review** — trigger item generation module, flag output for user or instructor review before adding to the item pool. |
| **Knowledge-recall and application domains** (e.g., medical, law, history, language learning, definitions, case studies) | **Generate** — trigger item generation module. These domains are well-suited to LLM generation: definition-based questions, scenario analysis, case matching. |

The difficulty feasibility check is configurable per group — an admin or instructor can adjust which concept combinations are allowed for generation vs. flagged as too complex.

### Generation Pipeline (high-level)

1. Selected concepts + edges + reference items are assembled into a generation context.
2. The context is passed to the group's configured item construction pipeline (see [Groups — AI Pipelines](08-groups.md)).
3. The pipeline produces candidate items with foundation concept annotations.
4. Candidates are validated: structural integrity (well-formed question + answer), concept coverage (do the foundation concepts actually appear), and dedup against existing items.
5. Accepted items are stored and linked to their foundation concepts as hyperedges.

> *[Module design deferred]* — The internal composition of the item generation module (prompt templates, multi-step generation, difficulty calibration, domain classifiers) will be specified in a dedicated design document.

## Modules

**Flashcards** — auto-generated from definitions and key concepts. Supports text, LaTeX, images, audio. Tied into spaced repetition.

**Handwriting Problem Solving** — user submits handwritten solutions (photo/scan/tablet). OCR + LLM pipeline validates correctness, provides feedback, identifies errors. Configurable LLM backend per group.

> *[Further modules deferred]* — Interactive simulations, peer review, timed quizzes, collaborative problem solving.

## Memory Curve & Study Scheduling

- Spaced repetition (e.g., SM-2, FSRS) per user per item.
- Tracks recall probability over time.
- Generates personalized study schedules.
- Integrates with traversal: struggling with an item surfaces prerequisite concepts for review.

> *[Detailed design deferred]* — Algorithm selection, scheduling UX, notification system, cross-device sync.
