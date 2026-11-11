import json

from game.agents import (
    choose_detective_action,
    create_detective_history,
    create_suspect_histories,
    question_suspect,
)
from game.case import (
    EVIDENCE,
    MAX_ACTIONS,
    MAX_INTERROGATIONS,
    REFERENCE_SOLUTION,
    SUSPECTS,
)


class Game:
    def __init__(self):
        self.detective_history = create_detective_history()
        self.suspect_histories = create_suspect_histories()

        self.actions_used = 0
        self.questions_used = 0
        self.inspected_ids = []
        self.transcript = []
        self.verdict = None
        self.evaluation = None

    @property
    def finished(self):
        return self.verdict is not None

    def turn_state(self):
        return {
            "actions_remaining": MAX_ACTIONS - self.actions_used,
            "questions_remaining": MAX_INTERROGATIONS - self.questions_used,
            "inspected_evidence_ids": list(self.inspected_ids),
            "available_evidence_ids": [
                item_id
                for item_id in EVIDENCE
                if item_id not in self.inspected_ids
            ],
            "instruction": (
                "Submit your verdict now."
                if self.actions_used >= MAX_ACTIONS
                else "Choose your next action."
            ),
        }

    def validate_action(self, action):
        action_type = action.get("type")

        if action_type not in {"question", "inspect", "verdict"}:
            raise ValueError("Unknown action type.")

        if action_type == "verdict":
            self.validate_verdict(action)
            return

        if self.actions_used >= MAX_ACTIONS:
            raise ValueError("No actions remain. Submit a verdict.")

        if action_type == "question":
            if self.questions_used >= MAX_INTERROGATIONS:
                raise ValueError("No interrogation questions remain.")

            if action.get("suspect_id") not in SUSPECTS:
                raise ValueError("Unknown suspect ID.")

            question = action.get("question")
            if not isinstance(question, str) or not question.strip():
                raise ValueError("A nonempty question is required.")

            if len(question) > 2000:
                raise ValueError("Question exceeds 2000 characters.")

        if action_type == "inspect":
            evidence_id = action.get("evidence_id")

            if evidence_id not in EVIDENCE:
                raise ValueError("Unknown evidence ID.")

            if evidence_id in self.inspected_ids:
                raise ValueError("This evidence has already been inspected.")

    def validate_verdict(self, action):
        if "suspect_id" not in action:
            raise ValueError("Verdict requires suspect_id, or null to abstain.")

        suspect_id = action["suspect_id"]
        if suspect_id is not None and suspect_id not in SUSPECTS:
            raise ValueError("Unknown suspect in verdict.")

        evidence_ids = action.get("evidence_ids")
        if not isinstance(evidence_ids, list):
            raise ValueError("evidence_ids must be a list.")

        if not all(isinstance(item, str) for item in evidence_ids):
            raise ValueError("Evidence IDs must be strings.")

        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Evidence citations must be unique.")

        if any(item not in self.inspected_ids for item in evidence_ids):
            raise ValueError("Cannot cite evidence that was not inspected.")

        explanation = action.get("explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            raise ValueError("Verdict requires an explanation.")

    def step(self, client):
        if self.finished:
            raise ValueError("This game has already finished.")

        # Give the detective up to three attempts to produce a valid action.
        feedback = []
        for _ in range(3):
            try:
                action = choose_detective_action(
                    client,
                    self.detective_history + feedback,
                    self.turn_state(),
                )
                self.validate_action(action)
                break
            except ValueError as exc:
                feedback.append({
                    "role": "user",
                    "content": (
                        f"Your proposed action was rejected: {exc} "
                        "Return a corrected action as a JSON object."
                    ),
                })
        else:
            raise RuntimeError(
                "The detective failed to provide a valid action "
                "after three attempts."
            )

        action_type = action["type"]

        if action_type == "question":
            suspect_id = action["suspect_id"]
            answer = question_suspect(
                client,
                self.suspect_histories[suspect_id],
                action["question"],
            )
            result = {
                "suspect_id": suspect_id,
                "answer": answer,
            }
            self.questions_used += 1
            self.actions_used += 1

        elif action_type == "inspect":
            evidence_id = action["evidence_id"]
            result = {
                "evidence_id": evidence_id,
                **EVIDENCE[evidence_id],
            }
            self.inspected_ids.append(evidence_id)
            self.actions_used += 1

        else:
            self.verdict = action
            self.evaluation = self.evaluate_verdict(action)
            result = {"status": "Game finished."}

        self.detective_history.extend([
            {"role": "assistant", "content": json.dumps(action)},
            {"role": "user", "content": json.dumps(result)},
        ])

        event = {"action": action, "result": result}
        self.transcript.append(event)
        return event

    def evaluate_verdict(self, verdict):
        culprit_id = REFERENCE_SOLUTION["culprit_id"]
        decisive_id = REFERENCE_SOLUTION["decisive_evidence_id"]
        accused_id = verdict["suspect_id"]

        return {
            "abstained": accused_id is None,
            "correct_culprit": accused_id == culprit_id,
            "reference_culprit_id": culprit_id,
            "decisive_evidence_inspected": (
                decisive_id in self.inspected_ids
            ),
            "decisive_evidence_cited": (
                decisive_id in verdict["evidence_ids"]
            ),
            "citations_are_inspected": all(
                item in self.inspected_ids
                for item in verdict["evidence_ids"]
            ),
            "explanation_review": (
                "Manual review required: check that the explanation "
                "accurately describes the cited evidence and does not "
                "invent facts or overstate what it proves."
            ),
        }