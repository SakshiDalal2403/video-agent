import os
import json
import threading
import time
import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "video-agent-dev-secret")

UPLOAD_DIR = os.path.join("downloads", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

STATE_LOCK = threading.Lock()
USER_STATE = {}
ACTIVE_RUNS = {}
RAG_CHAINS = {}
WORKER_STOP_EVENTS = {}
REDIS_TTL_SECONDS = int(os.getenv("REDIS_TTL_SECONDS", "86400"))
STALE_RUN_SECONDS = int(os.getenv("STALE_RUN_SECONDS", "180"))
REDIS_CLIENT = None

try:
    import redis

    REDIS_CLIENT = redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
except Exception:
    REDIS_CLIENT = None

PIPELINE_ORDER = ["audio", "transcript", "title", "summary", "extract", "rag"]
PIPELINE_LABELS = {
    "audio": "Audio Processing",
    "transcript": "Transcription",
    "title": "Title Generation",
    "summary": "Summarisation",
    "extract": "Extraction",
    "rag": "RAG Engine",
}


def default_pipeline_steps():
    return {step: "pending" for step in PIPELINE_ORDER}


def _build_default_state():
    now = time.time()
    return {
        "processing": False,
        "pipeline_done": False,
        "pipeline_steps": default_pipeline_steps(),
        "result": None,
        "chat_history": [],
        "error": None,
        "started_at": None,
        "updated_at": now,
        "heartbeat_at": None,
    }


def _run_state_key(run_id):
    return f"video_agent:run:{run_id}:state"


def _active_run_key(sid, tab_id):
    return f"video_agent:active:{sid}:{tab_id}"


def _memory_active_key(sid, tab_id):
    return f"{sid}:{tab_id}"


def _disable_redis():
    global REDIS_CLIENT
    REDIS_CLIENT = None


def _load_state_unlocked(run_id):
    if not run_id:
        return _build_default_state()

    if REDIS_CLIENT is not None:
        try:
            raw_state = REDIS_CLIENT.get(_run_state_key(run_id))
            if raw_state:
                return json.loads(raw_state)
        except Exception:
            _disable_redis()

    if run_id not in USER_STATE:
        USER_STATE[run_id] = _build_default_state()
        USER_STATE[run_id]["run_id"] = run_id
    return USER_STATE[run_id]


def _save_state_unlocked(run_id, state):
    if not run_id:
        return

    state["updated_at"] = time.time()
    USER_STATE[run_id] = state

    if REDIS_CLIENT is not None:
        try:
            REDIS_CLIENT.setex(
                _run_state_key(run_id),
                REDIS_TTL_SECONDS,
                json.dumps(state),
            )
        except Exception:
            _disable_redis()


def set_active_run(sid, tab_id, run_id):
    if not tab_id:
        return

    ACTIVE_RUNS[_memory_active_key(sid, tab_id)] = run_id

    if REDIS_CLIENT is not None:
        try:
            REDIS_CLIENT.setex(
                _active_run_key(sid, tab_id),
                REDIS_TTL_SECONDS,
                run_id,
            )
        except Exception:
            _disable_redis()


def get_active_run(sid, tab_id):
    if not tab_id:
        return None

    if REDIS_CLIENT is not None:
        try:
            run_id = REDIS_CLIENT.get(_active_run_key(sid, tab_id))
            if run_id:
                return run_id
        except Exception:
            _disable_redis()

    return ACTIVE_RUNS.get(_memory_active_key(sid, tab_id))


def get_request_tab_id(payload=None):
    payload = payload or {}
    return (
        request.args.get("tab_id")
        or request.form.get("tab_id")
        or payload.get("tab_id")
        or ""
    ).strip()


def get_request_run_id(payload=None):
    payload = payload or {}
    return (
        request.args.get("run_id")
        or request.form.get("run_id")
        or payload.get("run_id")
        or ""
    ).strip()


def get_session_id():
    sid = session.get("video_agent_sid")
    if not sid:
        sid = str(uuid.uuid4())
        session["video_agent_sid"] = sid
    return sid


def _ensure_state_unlocked(run_id):
    state = _load_state_unlocked(run_id)
    _mark_stale_state_unlocked(run_id, state)
    return state


def _mark_stale_state_unlocked(run_id, state):
    if not run_id or not state.get("processing"):
        return

    heartbeat_at = state.get("heartbeat_at") or state.get("updated_at") or state.get("started_at")
    if heartbeat_at and time.time() - float(heartbeat_at) <= STALE_RUN_SECONDS:
        return

    for step, status in state["pipeline_steps"].items():
        if status == "active":
            state["pipeline_steps"][step] = "pending"

    state["processing"] = False
    state["pipeline_done"] = False
    state["error"] = "Pipeline stopped because the server restarted during processing. Please start the analysis again."
    _save_state_unlocked(run_id, state)


def ensure_state(run_id):
    with STATE_LOCK:
        return _ensure_state_unlocked(run_id)


def serialize_state(state):
    result = state.get("result") or {}
    return {
        "processing": state["processing"],
        "pipeline_done": state["pipeline_done"],
        "pipeline_steps": state["pipeline_steps"],
        "error": state["error"],
        "chat_history": state["chat_history"],
        "result": {
            "title": result.get("title"),
            "transcript": result.get("transcript"),
            "summary": result.get("summary"),
            "action_items": result.get("action_items"),
            "key_decisions": result.get("key_decisions"),
            "open_questions": result.get("open_questions"),
        }
        if result
        else None,
        "pipeline_labels": PIPELINE_LABELS,
    }


def update_state(run_id, **changes):
    with STATE_LOCK:
        state = _ensure_state_unlocked(run_id)
        state.update(changes)
        _save_state_unlocked(run_id, state)


def update_step(run_id, step, status):
    with STATE_LOCK:
        state = _ensure_state_unlocked(run_id)
        state["pipeline_steps"][step] = status
        _save_state_unlocked(run_id, state)


def append_chat_message(run_id, role, content):
    with STATE_LOCK:
        state = _ensure_state_unlocked(run_id)
        state["chat_history"].append({"role": role, "content": content})
        _save_state_unlocked(run_id, state)


def reset_state_for_run(run_id, sid, tab_id):
    with STATE_LOCK:
        state = _build_default_state()
        now = time.time()
        state["processing"] = True
        state["sid"] = sid
        state["tab_id"] = tab_id
        state["run_id"] = run_id
        state["started_at"] = now
        state["heartbeat_at"] = now
        USER_STATE[run_id] = state
        _save_state_unlocked(run_id, state)
        RAG_CHAINS.pop(run_id, None)


def log_pipeline(run_id, message):
    print(f"[pipeline:{run_id}] {message}", flush=True)


def heartbeat_pipeline(run_id, stop_event):
    while not stop_event.wait(15):
        with STATE_LOCK:
            state = _load_state_unlocked(run_id)
            if not state.get("processing"):
                return
            state["heartbeat_at"] = time.time()
            _save_state_unlocked(run_id, state)


def run_pipeline_async(run_id, source, language):
    stop_event = threading.Event()
    WORKER_STOP_EVENTS[run_id] = stop_event
    heartbeat = threading.Thread(
        target=heartbeat_pipeline,
        args=(run_id, stop_event),
        daemon=True,
    )
    heartbeat.start()

    try:
        from utils.audio_processor import process_input

        log_pipeline(run_id, "Starting audio processing")
        update_step(run_id, "audio", "active")
        chunks = process_input(source)
        update_step(run_id, "audio", "done")
        log_pipeline(run_id, f"Audio processing done ({len(chunks)} chunk(s))")

        from core.transcriber import transcribe_all

        log_pipeline(run_id, "Starting transcription")
        update_step(run_id, "transcript", "active")
        transcript = transcribe_all(chunks, language)
        update_step(run_id, "transcript", "done")
        log_pipeline(run_id, f"Transcription done ({len(transcript)} characters)")

        from core.summarize import generate_title, summarize

        log_pipeline(run_id, "Starting title generation")
        update_step(run_id, "title", "active")
        title = generate_title(transcript)
        update_step(run_id, "title", "done")
        log_pipeline(run_id, "Title generation done")

        log_pipeline(run_id, "Starting summarisation")
        update_step(run_id, "summary", "active")
        summary = summarize(transcript)
        update_step(run_id, "summary", "done")
        log_pipeline(run_id, "Summarisation done")

        from core.extractor import extract_action_items, extract_key_decisions, extract_questions

        log_pipeline(run_id, "Starting extraction")
        update_step(run_id, "extract", "active")
        action_items = extract_action_items(transcript)
        key_decisions = extract_key_decisions(transcript)
        open_questions = extract_questions(transcript)
        update_step(run_id, "extract", "done")
        log_pipeline(run_id, "Extraction done")

        from core.rag_engine import build_rag_chain

        log_pipeline(run_id, "Starting RAG vector store")
        update_step(run_id, "rag", "active")
        rag_chain = build_rag_chain(transcript, run_id=run_id)
        chroma_path = os.path.join("vector_db", "runs", run_id)
        update_step(run_id, "rag", "done")
        log_pipeline(run_id, f"RAG vector store done at {chroma_path}")

        RAG_CHAINS[run_id] = rag_chain
        update_state(
            run_id,
            processing=False,
            pipeline_done=True,
            chroma_path=chroma_path,
            result={
                "title": title,
                "transcript": transcript,
                "summary": summary,
                "action_items": action_items,
                "key_decisions": key_decisions,
                "open_questions": open_questions,
            },
        )
        log_pipeline(run_id, "Pipeline complete")
    except Exception as exc:
        log_pipeline(run_id, f"Pipeline failed: {exc}")
        with STATE_LOCK:
            state = _ensure_state_unlocked(run_id)
            for step, status in state["pipeline_steps"].items():
                if status == "active":
                    state["pipeline_steps"][step] = "pending"
            state["processing"] = False
            state["pipeline_done"] = False
            state["error"] = str(exc)
            _save_state_unlocked(run_id, state)
    finally:
        stop_event.set()
        WORKER_STOP_EVENTS.pop(run_id, None)


@app.route("/")
def index():
    get_session_id()
    return render_template("index.html")


@app.get("/api/state")
def get_state():
    sid = get_session_id()
    tab_id = get_request_tab_id()
    run_id = get_request_run_id() or get_active_run(sid, tab_id)
    state = ensure_state(run_id)
    return jsonify(serialize_state(state))


@app.post("/api/analyze")
def analyze():
    sid = get_session_id()
    uploaded_file = None

    if request.content_type and request.content_type.startswith("multipart/form-data"):
        source = (request.form.get("source") or "").strip()
        language = (request.form.get("language") or "english").strip().lower()
        tab_id = get_request_tab_id()
        uploaded_file = request.files.get("file")
    else:
        payload = request.get_json(silent=True) or {}
        source = (payload.get("source") or "").strip()
        language = (payload.get("language") or "english").strip().lower()
        tab_id = get_request_tab_id(payload)

    if uploaded_file and uploaded_file.filename:
        original_name = secure_filename(uploaded_file.filename)
        if not original_name:
            return jsonify({"error": "Uploaded file name is not valid."}), 400
        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        source = os.path.join(UPLOAD_DIR, stored_name)
        uploaded_file.save(source)

    if not source:
        return jsonify({"error": "Please enter a YouTube URL, file path, or upload an audio/video file."}), 400

    if language not in {"english", "hinglish"}:
        return jsonify({"error": "Language must be either 'english' or 'hinglish'."}), 400

    active_run_id = get_active_run(sid, tab_id)
    state = ensure_state(active_run_id)
    if state["processing"]:
        return jsonify({"error": "Pipeline is already running."}), 409

    run_id = uuid.uuid4().hex
    set_active_run(sid, tab_id, run_id)
    reset_state_for_run(run_id, sid, tab_id)

    worker = threading.Thread(
        target=run_pipeline_async,
        args=(run_id, source, language),
        daemon=True,
    )
    worker.start()

    return jsonify({"ok": True, "run_id": run_id})


@app.post("/api/chat")
def chat():
    sid = get_session_id()
    payload = request.get_json(silent=True) or {}
    tab_id = get_request_tab_id(payload)
    run_id = get_request_run_id(payload) or get_active_run(sid, tab_id)
    question = (payload.get("question") or "").strip()

    if not question:
        return jsonify({"error": "Please enter a question."}), 400

    state = ensure_state(run_id)
    if not state["pipeline_done"]:
        return jsonify({"error": "Run the analysis first."}), 400

    rag_chain = RAG_CHAINS.get(run_id)
    if rag_chain is None:
        chroma_path = state.get("chroma_path")
        if chroma_path:
            from core.rag_engine import load_rag_chain

            rag_chain = load_rag_chain(chroma_path)
            RAG_CHAINS[run_id] = rag_chain

    if rag_chain is None:
        return jsonify({"error": "RAG chain is not available for this analysis."}), 400

    from core.rag_engine import ask_question

    append_chat_message(run_id, "user", question)
    try:
        answer = ask_question(rag_chain, question)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500

    append_chat_message(run_id, "assistant", answer)

    return jsonify({"answer": answer, "chat_history": ensure_state(run_id)["chat_history"]})


@app.post("/api/chat/clear")
def clear_chat():
    sid = get_session_id()
    payload = request.get_json(silent=True) or {}
    tab_id = get_request_tab_id(payload)
    run_id = get_request_run_id(payload) or get_active_run(sid, tab_id)
    with STATE_LOCK:
        state = _ensure_state_unlocked(run_id)
        state["chat_history"] = []
        _save_state_unlocked(run_id, state)
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "false").lower() == "true",
    )
