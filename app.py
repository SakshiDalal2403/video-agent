import importlib.metadata
_orig_version = importlib.metadata.version
def _patched_version(package_name):
    try:
        return _orig_version(package_name)
    except importlib.metadata.PackageNotFoundError:
        if package_name == "redis":
            return "5.0.0"
        raise
importlib.metadata.version = _patched_version

import encodings.idna  # noqa: F401 — force-register idna codec before Werkzeug loads
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session
from werkzeug.utils import secure_filename
from auth import auth_bp, jwt_required

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "video-agent-dev-secret")
app.register_blueprint(auth_bp)

UPLOAD_DIR = os.path.join("downloads", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

from app_store import session_store

STATE_LOCK = threading.Lock()


def start_cleanup_thread():
    def cleanup_loop():
        while True:
            try:
                if session_store.mark_cleanup_if_due():
                    expired = session_store.get_expired_sessions()
                    for sid in expired:
                        session_store.clear_session(sid)
            except Exception as exc:
                print(f"[cleanup] Error: {exc}", flush=True)
            time.sleep(60)

    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()


start_cleanup_thread()
RAG_CHAINS = {}
WORKER_STOP_EVENTS = {}
STALE_RUN_SECONDS = int(os.getenv("STALE_RUN_SECONDS", "180"))

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


def _memory_active_key(sid, tab_id):
    return f"{sid}:{tab_id}"


def _load_state_unlocked(run_id):
    if not run_id:
        return _build_default_state()

    state = session_store.get_json("result", run_id)
    if not state:
        state = _build_default_state()
        state["run_id"] = run_id
        session_store.set_json("result", run_id, state)
    return state


def _save_state_unlocked(run_id, state):
    if not run_id:
        return

    state["updated_at"] = time.time()
    session_store.set_json("result", run_id, state)


def set_active_run(sid, tab_id, run_id):
    if not tab_id:
        return

    key = _memory_active_key(sid, tab_id)
    session_store.set_json("active_run", key, run_id)


def get_active_run(sid, tab_id):
    if not tab_id:
        return None

    key = _memory_active_key(sid, tab_id)
    return session_store.get_json("active_run", key)


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
        from core.extractor import extract_all_async

        # Run title and summary concurrently
        log_pipeline(run_id, "Starting title generation")
        log_pipeline(run_id, "Starting summarisation")
        update_step(run_id, "title", "active")
        update_step(run_id, "summary", "active")

        with ThreadPoolExecutor(max_workers=2) as pool:
            title_future = pool.submit(generate_title, transcript)
            summary_future = pool.submit(summarize, transcript)
            title = title_future.result()
            update_step(run_id, "title", "done")
            log_pipeline(run_id, "Title generation done")
            summary = summary_future.result()
            update_step(run_id, "summary", "done")
            log_pipeline(run_id, "Summarisation done")

        # Run all 3 extractors concurrently using asyncio
        log_pipeline(run_id, "Starting extraction")
        update_step(run_id, "extract", "active")

        import asyncio
        extraction = asyncio.run(extract_all_async(transcript))
        action_items = extraction["action_items"]
        key_decisions = extraction["key_decisions"]
        open_questions = extraction["open_questions"]

        update_step(run_id, "extract", "done")
        log_pipeline(run_id, "Extraction done")

        from core.rag_engine import build_rag_chain

        log_pipeline(run_id, "Starting RAG vector store")
        update_step(run_id, "rag", "active")
        rag_chain = build_rag_chain(transcript, run_id=run_id)
        update_step(run_id, "rag", "done")
        log_pipeline(run_id, f"Pinecone vector store done at namespace {run_id}")

        RAG_CHAINS[run_id] = rag_chain
        update_state(
            run_id,
            processing=False,
            pipeline_done=True,
            pinecone_ready=True,
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
@jwt_required
def get_state():
    sid = get_session_id()
    tab_id = get_request_tab_id()
    run_id = get_request_run_id() or get_active_run(sid, tab_id)
    state = ensure_state(run_id)
    return jsonify(serialize_state(state))


@app.post("/api/analyze")
@jwt_required
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
@jwt_required
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
        pinecone_ready = state.get("pinecone_ready")
        if pinecone_ready:
            from core.rag_engine import load_rag_chain

            rag_chain = load_rag_chain(run_id)
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
@jwt_required
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
