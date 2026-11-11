"""Streamlit spectator interface. Run with: streamlit run app.py."""

import streamlit as st
from groq import APIConnectionError, APIStatusError, AuthenticationError, RateLimitError

from game.agents import create_client
from game.case import CASE_TITLE, EVIDENCE, MAX_ACTIONS, MAX_INTERROGATIONS, PUBLIC_BRIEFING, SUSPECTS
from game.engine import Game


st.set_page_config(page_title=CASE_TITLE, page_icon="🔎", layout="wide")

if "game" not in st.session_state:
    st.session_state.game = Game()
    st.session_state.running = False
    st.session_state.game_error = None

game = st.session_state.game

st.title(f"🔎 {CASE_TITLE}")
st.caption("An autonomous AI investigation · Groq · Detective Alex Reed and three suspects")

with st.expander("Case briefing"):
    st.text(PUBLIC_BRIEFING)

with st.sidebar:
    st.header("Case file")
    st.caption("Scenario: loading entrance recording available")
    for profile in SUSPECTS.values():
        st.write(f"**{profile['name']}** — {profile['role']}")
    st.divider()
    st.subheader("Evidence catalog")
    for evidence_id, item in EVIDENCE.items():
        status = "Inspected" if evidence_id in game.inspected_ids else "Unopened"
        st.write(f"{evidence_id} · {item['title']} — {status}")
    st.caption("Recording evidence is a fixed text description. No video is sent to the model.")

    if st.button("New game", disabled=st.session_state.running):
        st.session_state.game = Game()
        st.session_state.running = False
        st.session_state.game_error = None
        st.rerun()

metrics = st.columns(3)
metrics[0].metric("Actions remaining", MAX_ACTIONS - game.actions_used)
metrics[1].metric("Questions remaining", MAX_INTERROGATIONS - game.questions_used)
metrics[2].metric("Evidence inspected", f"{len(game.inspected_ids)} / {len(EVIDENCE)}")

controls = st.columns(3)
next_turn = controls[0].button(
    "Next turn", disabled=game.finished or st.session_state.running,
)
if controls[1].button(
    "Run investigation", type="primary",
    disabled=game.finished or st.session_state.running,
):
    st.session_state.running = True
    st.session_state.game_error = None
    st.rerun()
if controls[2].button("Pause", disabled=not st.session_state.running):
    st.session_state.running = False
    st.rerun()

st.caption("Running makes real Groq API requests. Pause takes effect between turns.")

st.subheader("Public investigation transcript")
if not game.transcript:
    st.info("Start the investigation to watch the detective choose an action.")

for index, event in enumerate(game.transcript, start=1):
    action, result = event["action"], event["result"]
    if action["type"] == "question":
        name = SUSPECTS[action["suspect_id"]]["name"]
        with st.chat_message("assistant"):
            st.caption(f"Turn {index} · Detective → {name}")
            st.text(action["question"])
        with st.chat_message("user"):
            st.caption(name)
            st.text(result["answer"])
    elif action["type"] == "inspect":
        with st.chat_message("assistant"):
            st.caption(f"Turn {index} · Inspect {result['evidence_id']}")
            st.write(f"**{result['title']}**")
            st.text(result["content"])
    else:
        st.caption(f"Turn {index} · Detective submits a final verdict")

if game.finished:
    st.session_state.running = False
    st.subheader("Final verdict")
    verdict = game.verdict
    suspect_id = verdict["suspect_id"]
    if suspect_id is None:
        st.warning("The detective abstained: insufficient evidence.")
    else:
        st.write(f"**Accused:** {SUSPECTS[suspect_id]['name']}")
    st.text(verdict["explanation"])
    st.write("**Cited evidence:** " + (", ".join(verdict["evidence_ids"]) or "None"))
    for evidence_id in verdict["evidence_ids"]:
        with st.expander(f"{evidence_id} · {EVIDENCE[evidence_id]['title']}"):
            st.text(EVIDENCE[evidence_id]["content"])

    with st.expander("Evaluation — revealed after the game"):
        evaluation = game.evaluation
        reference_name = SUSPECTS[evaluation["reference_culprit_id"]]["name"]
        st.write(f"**Reference culprit:** {reference_name}")
        st.write(f"Correct culprit named: {evaluation['correct_culprit']}")
        st.write(f"Decisive evidence inspected: {evaluation['decisive_evidence_inspected']}")
        st.write(f"Decisive evidence cited: {evaluation['decisive_evidence_cited']}")
        st.write(f"All citations inspected: {evaluation['citations_are_inspected']}")
        st.info(evaluation["explanation_review"])

if st.session_state.game_error:
    st.error(st.session_state.game_error)

# One turn per rerun lets the transcript update throughout autonomous play.
# Only the Game object is retained; the client is closed after each turn.
if (next_turn or st.session_state.running) and not game.finished:
    try:
        with st.spinner("The agents are investigating…"):
            with create_client() as client:
                game.step(client)
        st.session_state.game_error = None
    except AuthenticationError:
        st.session_state.game_error = "Groq rejected the API key. Check your local .env file."
    except RateLimitError:
        st.session_state.game_error = "Groq rate limit reached. Wait, then retry using Next turn."
    except APIConnectionError:
        st.session_state.game_error = "Cannot connect to Groq. Check your connection and retry."
    except APIStatusError as exc:
        st.session_state.game_error = f"Groq returned HTTP {exc.status_code}. Check your model access and retry."
    except (RuntimeError, ValueError):
        st.session_state.game_error = "The turn could not complete. Check configuration or retry using Next turn."

    if st.session_state.game_error:
        st.session_state.running = False
    st.rerun()
